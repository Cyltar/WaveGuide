from dataclasses import dataclass
from fastapi import Header, HTTPException
from app.supabase_client import supabase


@dataclass
class AuthenticatedUser:
    user_id: str
    access_token: str


def get_current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required."
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization header."
        )

    token = authorization.removeprefix(
        "Bearer "
    ).strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required."
        )

    try:
        response = supabase.auth.get_user(
            token
        )

        if response.user is None:
            raise HTTPException(
                status_code=401,
                detail=(
                    "Invalid or expired "
                    "access token."
                )
            )

        return AuthenticatedUser(
            user_id=str(response.user.id),
            access_token=token
        )

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            status_code=401,
            detail=(
                "Invalid or expired "
                "access token."
            )
        )