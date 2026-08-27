#!/usr/bin/env bash
# Pull secrets from Mason's Bitwarden *personal* vault, write them into
# assistant.env, restart the service only if something actually changed.
# See docs/adr/011-bitwarden-secret-sync.md for the full design.
#
# The master password is NOT a plaintext env var — it's a systemd encrypted
# credential (see assistant-secrets-sync.service's LoadCredentialEncrypted=),
# decrypted by systemd into $CREDENTIALS_DIRECTORY only for this unit's
# runtime, never sitting on disk as plaintext. Set it up once with:
#   echo -n 'your master password' | systemd-creds encrypt - /root/.bw-master-password.cred
#
# BW_CLIENTID/BW_CLIENTSECRET (the API key pair — alone these can log the
# CLI in but cannot decrypt anything without also unlocking) still live in
# ~/.bw-sync.env (0600) — meaningfully less sensitive than the master
# password, so plaintext-on-disk for those two is an acceptable tradeoff.
#
# Item IDs for what to sync live in bitwarden_items.py, next to this script
# — that's the single place to add a new credential.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="/opt/assistant-backend/assistant.env"
BW_ENV_FILE="${HOME}/.bw-sync.env"

if [[ ! -f "$BW_ENV_FILE" ]]; then
  echo "[secrets-sync] $BW_ENV_FILE not found — nothing to do (one-time setup incomplete)" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$BW_ENV_FILE"
export BW_CLIENTID BW_CLIENTSECRET

if [[ -z "${CREDENTIALS_DIRECTORY:-}" ]] || [[ ! -f "${CREDENTIALS_DIRECTORY}/BW_MASTER_PASSWORD" ]]; then
  echo "[secrets-sync] no BW_MASTER_PASSWORD credential — run via systemd" \
       "(assistant-secrets-sync.service), not directly, or pass" \
       "--passwordfile yourself for a manual test run" >&2
  exit 1
fi

SESSION="$(bw unlock --passwordfile "${CREDENTIALS_DIRECTORY}/BW_MASTER_PASSWORD" --raw)"
export BW_SESSION="$SESSION"

bw sync --session "$SESSION" >/dev/null

python3 "$SCRIPT_DIR/sync_secrets_from_bitwarden.py" --session "$SESSION" --env-file "$ENV_FILE"
