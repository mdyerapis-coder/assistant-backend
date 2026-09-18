"""Google OAuth 2.0 auth-code flow — backend-anchored confidential client.

See docs/adr/007-google-oauth-backend-anchored.md and docs/oauth-relay.md.
The phone never holds the OAuth secret; it opens a Custom Tab at
GET /oauth/google/start and is deep-linked back via
sableapp://oauth-complete (live assistant-android; override with
GOOGLE_OAUTH_DEEPLINK) once this host finishes the exchange and stores
the tokens. client_secret and GOOGLE_TOKEN_ENCRYPTION_KEY stay here.

Endpoints:
- GET /oauth/google/start — generates CSRF state, redirects to Google
- GET /oauth/google/callback — exchanges code for tokens, stores encrypted
- GET /oauth/google/status — returns whether Google is connected
- DELETE /oauth/google — removes stored tokens
"""

import datetime
import json
import logging
import secrets
from typing import Annotated
from urllib.parse import urlencode

import aiohttp
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials

from .. import config, db
from ..auth import require_bearer_token

logger = logging.getLogger(__name__)

router = APIRouter()

# Scopes we request: Calendar (read events) + Gmail (read + send).
# See docs/plan.md §1 — narrower than full-mailbox read/write.
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

STATE_TTL_SECONDS = 600  # 10 minutes
# Defaults aligned with assistant-android (package com.mdyerapis.sable).
# Historical alias this file used to emit: assistantapp://oauth-complete.
DEEPLINK_SCHEME = "sableapp"
DEEPLINK_HOST = "oauth-complete"
DEFAULT_OAUTH_COMPLETE_DEEPLINK = f"{DEEPLINK_SCHEME}://{DEEPLINK_HOST}"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _get_fernet() -> Fernet:
    """Return a Fernet instance using the configured encryption key."""
    key = config.get_google_token_encryption_key()
    if not key:
        raise RuntimeError(
            "GOOGLE_TOKEN_ENCRYPTION_KEY is not set — cannot store tokens. "
            "Generate one with: python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return Fernet(key.encode())


def _encrypt(plaintext: str) -> bytes:
    return _get_fernet().encrypt(plaintext.encode())


def _decrypt(ciphertext: bytes) -> str:
    try:
        return _get_fernet().decrypt(ciphertext).decode()
    except InvalidToken as e:
        raise RuntimeError("Failed to decrypt Google OAuth token — encryption key may have changed") from e


async def _store_state(state: str) -> None:
    """Persist a CSRF state token with TTL."""
    conn = db.get_connection()
    expires_at = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(seconds=STATE_TTL_SECONDS)
    ).isoformat()
    await conn.execute(
        "INSERT INTO oauth_states (state, created_at, expires_at) VALUES (?, ?, ?)",
        (state, _now_iso(), expires_at),
    )
    await conn.commit()


async def _consume_state(state: str) -> bool:
    """Validate and delete a CSRF state token. Returns True if valid."""
    conn = db.get_connection()
    now = _now_iso()
    async with conn.execute(
        "SELECT expires_at FROM oauth_states WHERE state = ?", (state,)
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return False
    if row[0] < now:
        await conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        await conn.commit()
        return False
    await conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
    await conn.commit()
    return True


async def _exchange_code_for_tokens(
    code: str,
    client_config: dict,
) -> dict:
    """Exchange an OAuth auth code for tokens via direct HTTP POST.

    google-auth's Credentials class doesn't have a .fetch(code=...) method
    (it has .refresh() for refreshing existing tokens, not initial
    exchange). The standard pattern is to POST to the token endpoint
    directly with the code and exchange parameters.
    """
    payload = {
        "code": code,
        "client_id": client_config["client_id"],
        "client_secret": client_config["client_secret"],
        "redirect_uri": config.GOOGLE_OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            client_config["token_uri"],
            data=payload,
            headers={"Accept": "application/json"},
        ) as resp:
            body = await resp.text()
            if resp.status != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"Google token endpoint returned {resp.status}: {body[:300]}",
                )
            return json.loads(body)


