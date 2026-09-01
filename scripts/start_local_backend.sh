#!/usr/bin/env bash
# Starts the local assistant-backend dev server with Bitwarden-managed
# provider keys sourced from ~/.assistant-local/keys.env (0600).
# Keys never appear in process args — they live only in the child's env.
set -euo pipefail

KEYS_FILE="$HOME/.assistant-local/keys.env"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$KEYS_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$KEYS_FILE"
  set +a
fi

exec "$REPO_DIR/.venv/bin/uvicorn" app.main:app \
  --host 127.0.0.1 --port 8420
