# Phase 01 — chat loop end-to-end (the proof milestone)

**Reads:** `docs/plan.md` §1 (API shape), §1.5 (memory/skills design — build tier-1 memory and the tool registry now even though no real tools exist yet), `docs/CONTRACT.md` (the SSE shape this phase implements). `docs/adr/008-two-tier-memory.md`, `docs/adr/009-tool-registry-and-progressive-disclosure.md`.

**Does:** implement `POST /v1/chat` for real — calls OpenAI with `stream=True`, no real tools registered yet beyond the memory ones, streams `ChatEvent`-shaped SSE frames per `docs/CONTRACT.md` straight through, persists conversation/messages to SQLite. Build `app/tools/registry.py` (the flat list shape) and `app/memory.py` + `app/tools/memory_tools.py` (`user_facts` table, `remember`/`forget`) now, wired into every request's system prompt — cheap to do at the same time as the rest of this phase, expensive to retrofit later.

Note: this repo's half is the backend. The Android side (`assistant-android`, separate repo, likely a different tool building it) needs only `docs/CONTRACT.md` to build its matching client — don't expect that repo to read this phase's actual Python.

**Writes:** `app/routers/chat.py`, `app/openai_client.py`, `app/memory.py`, `app/tools/registry.py`, `app/tools/memory_tools.py`, `app/db.py` schema additions (`conversations`, `messages`, `user_facts`).

**Human check:** send a real chat message from the sideloaded Android app (once that repo has its Phase-1-equivalent done), confirm tokens stream into the UI in real time — not one final blob. Confirm the conversation persists (`sqlite3 app.db "select * from messages;"`).

**When done:** write `REPORT.md` recording the verification result and the OpenAI model actually used.
