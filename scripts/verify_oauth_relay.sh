#!/usr/bin/env bash
# Smoke-check assistant.llmclouds.au as the O1 Google OAuth relay.
# See docs/oauth-relay.md. Does not print the bearer token.
#
# Usage (on a laptop or the VPS):
#   ASSISTANT_BEARER_TOKEN=... ./scripts/verify_oauth_relay.sh
#   RELAY_URL=https://assistant.llmclouds.au ASSISTANT_BEARER_TOKEN=... ./scripts/verify_oauth_relay.sh
#
# Exit 0 if health + oauth status (authed) succeed. Start-URL / unauth checks
# are reported but a missing Google client JSON (503 on /start) is a warning,
# not a hard fail — the process can be up before GCP is wired.
# Live uvicorn/Starlette RedirectResponse is 307 (not 302).

set -euo pipefail

RELAY_URL="${RELAY_URL:-https://assistant.llmclouds.au}"
RELAY_URL="${RELAY_URL%/}"
BODY="$(mktemp)"
trap 'rm -f "$BODY"' EXIT
FAIL=0
WARN=0

if [[ -z "${ASSISTANT_BEARER_TOKEN:-}" ]]; then
  echo "ASSISTANT_BEARER_TOKEN is required (from assistant.env / the phone Keystore)." >&2
  echo "GCP reminder: authorized redirect URI must be ${RELAY_URL}/oauth/google/callback" >&2
  exit 2
fi

check() {
  local name="$1" expect="$2" url="$3"
  shift 3
  local code
  code="$(curl -sS -o "$BODY" -w '%{http_code}' -m 15 "$@" "$url" || true)"
  if [[ "$code" == "$expect" ]]; then
    echo "ok  $name  http $code"
  else
    echo "FAIL $name  http $code (expected $expect)  $url" >&2
    FAIL=1
  fi
}

echo "relay: $RELAY_URL"
echo "GCP authorized redirect URI must include: ${RELAY_URL}/oauth/google/callback"
echo "Custom Tab start URL: ${RELAY_URL}/oauth/google/start"
echo "Deep link this backend emits: sableapp://oauth-complete (override GOOGLE_OAUTH_DEEPLINK)"
echo

check "GET /v1/health (bearer)" 200 "${RELAY_URL}/v1/health" \
  -H "Authorization: Bearer ${ASSISTANT_BEARER_TOKEN}"

check "GET /oauth/google/status (bearer)" 200 "${RELAY_URL}/oauth/google/status" \
  -H "Authorization: Bearer ${ASSISTANT_BEARER_TOKEN}"
echo "    body: $(tr -d '\n' <"$BODY")"

check "GET /oauth/google/status (no bearer)" 401 "${RELAY_URL}/oauth/google/status"

START_CODE="$(curl -sS -o /dev/null -w '%{http_code}' -m 15 "${RELAY_URL}/oauth/google/start" || true)"
if [[ "$START_CODE" == "307" || "$START_CODE" == "302" || "$START_CODE" == "303" ]]; then
  echo "ok  GET /oauth/google/start  http $START_CODE (redirect to Google)"
elif [[ "$START_CODE" == "503" ]]; then
  echo "WARN GET /oauth/google/start  http 503 — GOOGLE_CLIENT_SECRET_JSON missing on this host"
  WARN=1
else
  echo "FAIL GET /oauth/google/start  http $START_CODE (expected 302)" >&2
  FAIL=1
fi

if [[ "$FAIL" -ne 0 ]]; then
  exit 1
fi
if [[ "$WARN" -ne 0 ]]; then
  echo "oauth relay checks passed with warnings"
  exit 0
fi
echo "oauth relay checks passed"
