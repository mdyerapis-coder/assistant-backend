# Phase 01 — REPORT

**Date:** 2026-08-27
**Status:** backend implementation done and live-verified; the phase's actual human-check (send a message from the sideloaded Android app) is still pending because `assistant-android` doesn't exist yet.

## What actually happened

- Built `POST /v1/chat` (`app/routers/chat.py`), `app/db.py` (SQLite schema: `conversations`, `messages`, `user_facts`), `app/sse.py`, `app/openai_client.py`, `app/memory.py` (tier-1 `user_facts` + tier-2 text search), `app/tools/registry.py` + `app/tools/memory_tools.py` (`remember`/`forget`/`search_past_conversations`) — everything `phases/01_chat-loop/CONTEXT.md` asked for.
- 22 tests (mocked OpenAI stream, covering a plain-text turn, a full tool-call round trip, memory cap/consolidation behavior, and tool-schema shape). Passing locally and on assistant-vps.
- **`docs/CONTRACT.md` updated**: every SSE event now carries `conversation_id` (not just `message_completed`) — the original draft was ambiguous about how a client learns the assigned id, fixed to match the real implementation since that doc is what `assistant-android` will build against.

## Backend swapped from Cline to MiniMax mid-phase

Cline's account had a negative credit balance ($-0.31) — confirmed by hitting `api.cline.bot` directly, bypassing our app entirely: every model tried returned `insufficient_credits` or `model not found`. Not a bug in this repo. Mason chose to switch the active backend to MiniMax rather than top up Cline right now.

Two things had to be fixed to make MiniMax actually work, both found by testing live rather than trusting the phase-00 registry entry:
- `app/providers.py`'s MiniMax `base_url` was a guess (`api.minimax.chat`, flagged TODO in phase 00) — wrong, gave `401 invalid api key`. Corrected to `https://api.minimax.io/v1`, verified via direct curl before wiring it into the app.
- MiniMax's OpenAI-compatible endpoint inlines `<think>...</think>` reasoning directly into `content` by default — would have leaked raw chain-of-thought into the SSE delta stream, which `docs/CONTRACT.md` has no event type for. Fixed with `extra_body={"thinking": {"type": "disabled"}}` in `app/openai_client.py`, confirmed clean afterward.

`app/openai_client.py` now points at whichever provider `_ACTIVE_PROVIDER_NAME` names (currently `"minimax"`) rather than being hardcoded to Cline's env vars — swapping backends later is a one-line change, not a rewire. Real per-request/per-user provider selection is still deferred (unchanged from the phase-00 design note).

## Live verification (human check, partial)

Ran directly against `https://assistant.llmclouds.au/v1/chat` with the real bearer token and the real MiniMax model — not mocked:

1. Plain text turn: `"Reply with exactly the single word: pong"` → streamed `delta` "pong" → `message_completed` → `[DONE]`.
2. Tool-call round trip: `"remember that my favourite colour is teal"` → `delta`s, `tool_call_started` (`remember`, correct `args_json`), `tool_call_finished` (`ok: true`), more `delta`s, `message_completed`.
3. Cross-conversation tier-1 memory: **new** conversation (no `conversation_id`), asked `"What is my favourite colour?"` → correctly answered "teal" — proves `user_facts` is actually injected into the system prompt on every request, not just working within one thread.
4. Verified all of the above by reading `assistant.db` directly (`python3 -c "import sqlite3; ..."` — no `sqlite3` CLI installed on the VPS): `messages` rows correct for user/assistant/tool roles including `tool_call_id`/`name`, `user_facts` had exactly the one row expected.
5. Test data wiped (`rm assistant.db*`, service restarted) before handing back — VPS DB is empty/fresh now.

**Not yet done:** the phase's literal human-check (a real Android client streaming this into a UI) — blocked on `assistant-android` not existing yet, unrelated to backend readiness. Treat that as still open when that repo starts.

## Deviations from the plan, and why

1. Active model backend is MiniMax, not Cline — Cline's account needs topping up before it can be the default again (see above). Not a plan change, an environment/billing fact.
2. Model-provider selection is a single hardcoded `_ACTIVE_PROVIDER_NAME` constant, not yet wired to real per-request selection — matches the original phase-00 note that this was deferred, not a new deviation.

## Not done yet (tracked, not forgotten)

- `assistant-android` doesn't exist — Phase 01's literal human-check needs it.
- Cline credits still negative — switch `_ACTIVE_PROVIDER_NAME` back (or add real provider-selection) once topped up, if desired.
- `tool_call_progress` (optional per contract) isn't emitted anywhere — fine, no v1 tool is long-running enough to need it yet.
