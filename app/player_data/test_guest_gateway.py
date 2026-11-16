"""HTTP-level guest admission tests with provider execution replaced."""
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4
from unittest.mock import Mock, patch
from contextlib import ExitStack

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app import guest_gateway as gateway
from app.guest_trial import COOKIE


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,WG_GUEST_ENABLED='true',INTERNAL_PROXY_SECRET='k'*32,GUEST_IP_HMAC_SECRET='h'*32))
        app=FastAPI()
        self.auth=Mock(side_effect=HTTPException(401,'Invalid token'))
        gateway.mount_guest(app,self.auth,Mock(),Mock())
        self.api=TestClient(app,base_url='https://example.test')
        self.api.headers.update({'x-waveguide-proxy':'k'*32,'x-waveguide-ip':'192.0.2.1'})
        self.rpc=self.stack.enter_context(patch.object(gateway,'rpc',return_value={'messages_remaining':5}))
        self.job=self.stack.enter_context(patch.object(gateway,'run_job'))
        self.body={'request_id':str(uuid4()),'message':'Analyze my last 20 games'}

    def test_cookie_and_restore(self):
        res=self.api.post('/guest/session')
        self.assertEqual(res.status_code,200)
        cookie=res.headers['set-cookie']
        for value in ('HttpOnly','Secure','SameSite=lax','Max-Age=7776000'):
            self.assertIn(value,cookie)
        args=self.rpc.call_args.kwargs
        self.assertNotIn('192.0.2.1',str(args))
        self.assertNotIn(self.api.cookies[COOKIE],str(args))
        self.api.get('/guest/status')
        self.assertEqual(self.rpc.call_args.args,('status',))
        self.assertEqual(self.rpc.call_args.kwargs['token_hash'],args['token_hash'])

    def test_untrusted_forwarding_never_reaches_admission(self):
        self.api.headers.pop('x-waveguide-proxy')
        res=self.api.post('/guest/session',headers={'x-forwarded-for':'192.0.2.99'})
        self.assertEqual(res.status_code,403)
        self.rpc.assert_not_called()

    def test_bearer_does_not_downgrade(self):
        res=self.api.post('/chat',json=self.body,headers={'Authorization':'Bearer invalid'})
        self.assertEqual(res.status_code,401)
        self.rpc.assert_not_called()
        self.job.assert_not_called()

    def test_limits_and_replays_precede_ai(self):
        self.api.cookies.set(COOKIE,'a'*43)
        self.rpc.side_effect=HTTPException(403,{'code':'GUEST_LIMIT_REACHED'})
        self.assertEqual(self.api.post('/chat',json=self.body).status_code,403)
        self.job.assert_not_called()
        self.rpc.side_effect=None
        self.rpc.return_value={'replay':{'answer':'Already saved'}}
        self.assertEqual(self.api.post('/chat',json=self.body).json()['answer'],'Already saved')
        self.job.assert_not_called()

    def test_client_state_and_oversize_are_rejected(self):
        for body in [{**self.body,'guest_id':'fake'},{**self.body,'messages_remaining':5},{**self.body,'message':'x'*1501}]:
            self.assertIn(self.api.post('/chat',json=body).status_code,(413,422))
        self.assertEqual(self.api.post('/chat',content=b' '*20000).status_code,413)
        self.rpc.assert_not_called()

    def test_twenty_game_request_admitted_once(self):
        self.api.cookies.set(COOKIE,'a'*43)
        self.rpc.return_value={'session_id':str(uuid4()),'fence':str(uuid4())}
        self.job.return_value={'answer':'Coaching','guest':{'messages_remaining':4}}
        self.assertEqual(self.api.post('/chat',json=self.body).status_code,200)
        self.rpc.assert_called_once()
        job=self.job.call_args.args[0]
        self.assertTrue(job['guest'])
        self.assertEqual(job['body']['message'],self.body['message'])

    def test_claim_requires_bearer_and_preserves_cookie_on_failure(self):
        import types
        self.api.cookies.set(COOKIE,'a'*43)
        client=Mock()
        storage=types.SimpleNamespace(supabase=client)
        with patch.dict(sys.modules,{'app.supabase_client':storage}):
            self.assertEqual(self.api.post('/guest/claim').status_code,401)
            client.rpc.assert_not_called()
            self.auth.side_effect=None
            self.auth.return_value=types.SimpleNamespace(user_id='verified-id')
            client.rpc.return_value.execute.return_value.data={'error':'REQUEST_IN_PROGRESS','retry':2}
            response=self.api.post('/guest/claim',headers={'Authorization':'Bearer signed'})
            self.assertEqual(response.status_code,409)
            self.assertNotIn('set-cookie',response.headers)
            client.rpc.return_value.execute.return_value.data={'claimed':True}
            result=self.api.post('/guest/claim',headers={'Authorization':'Bearer signed'},json={'user_id':'forged'})
            self.assertEqual(result.status_code,200)
            self.assertIn('Max-Age=0',result.headers['set-cookie'])
            self.assertEqual(client.rpc.call_args.args[1]['account_id'],'verified-id')

