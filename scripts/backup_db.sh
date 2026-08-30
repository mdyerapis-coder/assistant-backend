#!/usr/bin/env bash
# SQLite off-box backup — WAL-safe via sqlite3 .backup + restic/rsync push.
# See docs/backup.md for setup, restore, and off-box target configuration.
#
# Required env vars (documented at top per CONTEXT.md §hardening):
#   ASSISTANT_DB_PATH      — live SQLite DB path
#                            default: /opt/assistant-backend/assistant.db
#                            (falls back to ./assistant.db when not on VPS)
#   BACKUP_DIR             — local staging dir for timestamped copies
#                            default: /var/backups/assistant
#
# Off-box target — set ONE of these (at least one required for off-box push;
# without either, script still creates a local timestamped backup and exits 0):
#   RESTIC_REPOSITORY      — restic repo URL (e.g. s3:https://s3.amazonaws.com/bucket/prefix
#                            or b2:bucket:prefix or /mnt/offbox-restic)
#     RESTIC_PASSWORD      — restic repo password (required when RESTIC_REPOSITORY is set)
#     (any other RESTIC_* / AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY etc. are
#      passed through to restic — see `restic help backup` and docs/backup.md)
#   BACKUP_RSYNC_DEST      — rsync destination
#                            e.g. user@backup-host:/srv/backups/assistant/
#                            or /mnt/offbox/assistant/
#     BACKUP_RSYNC_SSH_KEY — optional path to SSH private key for rsync over SSH
#     BACKUP_RSYNC_ARGS    — optional extra rsync args (default: -az)
#
# Optional:
#   BACKUP_RETENTION_DAYS  — local retention in days (default: 7)
#   BACKUP_TIMESTAMP       — override timestamp for testing (default: $(date +%Y%m%d-%H%M%S))
#   BACKUP_KEEP_COMPRESSED — if "1", gzip the staged file (default: 0)
#
# Environment files (systemd loads these via EnvironmentFile=):
#   /opt/assistant-backend/assistant.env   — already has ASSISTANT_DB_PATH on VPS
#   /etc/default/assistant-backup         — local overrides for BACKUP_* / RESTIC_* / NTFY_*
#
# Exit codes: 0 ok, 1 missing sqlite3, 2 DB not found, 3 backup integrity failed,
#             4 off-box push failed (local backup still kept).

set -euo pipefail

# --- config (env overrides defaults) ---
DB_PATH="${ASSISTANT_DB_PATH:-/opt/assistant-backend/assistant.db}"
# fallback for dev workstations where /opt path doesn't exist
if [[ ! -f "$DB_PATH" && -f "./assistant.db" ]]; then
  DB_PATH="./assistant.db"
fi
BACKUP_DIR="${BACKUP_DIR:-/var/backups/assistant}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
TIMESTAMP="${BACKUP_TIMESTAMP:-$(date +%Y%m%d-%H%M%S)}"
KEEP_COMPRESSED="${BACKUP_KEEP_COMPRESSED:-0}"

RESTIC_REPO="${RESTIC_REPOSITORY:-}"
RSYNC_DEST="${BACKUP_RSYNC_DEST:-}"
RSYNC_KEY="${BACKUP_RSYNC_SSH_KEY:-}"
RSYNC_ARGS="${BACKUP_RSYNC_ARGS:--az}"

log() { echo "[backup] $*" >&2; }
journal_log() {
  if command -v systemd-cat >/dev/null 2>&1; then
    echo "[backup] $*" | systemd-cat -t assistant-backup 2>/dev/null || echo "[backup] $*" >&2
  else
    echo "[backup] $*" >&2
    command -v logger >/dev/null 2>&1 && logger -t assistant-backup "$*" || true
  fi
}

# --- preflight ---
if ! command -v sqlite3 >/dev/null 2>&1; then
  log "sqlite3 not found — install sqlite3 (apt install sqlite3)"
  exit 1
fi
if [[ ! -f "$DB_PATH" ]]; then
  log "DB not found at $DB_PATH (set ASSISTANT_DB_PATH)"
  exit 2
fi

