# SSE frame contract — the only file the Android repo needs

**Owning source:** `app/sse.py` (backend). If this doc and that file ever disagree, that's a bug — fix them together, same commit. Android's half of this contract lives at `backend-client/.../SseFrameCodec.kt` in the `assistant-android` repo; keep both sides in sync by hand until an automated schema check exists.

## Transport

`POST /v1/chat` (bearer-authed) responds with `Content-Type: text/event-stream`. Standard SSE framing: each event is one or more `data: <json>\n\n` lines. The stream ends with a literal `data: [DONE]\n\n`.

## Request body

```json
{ "conversation_id": "optional-string", "message": "the user's turn" }
```

Omit `conversation_id` to start a new conversation; the first event of the response includes the assigned id.

## Event shapes

Each `data:` line is a JSON object with a `type` field. Six types exist; **anything else must decode to an `unknown` event, never throw** — a forward-compatible client is more valuable than a strict one (this is deliberate, borrowed from a proven pattern — see `docs/adr/009-tool-registry-and-progressive-disclosure.md`'s sibling reasoning on tolerant parsing).

| `type` | Fields | Meaning |
|---|---|---|
| `delta` | `content: string` | Append this text to the current assistant message |
| `tool_call_started` | `id, name, args_json` | The model is calling a tool; render as a pending chip |
| `tool_call_progress` | `id, note?` | Optional intermediate status for a long-running tool |
| `tool_call_finished` | `id, ok: bool, summary?` | Tool call resolved; chip flips to done/failed |
| `message_completed` | `conversation_id, message_id` | The assistant's turn is fully done |
| `error` | `message, retryable: bool` | Something failed mid-stream |

## Ordering guarantees

- A `delta` may arrive before any `tool_call_*` event for the same turn if the model streams text before deciding to call a tool — a client-side reducer must handle text arriving with no preceding "message started" marker (synthesize the message).
- `tool_call_finished` always follows the `tool_call_started` with the same `id`, but other `delta`/`tool_call_*` events may interleave between them (parallel tool calls).
- `message_completed` is always the last non-`[DONE]` event for a turn.

## What's NOT in this contract yet

Tier-1 memory (`remember`/`forget`) and skill discovery (`list_skills`/`use_skill`) are tool calls like any other — they don't change this event shape, they just appear as `tool_call_started` events with those names. No separate wire format for them.
