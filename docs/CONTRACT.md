# Wire contract — the only file the Android repo needs

**Owning sources:** `app/sse.py` (SSE frames), `app/routers/chat.py` (chat + `/v1/models`), `app/routers/threads.py` + `app/routers/memory.py` (thread history + memory inspection, phase 05), `app/routers/oauth_google.py` (O1 relay URLs + deep link). If this doc and those files ever disagree, that's a bug — fix them together, same commit. Android's half of this contract lives at `backend-client/.../SseFrameCodec.kt` and `backend-client/.../ThreadsApi.kt` in the `assistant-android` repo; keep both sides in sync by hand until an automated schema check exists. Operator checklist for the VPS: [docs/oauth-relay.md](oauth-relay.md).

## Transport

`POST /v1/chat` (bearer-authed) responds with `Content-Type: text/event-stream`. Standard SSE framing: each event is one or more `data: <json>\n\n` lines. The stream ends with a literal `data: [DONE]\n\n`.

## Request body

```json
{
  "conversation_id": "optional-string",
  "message": "the user's turn",
  "model": "optional-provider-id"
}
```

Omit `conversation_id` to start a new conversation; the first event of the response includes the assigned id.
Omit `model` to use the backend default. Clients must source model ids from
the bearer-authenticated `GET /v1/models` endpoint rather than inventing or
persisting raw provider URLs.

## Model catalog

`GET /v1/models` returns only configured providers whose endpoint and model id
have been verified for chat:

```json
{
  "default_model_id": "minimax",
  "models": [
    {
      "id": "minimax",
      "model": "MiniMax-M3",
      "provider": "minimax",
      "description": "Current general-purpose flagship, multimodal."
    }
  ]
}
```

`default_model_id` is `null` and `models` is empty when no selectable provider
is configured. Passing an unknown, unconfigured, or unverified `model` to
`POST /v1/chat` returns HTTP 422 before the user message is persisted.

## Thread history (phase 05)

Same bearer auth and tolerant-parsing rule (ignore unknown fields) as everywhere else.

### `GET /v1/threads` — conversation list; the server is the source of truth

```json
{ "threads": [
    { "id": "uuid-string",
      "title": "first user message, truncated to 80 chars",
      "preview": "last user/assistant text, truncated to 140 chars",
      "created_at": "iso-8601",
      "last_message_at": "iso-8601",
      "message_count": 7 }
] }
```

Ordered by `last_message_at` descending. `message_count` counts all stored rows (including tool rows), not just renderable bubbles. Conversations with zero messages are not listed. `preview` can be `""` in pathological cases; `title` falls back to `"Untitled"`.

### `GET /v1/threads/{id}/messages` — renderable history

```json
{ "thread_id": "uuid-string",
  "messages": [
    { "id": 123, "role": "user" | "assistant", "content": "text", "created_at": "iso-8601" }
] }
```

Only rows a chat UI renders: `user`/`assistant` roles with non-empty `content`, oldest-first, `id` is the backend's integer row id. Tool rows and content-less assistant rows are omitted. Unknown thread id → `404 {"detail": "unknown thread"}`. Phase 05 added **no new SSE frame types** — history sync is pull-based REST, not pushed through the chat stream.

## Memory inspection (phase 05)

### `GET /v1/memory` / `PATCH /v1/memory`

```json
// GET
{ "facts": [ { "key": "timezone", "value": "Australia/Sydney", "updated_at": "iso-8601" } ] }
```

```json
// PATCH — upsert values; null value deletes the key
{ "facts": { "timezone": "Australia/Sydney", "stale_fact": null } }
```

PATCH response: `{"facts": [...same shape as GET...], "rejected": [{"key": "...", "reason": "..."}]}`. A write that would exceed the memory cap lands in `rejected` (with a reason) instead of being stored — the rest of the patch still applies. The model's `remember`/`forget` tools and the post-turn auto-extractor (phase 05) write through the same store these endpoints read.
## SMS relay (phase 06)

The backend has no SMS gateway — `send_sms`/`read_sms` tool calls are relayed
through the connected Android phone. The backend pushes an FCM data message to
the registered device token:

```
data: { "action": "send_sms", "request_id": "<uuid>", "phone": "+614...", "message": "..." }
data: { "action": "read_sms",  "request_id": "<uuid>", "phone": "?", "limit": "10" }
```

The phone executes via the Android SMS APIs and reports the outcome back to:

```
POST /v1/sms/results            (bearer-authed)
{ "request_id": "<uuid>", "ok": true }
{ "request_id": "<uuid>", "ok": false, "error": "reason" }
{ "request_id": "<uuid>", "ok": true, "messages": [
    { "from_number": "+614...", "message": "...", "received_at": "iso-8601" }
] }
```

Response: `{"ok": true}`; 404 for an unknown `request_id`. A `read_sms` result
with `messages` is stored and returned by the `get_sms_result` tool. The SMS
tools are hidden behind `use_skill("sms")` (progressive disclosure, ADR-009) —
they are NOT in the always-visible tool set, so the phone relay is not
required for normal chat turns.

