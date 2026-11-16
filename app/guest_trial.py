"""Guest trial protocol shared by the HTTP gateway and isolated chat worker."""
from dataclasses import dataclass
from hashlib import sha256
from datetime import datetime, timezone
import hmac
import ipaddress
import os
import secrets
from uuid import UUID

from fastapi import HTTPException

COOKIE = 'waveguide_guest'
MAX_AGE = 90 * 86400
ERRORS = {
    'GUEST_LIMIT_REACHED': (403, 'Create an account to continue chatting.'),
    'INVALID_GUEST_SESSION': (401, 'Your guest session could not be verified.'),
    'REQUEST_IN_PROGRESS': (409, 'Another message is being processed. Please wait.'),
    'IDEMPOTENCY_CONFLICT': (409, 'This request ID belongs to a different message.'),
    'GUEST_RATE_LIMITED': (429, 'Too many requests. Please try again later.'),
    'IP_RATE_LIMITED': (429, 'Too many requests from this network. Please try again later.'),
    'TOO_MANY_GUEST_SESSIONS': (429, 'The guest trial creation limit for this network has been reached.'),
    'GLOBAL_AI_BUDGET_EXCEEDED': (503, 'WaveGuide is busy. Please try again later.'),
    'NOT_FOUND': (404, 'Conversation not found.'),
    'LEASE_LOST': (503, 'Request expired. Please retry.'),
    'CHAT_FAILED': (503, 'Chat could not be completed. Please retry.'),
    'CLAIM_CONFLICT': (409, 'This guest conversation cannot be transferred.'),
}


@dataclass
class GuestRun:
    """Server-only context for the shared pipeline; never parsed from browser input."""
    conversation: str
    history: list
    context: dict | None = None
    charge: bool = False


def settings():
    """Read bounded server settings; the lifetime five-message limit lives in PostgreSQL."""
    defaults = {'hour_limit':30, 'attempt_limit':10, 'success_limit':15, 'create_limit':3,
                'concurrent':12, 'minute_budget':120, 'day_budget':4000}
    return {k:max(1,int(os.getenv('WG_'+k.upper(),v))) for k,v in defaults.items()}


def reject(code, **extra):
    """Map trusted error codes to stable public messages and retry hints."""
    status, message = ERRORS.get(code, ERRORS['CHAT_FAILED'])
    retry = extra.get('retry')
    raise HTTPException(status, {'code':code, 'message':message, **extra},
                        headers={'Retry-After':str(max(1,int(retry)))} if retry else None)


def rpc(op, **args):
    """Use a restricted server-only PostgreSQL entry point; fail closed if unavailable."""
    from app.supabase_client import supabase
    try:
        value = supabase.rpc('waveguide_trial', {'op':op, 'a':args}).execute().data
    except Exception:
        reject('CHAT_FAILED')
    if not isinstance(value, dict):
        reject('CHAT_FAILED')
    if 'error' in value:
        reject(value['error'], **{k:v for k,v in value.items() if k in ('retry','guest')})
    return value


def guest_hash(request):
    """Treat only a correctly encoded random token as a guest credential."""
    import re
    token = request.cookies.get(COOKIE, '')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{43}', token):
        reject('INVALID_GUEST_SESSION')
    return sha256(token.encode()).hexdigest()


def trusted_ip(request):
    """Only the server-authenticated proxy may assert the canonical client address."""
    key = os.getenv('INTERNAL_PROXY_SECRET','')
    salt = os.getenv('GUEST_IP_HMAC_SECRET','')
    if len(key)<32 or len(salt)<32:
        reject('CHAT_FAILED')
    if not secrets.compare_digest(request.headers.get('x-waveguide-proxy','').encode(),key.encode()):
        raise HTTPException(403, 'Guest proxy authentication required.')
    try:
        address = ipaddress.ip_address(request.headers.get('x-waveguide-ip',''))
        if isinstance(address,ipaddress.IPv6Address) and address.ipv4_mapped:
            address=address.ipv4_mapped
    except ValueError:
        raise HTTPException(403,'Invalid proxy address.')
    return hmac.new(salt.encode(),datetime.now(timezone.utc).date().isoformat().encode()+b':'+address.packed,'sha256').hexdigest()


def uuid_string(value):
    """Accept only UUIDs for guest conversation and submission identifiers."""
    try:
        return str(UUID(str(value)))
    except (ValueError,TypeError):
        raise HTTPException(422,'Expected a UUID.')


def bounded_prompt(text: str) -> str:
    """Refuse oversized server-assembled evidence without silently dropping requested games."""
    if len(text)>int(os.getenv('WG_MAX_PROMPT_CHARS','750000')):
        raise HTTPException(413,{'code':'CONTEXT_TOO_LARGE','message':'This analysis is too large. Try a narrower question.'})
    return text
