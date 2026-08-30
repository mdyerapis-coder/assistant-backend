#!/usr/bin/env bash
# Uptime + error alerting for assistant.service — see docs/monitoring.md.
#
# Runs every 5 min (assistant-health-alert.timer). Two checks:
#   1. GET /v1/health on the local uvicorn (127.0.0.1:8090, bearer-gated).
#   2. Scan `journalctl -u assistant.service --since -5min` for Python
#      tracebacks.
# On any failure, POSTs a notification to https://ntfy.sh/$NTFY_TOPIC.
#
# Required env vars:
#   ASSISTANT_BEARER_TOKEN — the API token /v1/health is gated behind
#                            (same value the Android app uses; already set in
#                            /opt/assistant-backend/assistant.env)
#   NTFY_TOPIC             — ntfy.sh topic name; alerts publish here
#                            (set in /etc/default/assistant-health-alert on
#                            the VPS; the topic string is the secret — pick
#                            something unguessable)
# Optional env vars:
#   HEALTH_URL             — default http://127.0.0.1:8090/v1/health
#   NTFY_URL               — default https://ntfy.sh (override for self-host)
#   ALERT_STATE_FILE       — dedupe state; default /var/lib/assistant/health-alert.state
#   JOURNAL_SCAN_PATTERN   — default 'Traceback|CRITICAL|FATAL'
#
# Exit codes: 0 ok (or repeat-failure already alerted), 1 new alert fired,
#             2 configuration error (missing env var).
#
# Dedupe: while failures persist, only the first run posts to ntfy (state
# file records "alerted"); recovery posts a short all-clear and clears the
# state. Prevents a page every 5 minutes during an outage.

set -uo pipefail

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8090/v1/health}"
NTFY_URL="${NTFY_URL:-https://ntfy.sh}"
NTFY_TOPIC="${NTFY_TOPIC:-}"
STATE_FILE="${ALERT_STATE_FILE:-/var/lib/assistant/health-alert.state}"
JOURNAL_SCAN_PATTERN="${JOURNAL_SCAN_PATTERN:-Traceback|CRITICAL|FATAL}"
HOSTNAME_TAG="$(hostname 2>/dev/null || echo unknown-host)"

log() { echo "[health-alert] $*" >&2; }

# notify TITLE BODY PRIORITY — POST to ntfy; failure to notify is logged,
# never fatal (we don't want alerting outages to crash the timer unit).
notify() {
  local title="$1" body="$2" prio="$3"
  if [[ -z "$NTFY_TOPIC" ]]; then
    log "NTFY_TOPIC not set — would notify: [$prio] $title: $body"
    return 0
  fi
  curl -fsS -m 10 \
    -H "Title: $title" \
    -H "Priority: $prio" \
    -H "Tags: warning" \
    -d "$body" \
    "$NTFY_URL/$NTFY_TOPIC" >/dev/null \
    || log "WARNING: ntfy POST failed (is the topic reachable?)"
}

# set_alerted "description" — first time a given failure is seen: notify and
# remember. Returns 0 if a NEW alert fired (caller exits 1), 1 if already
# alerted (caller exits 0).
set_alerted() {
  local desc="$1" prev
  if [[ -f "$STATE_FILE" ]]; then
    prev="$(cat "$STATE_FILE" 2>/dev/null || true)"
    if [[ "$prev" == "$desc" ]]; then
      log "still failing (already alerted): $desc"
      return 1
    fi
    # failure signature changed — re-alert with the new signature
    mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null || true
    printf '%s' "$desc" > "$STATE_FILE" 2>/dev/null || true
    notify "assistant: NEW failure on $HOSTNAME_TAG" "$desc" "high"
    log "failure changed, re-alerted: $desc"
    return 0
  fi
  mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null || true
  printf '%s' "$desc" > "$STATE_FILE" 2>/dev/null || true
  notify "assistant: DOWN on $HOSTNAME_TAG" "$desc" "high"
  log "alerted: $desc"
  return 0
}

# clear_alerted "recovery note" — all-clear if we had an alert out.
clear_alerted() {
  if [[ -f "$STATE_FILE" ]]; then
    local prev
    prev="$(cat "$STATE_FILE" 2>/dev/null || true)"
    notify "assistant: RECOVERED on $HOSTNAME_TAG" \
      "previous alert: ${prev:-unknown}. $1" "default"
    rm -f "$STATE_FILE" 2>/dev/null || true
    log "recovered: $1"
  fi
}

# --- config check ---
if [[ -z "$NTFY_TOPIC" ]]; then
  log "NTFY_TOPIC not set — running in dry-run (alerts logged, not sent)"
fi
if [[ -z "${ASSISTANT_BEARER_TOKEN:-}" ]]; then
  log "ASSISTANT_BEARER_TOKEN not set — /v1/health is bearer-gated; check 1 will fail"
  exit 2
fi

FAILED_DESC=""

# --- check 1: local health endpoint (bearer-gated) ---
HTTP_CODE="$(curl -fsS -m 10 -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $ASSISTANT_BEARER_TOKEN" \
  "$HEALTH_URL" 2>/dev/null)" || HTTP_CODE="000"

if [[ "$HTTP_CODE" != "200" ]]; then
  FAILED_DESC="/v1/health check failed: url=$HEALTH_URL http_code=$HTTP_CODE (000 = connection refused/timeout). Check assistant.service: systemctl status assistant.service"
fi

# --- check 2: tracebacks in the last 5 min of journal ---
JOURNAL_OUTPUT=""
if command -v journalctl >/dev/null 2>&1; then
  # Service is optional context for the scan; missing units or read-denied
  # journals produce stderr + empty output, not a failure.
  JOURNAL_OUTPUT="$(journalctl -u assistant.service --since -5min --no-pager -o cat 2>/dev/null || true)"
fi
if [[ -n "$JOURNAL_OUTPUT" ]]; then
  # -c: include context (a few lines) so the alert is actionable. Exclude
  # our own log tag to avoid matching this script's own mentions of the word
  # Traceback in log output.
  TRACEBACK_HITS="$(printf '%s\n' "$JOURNAL_OUTPUT" \
    | grep -E -m 3 "$JOURNAL_SCAN_PATTERN" || true)"
  if [[ -n "$TRACEBACK_HITS" ]]; then
    SNIPPET="$(printf '%s\n' "$TRACEBACK_HITS" | head -c 500)"
    JOURNAL_URL="$(systemctl show -p FragmentPath --value assistant.service 2>/dev/null || true)"
    FAILED_DESC="${FAILED_DESC:+$FAILED_DESC }journal errors in last 5min: ${SNIPPET}${JOURNAL_URL:+ (unit: $JOURNAL_URL)}"
  fi
fi

# --- alert / recover ---
if [[ -n "$FAILED_DESC" ]]; then
  if set_alerted "$FAILED_DESC"; then
    log "check failed: $FAILED_DESC"
    exit 1
  fi
  exit 0
fi

clear_alerted "all checks passing (health endpoint 200, no journal tracebacks)."
exit 0