mkdir -p "$BACKUP_DIR"
BACKUP_FILE="${BACKUP_DIR}/assistant-${TIMESTAMP}.db"
TMP_FILE="${BACKUP_FILE}.tmp"

# --- WAL-safe snapshot via sqlite3 .backup ---
log "backing up $DB_PATH -> $BACKUP_FILE (WAL-safe .backup)"
# shellcheck disable=SC2016
if ! sqlite3 "$DB_PATH" ".backup '${TMP_FILE}'"; then
  log "sqlite3 .backup failed"
  rm -f "$TMP_FILE"
  exit 3
fi

# --- integrity check on the snapshot (not the live DB) ---
if ! sqlite3 "$TMP_FILE" "PRAGMA integrity_check;" | grep -q "^ok$"; then
  log "integrity_check failed on snapshot"
  sqlite3 "$TMP_FILE" "PRAGMA integrity_check;" >&2 || true
  rm -f "$TMP_FILE"
  exit 3
fi

mv "$TMP_FILE" "$BACKUP_FILE"
log "snapshot ok: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"

if [[ "$KEEP_COMPRESSED" == "1" ]]; then
  gzip -f "$BACKUP_FILE"
  BACKUP_FILE="${BACKUP_FILE}.gz"
  log "compressed: $BACKUP_FILE"
fi

# --- local retention ---
if [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] && [[ "$RETENTION_DAYS" -gt 0 ]]; then
  # shellcheck disable=SC2086
  find "$BACKUP_DIR" -maxdepth 1 -name 'assistant-*.db*' -mtime +"$RETENTION_DAYS" -print -delete 2>/dev/null || true
fi

# --- off-box push ---
PUSH_FAILED=0

if [[ -n "$RESTIC_REPO" ]]; then
  if [[ -z "${RESTIC_PASSWORD:-}" ]]; then
    log "RESTIC_REPOSITORY set but RESTIC_PASSWORD is empty — skipping restic push"
    PUSH_FAILED=1
  elif ! command -v restic >/dev/null 2>&1; then
    log "restic not found — install restic (apt install restic) or unset RESTIC_REPOSITORY to use rsync"
    PUSH_FAILED=1
  else
    log "pushing $BACKUP_FILE to restic:$RESTIC_REPO"
    if restic backup "$BACKUP_FILE" --tag assistant-sqlite --tag "host=$(hostname -f 2>/dev/null || hostname)" 2>&1; then
      log "restic push ok"
    else
      log "restic push failed"
      PUSH_FAILED=1
    fi
  fi
elif [[ -n "$RSYNC_DEST" ]]; then
  if ! command -v rsync >/dev/null 2>&1; then
    log "rsync not found — install rsync"
    PUSH_FAILED=1
  else
    RSYNC_SSH=""
    if [[ -n "$RSYNC_KEY" ]]; then
      RSYNC_SSH="ssh -i ${RSYNC_KEY} -o StrictHostKeyChecking=accept-new"
    fi
    log "pushing $BACKUP_FILE -> $RSYNC_DEST (rsync $RSYNC_ARGS)"
    if [[ -n "$RSYNC_SSH" ]]; then
      if rsync $RSYNC_ARGS -e "$RSYNC_SSH" "$BACKUP_FILE" "$RSYNC_DEST"; then
        log "rsync push ok"
      else
        log "rsync push failed"
        PUSH_FAILED=1
      fi
    else
      # shellcheck disable=SC2086
      if rsync $RSYNC_ARGS "$BACKUP_FILE" "$RSYNC_DEST"; then
        log "rsync push ok"
      else
        log "rsync push failed"
        PUSH_FAILED=1
      fi
    fi
  fi
else
  log "no off-box target configured (set RESTIC_REPOSITORY or BACKUP_RSYNC_DEST) — local backup only"
  log "see docs/backup.md for setup"
fi

journal_log "backup complete: $BACKUP_FILE (off-box push: $([[ $PUSH_FAILED -eq 0 ]] && echo ok || echo failed/skipped))"

if [[ $PUSH_FAILED -ne 0 && ( -n "$RESTIC_REPO" || -n "$RSYNC_DEST" ) ]]; then
  exit 4
fi
exit 0
