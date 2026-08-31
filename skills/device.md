---
name: device_control
description: Control device features (notifications + media) through the user's connected Android phone
when_to_use: When the user asks to read notifications, play/pause/skip media, or manage device features
revision: 1
tools: ["read_notifications", "control_media"]
---
# Device Control via the connected phone

The backend has no direct access to the user's phone — messages relay through the
user's Android phone (Assistant app installed, notifications + media permission
granted).

Workflow:
1. **`read_notifications(limit?)`** — reads recent notifications from the user's
   Android phone via the NotificationListenerService. Returns a `request_id`.
2. **`control_media(action)`** — controls media playback on the user's connected
   Android phone. `action` is one of: `play`, `pause`, `next`, `prev`. Returns
   a `request_id`.

Always follow up with `get_device_result(request_id)` to learn the outcome —
for reads this returns the notifications once the phone reports back. If the
result is still "in flight", wait briefly and retry `get_device_result`.

If `read_notifications` reports no registered phone, tell the user to open the
Assistant app on their phone and enable notifications + the "Read notifications"
permission in settings, then retry.

### Backend Infrastructure

- **`app/tools/device_control.py`** — Tool implementation with
  `read_notifications`, `control_media` functions. Uses FCM data push for dispatch,
  tracks in `sms_relay` DB table (action column differentiates device from SMS).
- **`app/routers/device_control.py`** — `POST /v1/device/results` endpoint with
  `DeviceResultRequest`/`DeviceResultNotification` Pydantic models, bearer-token
  protected
- **`assistant.db`** — `sms_relay` table re-used with `action` column values:
  `send_sms`, `read_sms`, `read_notifications`, `control_media`. The
  `sms_relay_messages` table stores notification details for
  `read_notifications` outcomes.

### Key Design Patterns

- **Progressive disclosure** (ADR-009): Device control tools hidden behind
  `use_skill("device_control")` — not in always-visible set
- **FCM data push**: Backend never calls phone directly; relay goes through the
  user's Android device
- **Tracking**: Every relay request gets a `request_id` row in `sms_relay`; outcome
  is recorded via `POST /v1/device/results`
- **404 on unknown request_id**: The results endpoint returns 404 for unrecognized IDs
- **Bearer auth**: All device control endpoints require valid bearer token
- **Consent gating**: `read_notifications` requires BIND_NOTIFICATION_LISTENER_SERVICE
  permission; `control_media` requires MediaSessionManager access. Both are
  gated behind a permission rationale dialog on first use.