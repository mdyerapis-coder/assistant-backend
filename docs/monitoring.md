# Uptime & error alerting

Two 5-minute checks via `scripts/health_alert.sh`, run by `assistant-health-alert.service`/`.timer`:

1. **Liveness** — `GET /v1/health` on `http://127.0.0.1:8090` with the bearer token (the endpoint is auth-gated; a hung uvicorn or full crash fails this).
2. **Error scan** — `journalctl -u assistant.service --since -5min` grepped for `Traceback|CRITICAL|FATAL` (pattern overridable via `JOURNAL_SCAN_PATTERN`).

Failures POST to **ntfy.sh** (Priority: high); recovery posts an all-clear. A state file dedupes — one alert per outage, not one per 5-minute run.

## Configuration

| Var | Source | Purpose |
|---|---|---|
| `ASSISTANT_BEARER_TOKEN` | `/opt/assistant-backend/assistant.env` (already present) | authenticates the health check |
| `NTFY_TOPIC` | `/etc/default/assistant-health-alert` | the ntfy.sh topic — **the topic string is the secret**, pick something unguessable and subscribe privately in the ntfy app |
| `HEALTH_URL` | optional | override the checked URL |
| `NTFY_URL` | optional | override for self-hosted ntfy |

`NTFY_TOPIC` unset = dry-run mode (alerts logged to journal only) — useful for testing the unit before trusting it.

## Deploy (VPS, manual — Mason)

```bash
# 1. Pick an unguessable topic and put it (plus any overrides) in the defaults file
echo 'NTFY_TOPIC=assistant-prod-<random-suffix>' | sudo tee /etc/default/assistant-health-alert
sudo chmod 600 /etc/default/assistant-health-alert

# 2. Install
sudo cp assistant-health-alert.service assistant-health-alert.timer /etc/systemd/system/
sudo cp scripts/health_alert.sh /opt/assistant-backend/scripts/ && sudo chmod +x /opt/assistant-backend/scripts/health_alert.sh
sudo mkdir -p /var/lib/assistant
sudo systemctl daemon-reload && sudo systemctl enable --now assistant-health-alert.timer
systemctl list-timers assistant-health-alert.timer
```

## Testing the alert path

```bash
sudo systemctl stop assistant.service           # take the app down
sudo systemctl start assistant-health-alert.service
sudo journalctl -u assistant-health-alert.service -n 20   # expect "alerted: ..."
# → ntfy push arrives on the phone
sudo systemctl start assistant.service          # next run posts RECOVERED
```

## Known limits (deliberate)

- 5-minute granularity: outages shorter than one interval may self-heal before a check runs. Good enough for a single-user assistant; not a paging SLO.
- ntfy.sh free tier has no delivery guarantee. If alerts ever become load-bearing, self-host ntfy (`NTFY_URL`) or swap the `notify()` body for a different channel — the script isolates it in one function.
- The bearer token is required for the health check by design (`/v1/health` is auth-gated); the token already lives in `assistant.env`, so no new secret surface was added.
