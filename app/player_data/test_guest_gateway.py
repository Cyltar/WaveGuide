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
