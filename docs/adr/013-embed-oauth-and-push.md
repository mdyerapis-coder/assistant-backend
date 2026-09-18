# ADR-013: embed path — OAuth relay and local push (ADR-012 step 3)

**Status:** accepted (paper), 2026-09-18  
**Supersedes / amends:** ADR-012 (redesign edges only); does not overturn ADR-007 for the cloud path.  
**Related:** ADR-006 (reminder creation vs delivery), ADR-007 (Google OAuth confidential client), CONTRACT.md (FCM SMS relay + automations scheduler), [docs/oauth-relay.md](../oauth-relay.md) (operator surface for `assistant.llmclouds.au`).

## Decision

For the APK-embedded backend path (ADR-012 Option A or later B), lock:

1. **O1 — Thin Google OAuth relay.** The confidential `client_secret` stays off-device on a small always-on service (initially the existing `assistant.llmclouds.au` host, possibly stripped later to OAuth + token vault only). Phone Custom Tab flow remains backend-anchored: start at the relay’s `/oauth/google/start`, callback on that host, deep-link return via `sableapp://oauth-complete` (live `assistant-android` scheme; historical backend alias was `assistantapp://oauth-complete`). Embedded in-process backend does **not** ship the client secret. Calendar/Gmail either use tokens obtained via the relay or call Google through the relay. ADR-007 remains the law for the secret; embed does not switch to phone-side PKCE. Operator checklist: [docs/oauth-relay.md](../oauth-relay.md).

2. **P1 — WorkManager + local notifications.** Reminder and automation *delivery* on the embed path is owned by Android scheduling (WorkManager) and local notifications. Server-initiated FCM to “self” is out of scope for pure embed. ADR-006’s split still holds: creation stays tool + SQLite; delivery is a separate shippable concern, now Android-native instead of Firebase when embedded.

3. **P2 — In-process device tools.** When the backend process is co-located on the phone, SMS / notification-read / media-control tools call Android APIs directly. The CONTRACT.md FCM data-message hop (`action: send_sms` / `read_sms` → `POST /v1/sms/results`) is for the remote-backend topology only and is not recreated as a loopback FCM dance.

## Consequences

- Pure embed is **not** zero-cloud if Google tools are enabled; OAuth (and possibly token refresh) still need the relay host.
- Multi-device FCM fan-out from a phone-local backend is dropped unless a hybrid cloud brain remains.
- `firebase-admin` stays droppable on the Android-flavored Python set (ADR-012); FCM client SDK on Android is optional and only needed if hybrid cloud→phone push remains.
- systemd health-alert / backup units stay non-goals for embed v1 (revisit with WorkManager backups later).
- Chaquopy wheel spike (ADR-012 step 1) remains a separate gate; these paper decisions do not wait on it.

## Rejected for this path (for now)

- **O2 — Phone PKCE:** overturns ADR-007; only revisit if zero-cloud Google becomes a hard product requirement.
- **O3 — Google cloud-only / embed without Calendar-Gmail:** cheaper spike posture; Declined in favour of O1 so embed keeps Google tools via relay.
- Keeping server-style FCM self-push for reminders on-device.

## Follow-ups (implementation, not this ADR)

1. ~~Sketch relay surface: which endpoints stay on cloud (`/oauth/google/*`, token refresh, optional proxied Calendar/Gmail) vs what the embedded process owns.~~ **Done** — [docs/oauth-relay.md](../oauth-relay.md). Running service stays full chat backend until a Google proxy exists; do not strip `/v1/chat` as a silent cutover.
2. Android: WorkManager mapping for `reminders.due_at` and automations cron. (Option C P1 shipped in `assistant-android`.)
3. Android: replace SMS relay client with in-process implementations behind the same tool names when `embed` flavor is active. (Option C P2 shipped in `assistant-android`.)
4. Retry Chaquopy wheel-availability spike when cloud agents are healthy.
