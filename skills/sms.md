---
name: sms
description: Send and read SMS messages through the user's connected phone
when_to_use: When the user asks to send a text message, check their texts, or read an SMS
tools: ["send_sms", "read_sms", "get_sms_result"]
revision: 1
---
# SMS via the connected phone

The backend has no SMS gateway — messages relay through the user's Android
phone (Assistant app installed, notifications enabled).

Workflow:
1. To send: call `send_sms` with the recipient number (international format,
   e.g. +61412345678) and the message body. It returns a `request_id`.
2. To read: call `read_sms` (optional `phone` filter and `limit`). It returns a
   `request_id`.
3. Always follow up with `get_sms_result(request_id)` to learn the outcome —
   for reads this returns the messages once the phone reports back. If the
   result is still "in flight", wait briefly and retry `get_sms_result`.

If `send_sms` reports no registered phone, tell the user to open the Assistant
app on their phone and enable notifications, then retry.
