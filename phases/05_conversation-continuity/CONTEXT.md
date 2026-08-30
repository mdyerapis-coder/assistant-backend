# Phase 05 — conversation continuity plus memory depth

**Reads:** `docs/plan.md` §1.5 (two-tier memory), `docs/CONTRACT.md`, `phases/01_chat-loop/REPORT.md` (tier-1 `user_facts` + `conversation_id` on every event), `CONTEXT.md` (delegation boundary). Companion: `assistant-android` `phases/08_conversation-continuity`.

**Does:**
1. Server-side thread persistence — full `conversations`/`messages` history keyed to the bearer token (not device storage) so reinstall, new phone, or second device resumes the same threads.
2. Extend `docs/CONTRACT.md` with thread list/sync events and endpoints (`GET /v1/threads`, `GET /v1/threads/:id/messages` or equivalent) — **CRITICAL: any `docs/CONTRACT.md` change must land in the same commit as the `app/sse.py` or router change and be re-copied BY HAND into `assistant-android`'s copy of `docs/CONTRACT.md`, per `CONTEXT.md` delegation-boundary rule.**
3. Tier-2 memory — auto-extracted durable facts fed into the system prompt plus `GET/PATCH /v1/memory` to inspect and edit.

**Writes:** `app/db.py` (thread persistence), `app/routers/threads.py`, `app/routers/memory.py`, `app/memory.py` (tier-2 extraction), `docs/CONTRACT.md` updates, `app/sse.py` (thread/sync frames).

**Human check:** reinstall (or second device) with same bearer token → thread list repopulates; send message on device B → appears on device A after sync. Store a fact ("my dog is called Rover"), confirm it appears via `GET /v1/memory` and is injected into next turn's prompt; `PATCH /v1/memory` edit persists.

**When done:** write `REPORT.md`.
