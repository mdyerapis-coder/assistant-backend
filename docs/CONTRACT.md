# SSE frame contract — the only file the Android repo needs

**Owning source:** `app/sse.py` (backend). If this doc and that file ever disagree, that's a bug — fix them together, same commit. Android's half of this contract lives at `backend-client/.../SseFrameCodec.kt` in the `assistant-android` repo; keep both sides in sync by hand until an automated schema check exists.

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

Tier-1 memory (`remember`/`forget`) and skill discovery (`list_skills`/`use_skill`) are tool calls like any other — they don't change this event shape, they just appear as `tool_call_started` events with those names. No separate wire format for them.
