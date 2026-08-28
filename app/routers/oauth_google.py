"""Google OAuth 2.0 auth-code flow — backend-anchored confidential client.

See docs/adr/007-google-oauth-backend-anchored.md. The phone never holds
the OAuth secret; it just opens a Custom Tab at GET /oauth/google/start
and gets deep-linked back via assistantapp://oauth-complete once the
backend finishes the exchange and stores the tokens.

Endpoints:
- GET /oauth/google/start — generates CSRF state, redirects to Google
- GET /oauth/google/callback — exchanges code for tokens, stores encrypted
- GET /oauth/google/status — returns whether Google is connected
- DELETE /oauth/google — removes stored tokens
"""

import datetime
import logging
import secrets
from typing import Annotated

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
DEEPLINK_SCHEME = "assistantapp"
DEEPLINK_HOST = "oauth-complete"


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
    from urllib.parse import urlencode
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

    creds = Credentials(
        token=None,
        refresh_token=None,
        id_token=None,
        token_uri=client_config["token_uri"],
        client_id=client_config["client_id"],
        client_secret=client_config["client_secret"],
        scopes=GOOGLE_SCOPES,
    )
    creds.fetch(code=code, request=GoogleRequest())

    if not creds.refresh_token:
        raise HTTPException(
            status_code=400,
            detail="No refresh_token returned. Re-consent with prompt=consent, "
                   "or remove the existing grant in your Google account settings.",
        )

    access_token_enc = _encrypt(creds.token)
    refresh_token_enc = _encrypt(creds.refresh_token)
    expiry = creds.expiry.isoformat() if creds.expiry else _now_iso()
    scope = " ".join(creds.scopes or GOOGLE_SCOPES)

    conn = db.get_connection()
    await conn.execute(
        "INSERT OR REPLACE INTO google_oauth_tokens "
        "(provider, access_token_enc, refresh_token_enc, expiry, scope, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("google", access_token_enc, refresh_token_enc, expiry, scope, _now_iso()),
    )
    await conn.commit()

    deep_link = f"{DEEPLINK_SCHEME}://{DEEPLINK_HOST}"
    return RedirectResponse(deep_link)


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
    """Load and refresh the stored Google credentials. Returns None if not connected."""
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

    creds = Credentials(
        token=_decrypt(row[0]),
        refresh_token=_decrypt(row[1]),
        token_uri=client_config["token_uri"],
        client_id=client_config["client_id"],
        client_secret=client_config["client_secret"],
        scopes=row[3].split(),
    )

    if creds.expired or (creds.expiry and creds.expiry <= datetime.datetime.now(datetime.timezone.utc)):
        try:
            creds.refresh(GoogleRequest())
        except Exception:
            logger.exception("Failed to refresh Google OAuth token")
            return None
        new_expiry = creds.expiry.isoformat() if creds.expiry else _now_iso()
        await conn.execute(
            "UPDATE google_oauth_tokens SET access_token_enc = ?, expiry = ?, updated_at = ? WHERE provider = ?",
            (_encrypt(creds.token), new_expiry, _now_iso(), "google"),
        )
        await conn.commit()

    return creds
