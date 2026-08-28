"""Configuration loaded from the process environment.

Populated in production by scripts/sync_secrets_from_bitwarden.sh writing
assistant.env, which systemd's EnvironmentFile= feeds into this process. See
docs/adr/011-bitwarden-secret-sync.md for why that's a restart-on-change
pull rather than something this module reaches out to Bitwarden for itself.

ASSISTANT_BEARER_TOKEN is required and deliberately has no default — a
backend that silently ran with no real auth check would be worse than one
that refuses to start. See docs/adr/002-errors-carry-intent.md.
"""

import json
import os
from pathlib import Path

ASSISTANT_BEARER_TOKEN = os.environ["ASSISTANT_BEARER_TOKEN"]

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
# Deliberately configurable, not hardcoded to api.openai.com — the OpenAI SDK
# accepts any OpenAI-Chat-Completions-compatible base_url. Currently pointed
# at Cline's own gateway (api.cline.bot), which fronts Anthropic/OpenAI/Google/
# etc. behind one key with namespaced model ids (e.g. "anthropic/claude-...").
# Leave unset to fall back to the SDK's own default (api.openai.com).
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "") or None
GOOGLE_CLIENT_SECRET_JSON = os.environ.get("GOOGLE_CLIENT_SECRET_JSON", "")

DB_PATH = os.environ.get("ASSISTANT_DB_PATH", "assistant.db")

# --- Phase 03: Google OAuth (Calendar + Gmail) ---

# The public URL the phone reaches the backend at. Defaults to the
# production URL so the OAuth redirect_uri works out of the box. A
# Bitwarden sync that doesn't carry ASSISTANT_PUBLIC_URL won't break the
# OAuth flow. Override via env var for local dev.
PUBLIC_BASE_URL = os.environ.get("ASSISTANT_PUBLIC_URL", "https://assistant.llmclouds.au")
GOOGLE_OAUTH_REDIRECT_URI = os.environ.get(
    "GOOGLE_OAUTH_REDIRECT_URI",
    f"{PUBLIC_BASE_URL}/oauth/google/callback",
)


def get_google_token_encryption_key() -> str:
    """Read the Fernet key for OAuth token encryption at rest.

    Order of precedence:
    1. GOOGLE_TOKEN_ENCRYPTION_KEY env var (fast, but Bitwarden sync may strip)
    2. /opt/assistant-backend/.google-token-key (file on the VPS that the
       sync script doesn't touch — survives Bitwarden rewrites)

    Without one of these, OAuth tokens can't be stored. Generate with:
        python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    """
    env_key = os.environ.get("GOOGLE_TOKEN_ENCRYPTION_KEY", "")
    if env_key:
        return env_key
    key_file = Path("/opt/assistant-backend/.google-token-key")
    if key_file.exists():
        return key_file.read_text().strip()
    return ""


def get_google_oauth_client_config() -> dict:
    """Parse GOOGLE_CLIENT_SECRET_JSON into the dict google-auth expects."""
    if not GOOGLE_CLIENT_SECRET_JSON:
        return {}
    parsed = json.loads(GOOGLE_CLIENT_SECRET_JSON)
    # The JSON is in the "web" client format — extract the relevant fields.
    web = parsed.get("web", parsed)
    return {
        "client_id": web["client_id"],
        "client_secret": web["client_secret"],
        "auth_uri": web.get("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
        "token_uri": web.get("token_uri", "https://oauth2.googleapis.com/token"),
        "auth_provider_x509_cert_url": web.get(
            "auth_provider_x509_cert_url",
            "https://www.googleapis.com/oauth2/v1/certs",
        ),
    }