@router.get("/oauth/google/start")
async def oauth_google_start() -> RedirectResponse:
    """Redirect to Google's OAuth consent screen with a CSRF state token."""
    client_config = config.get_google_oauth_client_config()
    if not client_config:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth is not configured on this backend.",
        )

    state = secrets.token_urlsafe(32)
    await _store_state(state)

    params = {
        "client_id": client_config["client_id"],
        "redirect_uri": config.GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    auth_url = f"{client_config['auth_uri']}?{urlencode(params)}"
    return RedirectResponse(auth_url)


@router.get("/oauth/google/callback")
async def oauth_google_callback(
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
) -> RedirectResponse:
    """Exchange the auth code for tokens and store them encrypted."""
    if not await _consume_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired state token.")

    client_config = config.get_google_oauth_client_config()
    if not client_config:
        raise HTTPException(status_code=503, detail="Google OAuth not configured.")

    token_response = await _exchange_code_for_tokens(code, client_config)
    access_token = token_response.get("access_token")
    refresh_token = token_response.get("refresh_token")
    expires_in = token_response.get("expires_in", 3600)
    scope = token_response.get("scope", " ".join(GOOGLE_SCOPES))

    if not access_token or not refresh_token:
        raise HTTPException(
            status_code=400,
            detail=f"No tokens in Google response: {json.dumps(token_response)[:300]}",
        )

    expiry = (
        datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(seconds=expires_in)
    ).isoformat()

    access_token_enc = _encrypt(access_token)
    refresh_token_enc = _encrypt(refresh_token)

    conn = db.get_connection()
    await conn.execute(
        "INSERT OR REPLACE INTO google_oauth_tokens "
        "(provider, access_token_enc, refresh_token_enc, expiry, scope, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("google", access_token_enc, refresh_token_enc, expiry, scope, _now_iso()),
    )
    await conn.commit()

    return RedirectResponse(config.GOOGLE_OAUTH_DEEPLINK)


@router.get("/oauth/google/status", dependencies=[Depends(require_bearer_token)])
async def oauth_google_status() -> dict:
    """Return whether Google OAuth is connected."""
    conn = db.get_connection()
    async with conn.execute(
        "SELECT expiry, scope, updated_at FROM google_oauth_tokens WHERE provider = ?",
        ("google",),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return {"connected": False}
    return {
        "connected": True,
        "expiry": row[0],
        "scope": row[1],
        "updated_at": row[2],
    }


@router.delete("/oauth/google", dependencies=[Depends(require_bearer_token)])
async def oauth_google_disconnect() -> dict:
    """Remove the stored Google OAuth tokens."""
    conn = db.get_connection()
    await conn.execute(
        "DELETE FROM google_oauth_tokens WHERE provider = ?", ("google",)
    )
    await conn.commit()
    return {"ok": True}


async def get_google_credentials() -> Credentials | None:
    """Load the stored Google credentials and return them.

    Returns a google.oauth2.credentials.Credentials with the access token
    (refreshed if expired) ready for use with google-api-python-client or
    direct HTTP calls. Returns None if not connected or if refresh fails.
    """
    conn = db.get_connection()
    async with conn.execute(
        "SELECT access_token_enc, refresh_token_enc, expiry, scope FROM google_oauth_tokens WHERE provider = ?",
        ("google",),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None

    client_config = config.get_google_oauth_client_config()
    if not client_config:
        return None

    access_token = _decrypt(row[0])
    refresh_token = _decrypt(row[1])
    expiry_dt = datetime.datetime.fromisoformat(row[2])
    # Normalize naive timestamps (legacy; creds.expiry from google-auth is naive UTC)
    if expiry_dt.tzinfo is None:
        expiry_dt = expiry_dt.replace(tzinfo=datetime.timezone.utc)
    scope = row[3]
    now = datetime.datetime.now(datetime.timezone.utc)

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=client_config["token_uri"],
        client_id=client_config["client_id"],
        client_secret=client_config["client_secret"],
        scopes=scope.split(),
    )

    # Refresh if expired or about to expire (within 60 seconds).
    if expiry_dt <= now + datetime.timedelta(seconds=60):
        try:
            creds.refresh(GoogleRequest())
        except Exception:
            logger.exception("Failed to refresh Google OAuth token")
            return None
        if creds.expiry is not None:
            exp = creds.expiry
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=datetime.timezone.utc)
            new_expiry = exp.isoformat()
        else:
            new_expiry = _now_iso()
        await conn.execute(
            "UPDATE google_oauth_tokens SET access_token_enc = ?, expiry = ?, updated_at = ? WHERE provider = ?",
            (_encrypt(creds.token), new_expiry, _now_iso(), "google"),
        )
        await conn.commit()

    return creds
