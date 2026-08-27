# Project contract

**What this is:** a single-user, backend-mediated personal assistant. The phone never talks to OpenAI or Google directly — every tool execution (reminders, calendar, email, memory) needs server-held state (SQLite rows, OAuth refresh tokens, the OpenAI key) that must never live on the phone. See `docs/adr/005-backend-mediated-tools.md`.

**The repeating unit:** a phase (`phases/NN_name/`), not a request or a session. Each phase is built once, verified once, and its `REPORT.md` is the permanent record that it happened. This is software construction, not a content pipeline — "running the pipeline again" means starting the *next* phase, not repeating the current one.

**Universes** (per ICM's system-map convention, applied here to phases rather than code):
- **live** — phases `00` through whichever has the highest-numbered `REPORT.md`. Build against these.
- **planned** — phases with a `CONTEXT.md` but no `REPORT.md` yet. Don't assume their outputs exist.
- **deferred** — phase `02.5` (reminder delivery) and everything past `03` (SMS, finances) are real future work, not ghosts, but explicitly not blocking anything earlier. See `docs/plan.md` §3.

**Source of truth for design questions:** `docs/plan.md`. This file and the phase `CONTEXT.md`s route to it and restate only what's needed to start work — they never fork the design. If a phase contract and `docs/plan.md` disagree, `docs/plan.md` wins and the phase contract is stale (fix it).

**Delegation boundary:** a separate repo, `assistant-android` (not yet created, likely built by a different AI tool — Codex or Cline — with no context on this repo), depends on exactly one thing here: the SSE frame shape in `docs/CONTRACT.md`. Never let that contract drift silently — if `app/sse.py`'s actual output shape changes, `docs/CONTRACT.md` changes in the same commit.