## Event shapes

Each `data:` line is a JSON object with a `type` field, and **every event — not just `message_completed` — also carries `conversation_id`**, which is how a client learns the assigned id when it started the request without one. Six types exist; **anything else must decode to an `unknown` event, never throw** — a forward-compatible client is more valuable than a strict one (this is deliberate, borrowed from a proven pattern — see `docs/adr/009-tool-registry-and-progressive-disclosure.md`'s sibling reasoning on tolerant parsing). Treat any field not listed below the same way: ignore it rather than rejecting the event.

| `type` | Fields (besides `conversation_id`) | Meaning |
|---|---|---|
| `delta` | `content: string` | Append this text to the current assistant message |
| `tool_call_started` | `id, name, args_json` | The model is calling a tool; render as a pending chip |
| `tool_call_progress` | `id, note?` | Optional intermediate status for a long-running tool |
| `tool_call_finished` | `id, ok: bool, summary?` | Tool call resolved; chip flips to done/failed |
| `message_completed` | `message_id` | The assistant's turn is fully done |
| `error` | `message, retryable: bool` | Something failed mid-stream |

## Ordering guarantees

- A `delta` may arrive before any `tool_call_*` event for the same turn if the model streams text before deciding to call a tool — a client-side reducer must handle text arriving with no preceding "message started" marker (synthesize the message).
- `tool_call_finished` always follows the `tool_call_started` with the same `id`, but other `delta`/`tool_call_*` events may interleave between them (parallel tool calls).
- `message_completed` is always the last non-`[DONE]` event for a turn.

## What's NOT in this contract yet

Tier-1 memory (`remember`/`forget`) and skill discovery (`list_skills`/`use_skill`) are tool calls like any other — they don't change this event shape, they just appear as `tool_call_started` events with those names. No separate wire format for them. Thread history sync is REST (see above), not SSE events — push-synced multi-device updates would be the trigger to add frame types.

## Automations (phase 07)

Natural-language cron automations. Users define recurring jobs using cron expressions.

### `POST /v1/automations` — Create a new automation

Request body:
```json
{
  "name": "Human-readable name",
  "cron": "Standard cron expression (e.g. "0 9 * * *" for 9am daily)",
  "action": "The skill/tool to execute when the cron fires"
}
```

Response: `{"id": "<automation-id>", "name": "...", "cron": "...", "action": "...", "enabled": true, "created_at": "iso-8601"}`

### `GET /v1/automations` — List automations

Optional query: `?enabled=true` (default) to show only enabled automations.

Response: `[{ "id", "name", "cron", "action", "enabled", "created_at" }]`

### `DELETE /v1/automations/{id}` — Delete an automation

Response: `{"deleted": true}`

Automations are hidden behind `use_skill("automations")` (progressive disclosure, ADR-009) — they do not appear in the default tool-schema payload.

### Scheduler firing

The background scheduler (app/scheduler.py) polls every 30s for due automations using `croniter`. When due, it executes the automation's action (via the tool registry) and FCM-pushes the result to all registered device tokens. After firing, the automation is disabled to avoid repeated triggers.

## OAuth relay (O1 / Option C hybrid)

Chat may run on-device. Google stays on this host. Android keeps two independent base URLs:

| Client setting | Default | Used for |
|---|---|---|
| `oauthRelayUrl` | `https://assistant.llmclouds.au` | Custom Tab, OAuth status/disconnect, Calendar/Gmail turns |
| `chatBaseUrl` | cloud FastAPI, or unused on-device | Ordinary `POST /v1/chat` when Cloud Assistant is selected |

Custom Tab start URL: `{oauthRelayUrl}/oauth/google/start` (never a WebView).

Deep link this backend emits after `/oauth/google/callback`: **`sableapp://oauth-complete`**. Live `assistant-android` registers that scheme only. Historical alias `assistantapp://oauth-complete` is not on the current APK; override with env `GOOGLE_OAUTH_DEEPLINK` only for a pre-rename build.

| Method | Path | Auth | Role |
|---|---|---|---|
| GET | `/oauth/google/start` | none | Redirect to Google consent |
| GET | `/oauth/google/callback` | none | Code exchange; then deep-link to the app |
| GET | `/oauth/google/status` | bearer | `{connected, expiry?, scope?, updated_at?}` |
| DELETE | `/oauth/google` | bearer | Drop stored tokens |
| POST | `/v1/chat` | bearer | Option C Google turns reuse this (existing calendar/gmail tools). Do not send `local:` conversation ids or on-device model ids. |
| GET | `/v1/health` | bearer | Token/host liveness |

`client_secret`, `GOOGLE_TOKEN_ENCRYPTION_KEY`, and Google refresh tokens stay on the relay. They are never in the APK. Full operator notes (GCP redirect URI, secrets, strip-later list): [docs/oauth-relay.md](oauth-relay.md).
