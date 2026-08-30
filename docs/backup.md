# Database backups

Off-box SQLite backups via `scripts/backup_db.sh` + `assistant-backup.service`/`.timer`. The snapshot is WAL-safe (`sqlite3 .backup`), integrity-checked (`PRAGMA integrity_check`) before it counts as good, and pushed off-box so a dead VPS still leaves the data intact.

## Schedule

`assistant-backup.timer` runs the script daily at 03:00 (+ up to 10 min jitter), `Persistent=true` so a missed run (server off) fires at next boot.

## Configuration

Env vars come from `/opt/assistant-backend/assistant.env` (already has `ASSISTANT_DB_PATH`) plus `/etc/default/assistant-backup` for backup-specific settings:

| Var | Purpose |
|---|---|
| `ASSISTANT_DB_PATH` | live SQLite DB (default `/opt/assistant-backend/assistant.db`) |
| `BACKUP_DIR` | local staging dir (default `/var/backups/assistant`) |
| `BACKUP_RETENTION_DAYS` | local retention (default 7) |
| `RESTIC_REPOSITORY` + `RESTIC_PASSWORD` | restic off-box target (S3/B2/local path) — **or** |
| `BACKUP_RSYNC_DEST` | rsync off-box target (`user@host:/srv/backups/assistant/`) |
| `BACKUP_RSYNC_SSH_KEY` | optional SSH key for the rsync push |

Set **at least one** off-box target. Without one the script still makes a local backup — which does not survive the VPS — and logs a warning.

Secrets (restic password, SSH keys) live in `/etc/default/assistant-backup`, root-owned `chmod 600`. Never in the repo.

## Deploy (VPS, manual — Mason)

```bash
sudo cp assistant-backup.service assistant-backup.timer /etc/systemd/system/
sudo cp scripts/backup_db.sh /opt/assistant-backend/scripts/ && sudo chmod +x /opt/assistant-backend/scripts/backup_db.sh
sudo systemctl daemon-reload && sudo systemctl enable --now assistant-backup.timer
systemctl list-timers assistant-backup.timer   # confirm next run
```

## Restore procedure

```bash
# 1. Stop the app so the live DB isn't written during restore
sudo systemctl stop assistant.service

# 2. Pull the backup file down from the off-box target, then:
sqlite3 /opt/assistant-backend/assistant.db "PRAGMA integrity_check;"   # sanity on the current file first
cp /opt/assistant-backend/assistant.db /opt/assistant-backend/assistant.db.pre-restore
cp /path/to/assistant-YYYYMMDD-HHMMSS.db /opt/assistant-backend/assistant.db
chown --reference=/opt/assistant-backend/assistant.db.pre-restore /opt/assistant-backend/assistant.db

# 3. Restart and verify
sudo systemctl start assistant.service
curl -s -H "Authorization: Bearer $ASSISTANT_BEARER_TOKEN" https://assistant.llmclouds.au/v1/health
```

Note: the snapshot already includes the WAL state at backup time, so no `-wal`/`-shm` files are needed with the restore.

## Exit codes (what the journal means)

`0` ok · `1` sqlite3 missing · `2` DB not found · `3` snapshot/integrity failed · `4` off-box push failed (local backup kept).
