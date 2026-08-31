# Phase 05 — conversation continuity plus memory depth

**Status:** deployed to the VPS and live-verified (`77 passed` locally; all new endpoints 200 against https://assistant.llmclouds.au with real data, 2026-08-31). Remaining: on-phone verification, which is the companion Android phase's gate.

## What landed

### 1. Server-side thread persistence (already existed) + exposure

`conversations`/`messages` have been persisted server-side since phase 01 — what was missing was any way for a client to read them back. New `app/routers/threads.py`:

- `GET /v1/threads` — threads with derived `title` (first user message, 80-char cap), `preview` (last user/assistant text, 140-char cap), `message_count`, `created_at`/`last_message_at`, ordered most-recent-first, zero-message conversations excluded. No schema change needed: everything is derived from the existing tables with correlated subqueries, so the deployed `assistant.db` needs no migration.
- `GET /v1/threads/{id}/messages` — renderable history only (`user`/`assistant` with non-empty content, ordered, integer ids); tool rows and content-less assistant rows are omitted. 404 on unknown id.

Threads are keyed to the bearer token implicitly: this backend is single-token (one human, one phone) — every conversation in the DB belongs to that principal, so a reinstall or second device using the same token sees the same threads. When multi-user auth ever lands, these two queries grow a `WHERE owner = ?`; until then an owner column would be dead weight.

### 2. Tier-2 memory: auto-extracted durable facts

- New `app/extraction.py` — after every cleanly completed chat turn, the router schedules a fire-and-forget background task (`extraction.schedule`) that sends the last user/assistant exchange (plus the already-known facts, so the model doesn't restate) to the active provider and asks for `{"facts": {key: value}}`. New/changed facts go through `memory.remember()`, which enforces the existing size cap — cap-rejected facts are logged and skipped, never crash the task. All failures (provider down, unparseable output, markdown-fenced JSON, prose-wrapped JSON) are handled and logged; extraction can never break or delay a chat stream. This lives in its own module rather than `app/memory.py` because memory.py is deliberately framework-free (its docstring's invariant) — extraction owns the model call, memory stays pure storage.
- New `app/routers/memory.py` — `GET /v1/memory` (all facts with timestamps) and `PATCH /v1/memory` (`{"facts": {key: value|null}}`; null deletes, upserts go through `remember()` so the cap applies, rejections returned as `rejected: [{key, reason}]`). The human can now audit/correct everything the model remembered or auto-extracted without chatting.

### 3. Merge discovery: the deployed VPS tree was ahead of git

While preparing the deploy, `/opt/assistant-backend` turned out to carry a full phase's worth of running-but-uncommitted work: skills platform (`app/skills.py`, `skills/`, `skills_tools`), MCP client wiring (`mcp_client.py`, `mcp_servers.json`), action patterns (`patterns.py`), plugin loader (`plugins/`, `plugins.py`), `ModelRuntime` per-request provider selection with `GET /v1/models` and `ChatRequest.model` (422 on unknown id — not the silent fallback my first pass assumed), orjson SSE encoding, and new deps (orjson/pyyaml/mcp). Commit `5f9e63c` brings that tree into git wholesale and re-applies this phase's work on top of the VPS versions: threads/memory/extraction kept (the VPS had none of them), `chat.py` gains the extraction schedule, `main.py` mounts the two new routers, and the first-pass `/v1/models` router + `openai_client.resolve` from `9e5f66c` were **dropped in favor of the deployed `ModelRuntime` implementation** (same wire shape the Android app already targets, stricter 422 semantics) — one implementation, not two.

### 4. Contract

`docs/CONTRACT.md` = the VPS text (model catalog with 422 semantics) + new "Thread history" and "Memory inspection" sections, same tolerant-parsing rule, explicit "no new SSE frame types in phase 05". Re-copied by hand into `assistant-android/docs/CONTRACT.md` (2026-08-31) per the delegation-boundary rule.

## Deviations from the phase CONTEXT

- "Writes app/sse.py (thread/sync frames)" — **not done, deliberately**: REST pull covers every verification in either phase's CONTEXT (thread list on launch, resume on tap, fresh-install rehydrate) without a new frame type that both sides must version. Sync events become worth it when push-synced multi-device updates become a real requirement.
- "Writes app/db.py (thread persistence)" — no change required; phase 01's schema already persisted everything.

## Verification

- Local, merged tree: `.venv/bin/pytest -q` → **77 passed** (31 new tests: threads 7, memory API 6, extraction 11, models 7 — the latter rewritten against `ModelRuntime`/`selectable_providers`/422; plus `tests/conftest.py` stubbing the background extraction schedule so no hidden task races TestClient teardown).
- Local uvicorn smoke (throwaway token + tmp DB, 2026-08-31): threads/memory GET/PATCH round-trip, 401 unauthed — all as documented.
- **Live on the VPS (deployed 2026-08-31, service restarted, `health:200`)**: `GET /v1/threads` → real threads with derived titles ("Say hello" → "Hello! 👋 …" preview); `GET /v1/threads/{id}/messages` → real renderable history (integer ids, oldest-first); `GET /v1/memory` → real facts (e.g. `cat_name: Mochi`); PATCH set + null-delete round-trip verified and cleaned up; `GET /v1/models` → `default_model_id: minimax` + live catalog; public URL `https://assistant.llmclouds.au/v1/threads` → 200.

## Not done yet (phone-side checks; assistant-android phase 08)

1. On-device: sessions screen lists server threads; tap resumes with server messages; fresh install + same token rehydrates.
2. Auto-extraction live proof: tell the assistant "my dog is called Rover" via the phone → `GET /v1/memory` shows `dog_name` within a turn; `PATCH` edit reflects in the next turn.
3. VPS git hygiene: the deploy dir is also root's home and carries home-dir noise (dotfiles, `Android/`, `Work/`, …). The repo-sync commit intentionally excludes all of that; a future cleanup should move the deployment to a dedicated non-home directory.
