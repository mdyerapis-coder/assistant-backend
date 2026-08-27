"""Bearer-token auth dependency — the only auth this backend has.

One static token, generated once (scripts/gen_bearer_token.py), compared in
constant time. No refresh, no expiry: this is one person's one phone talking
to one backend. See docs/plan.md section 1, "Auth (phone <-> backend)".
"""

import secrets

from fastapi import Header, HTTPException, status

from . import config


async def require_bearer_token(authorization: str = Header(default="")) -> None:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        token, config.ASSISTANT_BEARER_TOKEN
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid bearer token",
        )
