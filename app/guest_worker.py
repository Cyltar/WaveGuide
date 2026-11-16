"""Bounded chat execution with an independent lease heartbeat and a hard process deadline."""
import json
import os
import sys
import threading
import time

from fastapi import HTTPException
from app.guest_trial import GuestRun, rpc


def execute(job):
    """Run exactly the existing chat pipeline, then atomically finish a guest response."""
    from app.app import AuthenticatedUser, ChatRequest, chat
    if job['guest']:
        history = []
        if job['body'].get('session_id'):
            history = rpc('messages',token_hash=job['token_hash'],session_id=job['body']['session_id'])['messages']
        auth = GuestRun(job['conversation'],[{'role':m['role'],'content':m['content']} for m in history[-10:]])
    else:
        auth = AuthenticatedUser(job['user'],job['bearer'])
    result = chat(ChatRequest(**job['body']),auth)
    if not result.answer or not result.answer.strip():
        raise HTTPException(503,{'code':'CHAT_FAILED','message':'No response was generated.'})
    if not job['guest']:
        return result.model_dump()
    ctx = auth.context or {}
    if ctx.get('riot_rate_limited'):
        raise HTTPException(503,{'code':'RIOT_RATE_LIMITED','message':result.answer},
                            headers={'Retry-After':str(ctx['retry_after'])} if ctx.get('retry_after') else None)
    return rpc('finish', token_hash=job['token_hash'], rid=job['body']['request_id'],fence=job['fence'],
               message=job['body']['message'],answer=result.answer,context=ctx,charge=auth.charge)


def main():
    """A worker may outlive its HTTP client but must never outlive its execution lease."""
    job=json.load(sys.stdin)
    wire=sys.stdout
    sys.stdout=sys.stderr
    last=[time.monotonic()]
    def watchdog():
        while True:
            if time.time()>=job['deadline'] or time.monotonic()-last[0]>80:
                os._exit(75)
            time.sleep(1)
    def heartbeat():
        while True:
            started=time.monotonic()
            if not rpc('renew',fence=job['fence']).get('renewed'):
                os._exit(75)
            last[0]=started
            time.sleep(20)
    threading.Thread(target=watchdog,daemon=True).start()
    try:
        if not rpc('renew',fence=job['fence']).get('renewed'):
            raise HTTPException(503,'Request expired.')
        threading.Thread(target=heartbeat,daemon=True).start()
        payload={'data':execute(job)}
    except HTTPException as exc:
        detail=exc.detail
        if job['guest'] and isinstance(detail,dict) and detail.get('code') in {'AI_UNAVAILABLE','DAILY_LIMIT_REACHED'}:
            detail={'code':'GEMINI_UNAVAILABLE','message':'The coaching service is temporarily unavailable.'}
        payload={'status':exc.status_code,'detail':detail,'headers':exc.headers}
    except Exception:
        payload={'status':503,'detail':{'code':'CHAT_FAILED','message':'Request failed. Please retry.'}}
    finally:
        rpc('release',fence=job['fence'])
    print(json.dumps(payload),file=wire,flush=True)


if __name__=='__main__':
    main()
