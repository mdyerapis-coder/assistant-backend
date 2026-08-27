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
# Deliberately configurable, not hardcoded to api.openai.com — the OpenAI SDK
# accepts any OpenAI-Chat-Completions-compatible base_url. Currently pointed
# at Cline's own gateway (api.cline.bot), which fronts Anthropic/OpenAI/Google/
# etc. behind one key with namespaced model ids (e.g. "anthropic/claude-...").
# Leave unset to fall back to the SDK's own default (api.openai.com).
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "") or None
GOOGLE_CLIENT_SECRET_JSON = os.environ.get("GOOGLE_CLIENT_SECRET_JSON", "")

DB_PATH = os.environ.get("ASSISTANT_DB_PATH", "assistant.db")
