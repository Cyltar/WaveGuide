"""HTTP guest identity and admission in front of WaveGuide's existing chat implementation."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

from fastapi import HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from app.guest_trial import COOKIE, MAX_AGE, guest_hash, reject, rpc, settings, trusted_ip, uuid_string


def enabled():
    """Deploy database and proxy before enabling the trial."""
    return os.getenv('WG_GUEST_ENABLED','').lower() == 'true'


async def read_body(request):
    """Enforce the actual byte limit even without a Content-Length header."""
    data=bytearray()
    async for chunk in request.stream():
        if len(data)+len(chunk)>16384:
            raise HTTPException(413,'Message body is too large.')
        data.extend(chunk)
    try:
        body=json.loads(data)
    except (ValueError,UnicodeDecodeError):
        raise HTTPException(422,'Invalid JSON body.')
    if not isinstance(body,dict) or set(body)-{'message','session_id','request_id'}:
        raise HTTPException(422,'Unexpected chat fields.')
    if not isinstance(body.get('message'),str) or not body['message'].strip():
        raise HTTPException(422,'Enter a message.')
    return body


def run_job(job):
    """Keep blocking provider operations out of the HTTP worker and bound their runtime."""
    duration=min(900,max(30,int(os.getenv('WG_CHAT_TIMEOUT_SECONDS','240'))))
    job['deadline']=time.time()+duration
    try:
        process=subprocess.run([sys.executable,'-m','app.guest_worker'],input=json.dumps(job),
            text=True,encoding='utf-8',capture_output=True,timeout=duration+5,
            cwd=str(Path(__file__).resolve().parents[1]),env={**os.environ,'PYTHONIOENCODING':'utf-8'})
        payload=json.loads(process.stdout)
        if 'data' in payload:
            return payload['data']
        raise HTTPException(payload['status'],payload['detail'],headers=payload.get('headers'))
    except (subprocess.TimeoutExpired,ValueError,OSError,KeyError):
        reject('CHAT_FAILED')
    finally:
        rpc('release',fence=job['fence'])


def mount_guest(app, authenticated, legacy_chat, model):
    """Install the gateway without weakening the authenticated account endpoints."""
    def guest_identity(request):
        if not enabled():
            raise HTTPException(404,'Not found.')
        if 'authorization' in request.headers:
            authenticated(request.headers['authorization'])
            raise HTTPException(409,'Use your authenticated account.')
        return trusted_ip(request)

    @app.get('/guest/status')
    def status(request:Request,response:Response):
        guest_identity(request)
        response.headers['Cache-Control']='no-store'
        return rpc('status',token_hash=guest_hash(request))

    @app.post('/guest/session')
    def initialize(request:Request,response:Response):
        ip=guest_identity(request)
        response.headers['Cache-Control']='no-store'
        if request.cookies.get(COOKIE):
            try:
                return rpc('status',token_hash=guest_hash(request))
            except HTTPException as exc:
                if not isinstance(exc.detail,dict) or exc.detail.get('code')!='INVALID_GUEST_SESSION':
                    raise
        token=secrets.token_urlsafe(32)
        value=rpc('create',token_hash=hashlib.sha256(token.encode()).hexdigest(),ip=ip,**settings())
        response.set_cookie(COOKIE,token,max_age=MAX_AGE,secure=True,httponly=True,samesite='lax',path='/')
        return value

    @app.get('/guest/sessions')
    def sessions(request:Request,response:Response):
        guest_identity(request)
        response.headers['Cache-Control']='no-store'
        return rpc('sessions',token_hash=guest_hash(request))

    @app.get('/guest/sessions/{session_id}')
    def messages(session_id:str,request:Request,response:Response):
        guest_identity(request)
        response.headers['Cache-Control']='no-store'
        return rpc('messages',token_hash=guest_hash(request),session_id=uuid_string(session_id))

    @app.post('/chat')
    async def submit(request:Request):
        body=await read_body(request)
        bearer=request.headers.get('authorization')
        auth=await run_in_threadpool(authenticated,bearer) if bearer is not None or not enabled() else None
        if not enabled():
            return await run_in_threadpool(legacy_chat,model(**body),auth)
        if len(body['message'])>(int(os.getenv('WG_GUEST_MAX_CHARS','1500')) if not auth else 12000):
            raise HTTPException(413,'Message is too long.')
        if auth:
            lease=await run_in_threadpool(rpc,'account_admit',**settings())
            job={'guest':False,'user':auth.user_id,'bearer':auth.access_token}
        else:
            ip=trusted_ip(request)
            token=guest_hash(request)
            body['request_id']=uuid_string(body.get('request_id'))
            if body.get('session_id') is not None:
                body['session_id']=uuid_string(body['session_id'])
            digest=hashlib.sha256(json.dumps([body['message'],body.get('session_id')],ensure_ascii=False).encode()).hexdigest()
            lease=await run_in_threadpool(rpc,'admit',token_hash=token,ip=ip,rid=body['request_id'],
                session_id=body.get('session_id'),digest=digest,**settings())
            if 'replay' in lease:
                return lease['replay']
            job={'guest':True,'token_hash':token,'conversation':lease['session_id']}
        return await run_in_threadpool(run_job,{**job,'body':body,'fence':lease['fence']})
