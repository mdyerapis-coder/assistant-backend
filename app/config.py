"""Configuration loaded from the process environment.

Populated in production by scripts/sync_secrets_from_bitwarden.sh writing
assistant.env, which systemd's EnvironmentFile= feeds into this process. See
docs/adr/011-bitwarden-secret-sync.md for why that's a restart-on-change
pull rather than something this module reaches out to Bitwarden for itself.

ASSISTANT_BEARER_TOKEN is required and deliberately has no default — a
backend that silently ran with no real auth check would be worse than one
that refuses to start. See docs/adr/002-errors-carry-intent.md.
"""

import os

ASSISTANT_BEARER_TOKEN = os.environ["ASSISTANT_BEARER_TOKEN"]

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
GOOGLE_CLIENT_SECRET_JSON = os.environ.get("GOOGLE_CLIENT_SECRET_JSON", "")

DB_PATH = os.environ.get("ASSISTANT_DB_PATH", "assistant.db")
