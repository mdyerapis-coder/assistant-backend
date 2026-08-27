#!/usr/bin/env bash
# Pull secrets from Mason's Bitwarden *personal* vault, write them into
# assistant.env, restart the service only if something actually changed.
# See docs/adr/011-bitwarden-secret-sync.md for the full design and the
# accepted tradeoff (this needs the vault master password on the box).
#
# Reads credentials from ~/.bw-sync.env (0600, NOT assistant.env — kept
# separate on purpose):
#   BW_CLIENTID / BW_CLIENTSECRET   — Bitwarden personal API key
#                                     (web vault -> Account Settings -> API Key)
#   BW_MASTER_PASSWORD              — the vault master password. This is the
#                                     single most sensitive file on the box now.
#
# One-time setup this script assumes has already been done:
#   1. `bw config server` if using a self-hosted Bitwarden instance (skip for bitwarden.com)
#   2. `bw login --apikey` once, interactively, using BW_CLIENTID/BW_CLIENTSECRET
#      (this persists login state under ~/.config/Bitwarden CLI/, separate from
#      the per-run unlock this script does)
#   3. Item IDs below (OPENAI_ITEM_ID etc.) filled in to point at real vault items

set -euo pipefail

ENV_FILE="/opt/assistant-backend/assistant.env"
BW_ENV_FILE="${HOME}/.bw-sync.env"

# --- item IDs: fill these in after creating the corresponding Bitwarden items ---
# `bw list items --search "<name>"` to find an item's id.
OPENAI_ITEM_ID="${OPENAI_ITEM_ID:-}"
GOOGLE_CLIENT_SECRET_ITEM_ID="${GOOGLE_CLIENT_SECRET_ITEM_ID:-}"
# ASSISTANT_BEARER_TOKEN is deliberately NOT synced from Bitwarden — it's a
# phone<->backend secret generated once by gen_bearer_token.py, not an
# upstream API credential subject to third-party rotation.

if [[ ! -f "$BW_ENV_FILE" ]]; then
  echo "[secrets-sync] $BW_ENV_FILE not found — nothing to do (one-time setup incomplete)" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$BW_ENV_FILE"

export BW_CLIENTID BW_CLIENTSECRET

SESSION="$(bw unlock --passwordenv BW_MASTER_PASSWORD --raw)"
export BW_SESSION="$SESSION"

bw sync --session "$SESSION" >/dev/null

get_field() {
  # $1 = item id, $2 = field name on the item (defaults to the item's password)
  local item_id="$1"
  bw get item "$item_id" --session "$SESSION" | python3 -c "
import json, sys
item = json.load(sys.stdin)
print(item.get('login', {}).get('password') or '')
"
}

OPENAI_API_KEY="$([[ -n "$OPENAI_ITEM_ID" ]] && get_field "$OPENAI_ITEM_ID" || echo "")"
GOOGLE_CLIENT_SECRET_JSON="$([[ -n "$GOOGLE_CLIENT_SECRET_ITEM_ID" ]] && get_field "$GOOGLE_CLIENT_SECRET_ITEM_ID" || echo "")"

# Preserve the existing bearer token and DB path — this script only manages
# the upstream API credentials, never the phone<->backend token.
EXISTING_BEARER_TOKEN=""
EXISTING_DB_PATH="/opt/assistant-backend/assistant.db"
if [[ -f "$ENV_FILE" ]]; then
  EXISTING_BEARER_TOKEN="$(grep -oP '(?<=^ASSISTANT_BEARER_TOKEN=).*' "$ENV_FILE" || true)"
  EXISTING_DB_PATH="$(grep -oP '(?<=^ASSISTANT_DB_PATH=).*' "$ENV_FILE" || echo "$EXISTING_DB_PATH")"
fi

NEW_CONTENT="ASSISTANT_BEARER_TOKEN=${EXISTING_BEARER_TOKEN}
OPENAI_API_KEY=${OPENAI_API_KEY}
GOOGLE_CLIENT_SECRET_JSON=${GOOGLE_CLIENT_SECRET_JSON}
ASSISTANT_DB_PATH=${EXISTING_DB_PATH}
"

if [[ -f "$ENV_FILE" ]] && diff -q <(echo "$NEW_CONTENT") "$ENV_FILE" >/dev/null 2>&1; then
  echo "[secrets-sync] no change"
  exit 0
fi

echo "$NEW_CONTENT" > "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "[secrets-sync] secrets changed — restarting assistant.service"
systemctl restart assistant.service
