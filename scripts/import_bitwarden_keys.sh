#!/usr/bin/env bash
# Syncs model-provider API keys from Mason's Bitwarden vault into the LOCAL
# assistant-backend dev process (hub: assistant-backend). Never print keys.
#
# Prereq (operator does this, I never handle the master password):
#   bw unlock --raw > ~/.assistant-local/bw-session && chmod 600 ~/.assistant-local/bw-session
#
# Then:  scripts/import_bitwarden_keys.sh
set -euo pipefail

KEYS_DIR="$HOME/.assistant-local"
SESSION_FILE="$KEYS_DIR/bw-session"
KEYS_OUT="$KEYS_DIR/keys.env"
ITEMS_PY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/bitwarden_items.py"

if [[ ! -f "$SESSION_FILE" ]]; then
  echo "[bw-import] unlock first: bw unlock --raw > $SESSION_FILE && chmod 600 $SESSION_FILE" >&2
  exit 1
fi

SESSION="$(cat "$SESSION_FILE")"

# Resolve the env-var -> vault item id mapping without importing the module
# (keeps this script free of Python import side effects).
mapfile -t PAIRS < <(python3 - "$ITEMS_PY" <<'EOF'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("bitwarden_items", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
for k, v in mod.API_KEY_ITEM_IDS.items():
    print(f"{k}\t{v}")
EOF
)

mkdir -p "$KEYS_DIR"
: > "$KEYS_OUT"
chmod 600 "$KEYS_OUT"

wrote=0
for pair in "${PAIRS[@]}"; do
  env_name="${pair%%$'\t'*}"
  item_id="${pair##*$'\t'}"
    # Keys live in custom field `api_key`, or `login.password`, or `notes` —
    # Bitwarden item layouts vary; try all three without printing the value.
    value="$(bw get item "$item_id" --session "$SESSION" 2>/dev/null \
      | python3 -c 'import json,sys; item=json.load(sys.stdin); fs=item.get("fields") or []; val=next((f["value"] for f in fs if f.get("name")=="api_key" and f.get("value")), None); val=val or (item.get("login") or {}).get("password"); val=val or item.get("notes"); print(val or "")')"
  if [[ -n "$value" ]]; then
    printf '%s=%s\n' "$env_name" "$value" >> "$KEYS_OUT"
    wrote=$((wrote + 1))
  else
    echo "[bw-import] skip $env_name (vault item $item_id has no api_key field)" >&2
  fi
done

echo "[bw-import] wrote $wrote provider keys to $KEYS_OUT" >&2

# Restarts are handled by the caller — or run hub restart after this script.
