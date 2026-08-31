# Wire contract — the only file the Android repo needs

**Owning sources:** `app/sse.py` (SSE frames), `app/routers/threads.py` + `app/routers/memory.py` + `app/routers/models.py` (REST endpoints, phase 05). If this doc and those files ever disagree, that's a bug — fix them together, same commit. Android's half of this contract lives at `backend-client/.../SseFrameCodec.kt` and `backend-client/.../ThreadsApi.kt` in the `assistant-android` repo; keep both sides in sync by hand until an automated schema check exists.

**Auth (all endpoints, SSE and REST):** `Authorization: Bearer <token>` header. Missing/invalid → `401`.

## Part 1 — SSE chat stream

### Transport

`POST /v1/chat` (bearer-authed) responds with `Content-Type: text/event-stream`. Standard SSE framing: each event is one or more `data: <json>\n\n` lines. The stream ends with a literal `data: [DONE]\n\n`.

### Request body

```json
{ "conversation_id": "optional-string", "message": "the user's turn", "model": "optional-provider-id" }
```

Omit `conversation_id` to start a new conversation; the first event of the response includes the assigned id. Omit `model` to use the backend's active provider; a `model` value is an `id` from `GET /v1/models` (phase 05) — an unknown id silently falls back to the active provider, never an error.

### Event shapes

Each `data:` line is a JSON object with a `type` field, and **every event — not just `message_completed` — also carries `conversation_id`**, which is how a client learns the assigned id when it started the request without one. Six types exist; **anything else must decode to an `unknown` event, never throw** — a forward-compatible client is more valuable than a strict one (this is deliberate, borrowed from a proven pattern — see `docs/adr/009-tool-registry-and-progressive-disclosure.md`'s sibling reasoning on tolerant parsing). Treat any field not listed below the same way: ignore it rather than rejecting the event.

| `type` | Fields (besides `conversation_id`) | Meaning |
|---|---|---|
| `delta` | `content: string` | Append this text to the current assistant message |
| `tool_call_started` | `id, name, args_json` | The model is calling a tool; render as a pending chip |
| `tool_call_progress` | `id, note?` | Optional intermediate status for a long-running tool |
| `tool_call_finished` | `id, ok: bool, summary?` | Tool call resolved; chip flips to done/failed |
| `message_completed` | `message_id` | The assistant's turn is fully done |
| `error` | `message, retryable: bool` | Something failed mid-stream |

### Ordering guarantees

- A `delta` may arrive before any `tool_call_*` event for the same turn if the model streams text before deciding to call a tool — a client-side reducer must handle text arriving with no preceding "message started" marker (synthesize the message).
- `tool_call_finished` always follows the `tool_call_started` with the same `id`, but other `delta`/`tool_call_*` events may interleave between them (parallel tool calls).
- `message_completed` is always the last non-`[DONE]` event for a turn.

### What's NOT in this contract yet

Tier-1 memory (`remember`/`forget`) and skill discovery (`list_skills`/`use_skill`) are tool calls like any other — they don't change this event shape, they just appear as `tool_call_started` events with those names. No separate wire format for them. Phase 05 added **no new SSE frame types** — thread history sync is pull-based REST (below), not pushed through the chat stream.

## Part 2 — REST endpoints (phase 05)

Same tolerant-parsing rule: ignore unknown fields, never reject. All responses are JSON.

### `GET /v1/threads` — conversation list (server is source of truth)

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

Ordered by `last_message_at` descending. `message_count` includes tool-call rows (it's a raw row count, not a bubble count). Conversations with zero messages are not listed. `preview` can be `""` in pathological cases; `title` falls back to `"Untitled"`.

### `GET /v1/threads/{id}/messages` — renderable history

```json
{ "thread_id": "uuid-string",
  "messages": [
    { "id": 123, "role": "user" | "assistant", "content": "text", "created_at": "iso-8601" }
] }
```

Only rows a chat UI would render: `user`/`assistant` roles with non-empty `content`, ordered oldest-first, `id` is the backend's integer row id. Tool-call rows and content-less assistant rows are omitted entirely. Unknown thread id → `404 {"detail": "unknown thread"}`.

### `GET /v1/memory` / `PATCH /v1/memory` — inspect and edit stored facts

```json
// GET
{ "facts": [ { "key": "timezone", "value": "Australia/Sydney", "updated_at": "iso-8601" } ] }
```

```json
// PATCH — upsert values; null value deletes the key
{ "facts": { "timezone": "Australia/Sydney", "stale_fact": null } }
```

PATCH response: `{"facts": [...same shape as GET...], "rejected": [{"key": "...", "reason": "..."}]}`. A write that would exceed the memory cap lands in `rejected` (with a reason) instead of being stored — the rest of the patch still applies.

### `GET /v1/models` — provider catalog (phase 05 contract repair)

```json
{ "default_model_id": "minimax",
  "models": [ { "id": "minimax", "model": "MiniMax-M2", "provider": "minimax", "description": "..." } ] }
```

One entry per provider whose API key is configured on the backend; `id` is what `/v1/chat` accepts as its `model` field. `default_model_id` is what the backend uses when no `model` is sent.