class PipelineTests(unittest.TestCase):
    """Run the real shared chat orchestration while replacing remote providers."""
    @classmethod
    def setUpClass(cls):
        from google import genai
        from types import SimpleNamespace
        with patch.object(genai,'Client'), patch.dict(os.environ,GEMINI_API_KEY='offline'), patch.dict(
            sys.modules,{'app.supabase_client':SimpleNamespace(supabase=Mock(),create_user_client=Mock())}):
            import app.app as application
            from app.query_parser import QueryContext
        cls.app=application
        cls.query=QueryContext

    def setUp(self):
        from app import guest_worker
        self.worker=guest_worker
        self.stack=ExitStack()
        self.addCleanup(self.stack.close)
        # Importing the worker's runtime module is local and normally comes from the process entrypoint.
        self.stack.enter_context(patch.dict(sys.modules,{'app.app':self.app}))
        self.context=self.query(player_champion=None,enemy_champion=None,role=None,query_type='general')
        self.stack.enter_context(patch.object(self.app,'parse_query',return_value=self.context))
        self.model=self.stack.enter_context(patch.object(self.app,'ask_gemini',return_value='Grounded answer'))
        self.stack.enter_context(patch.object(self.app,'load_relevant_knowledge',return_value=''))
        self.store=self.stack.enter_context(patch.object(guest_worker,'rpc',return_value={'answer':'saved'}))
        self.job={'guest':True,'conversation':str(uuid4()),'fence':str(uuid4()),'token_hash':'a'*64,
                  'body':{'message':'A question','request_id':str(uuid4())}}

    def test_shared_coaching_and_twenty_games_charge_exactly_once(self):
        for count in (0,20):
            with self.subTest(count=count),patch.object(self.app,'resolve_player_riot_account',return_value={'source':'history'}), \
                    patch.object(self.app,'run_player_analysis',return_value={'games_analyzed':count}):
                if count:
                    self.context.player_analysis.requested=True
                    self.context.player_analysis.mode='recent_games'
                    self.context.player_analysis.game_count=count
                self.worker.execute(self.job)
                self.assertEqual(self.store.call_args.args,('finish',))
                self.assertTrue(self.store.call_args.kwargs['charge'])
                self.store.assert_called_once()
                self.store.reset_mock()

    def test_missing_riot_id_cannot_lookup_account_or_charge(self):
        self.context.player_analysis.requested=True
        self.context.player_analysis.mode='recent_games'
        with patch.object(self.app,'get_riot_account') as lookup:
            self.worker.execute(self.job)
        lookup.assert_not_called()
        self.model.assert_not_called()
        self.assertFalse(self.store.call_args.kwargs['charge'])

    def test_riot_limit_and_provider_failure_skip_finalization(self):
        RiotRateLimitError = self.app.RiotRateLimitError
        self.context.player_analysis.requested=True
        self.context.player_analysis.mode='recent_games'
        with patch.object(self.app,'resolve_player_riot_account',side_effect=RiotRateLimitError(19)):
            with self.assertRaises(HTTPException) as error:
                self.worker.execute(self.job)
        self.assertEqual(error.exception.detail['code'],'RIOT_RATE_LIMITED')
        self.store.assert_not_called()
        self.context.player_analysis.requested=False
        self.model.side_effect=HTTPException(503,{'code':'AI_UNAVAILABLE'})
        with self.assertRaises(HTTPException): self.worker.execute(self.job)
        self.store.assert_not_called()


    def test_oversized_assembled_context_is_not_silently_truncated(self):
        from app.guest_trial import bounded_prompt
        with patch.dict(os.environ,WG_MAX_PROMPT_CHARS='10'):
            with self.assertRaises(HTTPException) as error: bounded_prompt('x'*11)
            self.assertEqual(error.exception.detail['code'],'CONTEXT_TOO_LARGE')
            self.assertEqual(bounded_prompt('x'*10),'x'*10)
