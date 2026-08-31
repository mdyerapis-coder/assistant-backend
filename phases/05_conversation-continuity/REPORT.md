# Phase 05 — conversation continuity plus memory depth

**Status:** code complete + tested locally (`76 passed`, up from 45 at phase 04). Not yet deployed to the VPS and not yet device-verified — both are the companion Android phase's gate, not blockers for this one.

## What landed

### 1. Server-side thread persistence (already existed) + exposure

`conversations`/`messages` have been persisted server-side since phase 01 — what was missing was any way for a client to read them back. New `app/routers/threads.py`:

- `GET /v1/threads` — threads with derived `title` (first user message, 80-char cap), `preview` (last user/assistant text, 140-char cap), `message_count`, `created_at`/`last_message_at`, ordered most-recent-first, zero-message conversations excluded. No schema change needed: everything is derived from the existing tables with correlated subqueries, so the deployed `assistant.db` needs no migration.
- `GET /v1/threads/{id}/messages` — renderable history only (`user`/`assistant` with non-empty content, ordered, integer ids); tool rows and content-less assistant rows are omitted. 404 on unknown id.

Threads are keyed to the bearer token implicitly: this backend is single-token (one human, one phone) — every conversation in the DB belongs to that principal, so a reinstall or second device using the same token sees the same threads. When multi-user auth ever lands, these two queries grow a `WHERE owner = ?`; until then an owner column would be dead weight.

### 2. Tier-2 memory: auto-extracted durable facts

- New `app/extraction.py` — after every cleanly completed chat turn, the router schedules a fire-and-forget background task (`extraction.schedule`) that sends the last user/assistant exchange (plus the already-known facts, so the model doesn't restate) to the active provider and asks for `{"facts": {key: value}}`. New/changed facts go through `memory.remember()`, which enforces the existing size cap — cap-rejected facts are logged and skipped, never crash the task. All failures (provider down, unparseable output, markdown-fenced JSON, prose-wrapped JSON) are handled and logged; extraction can never break or delay a chat stream. This lives in its own module rather than `app/memory.py` because memory.py is deliberately framework-free (its docstring's invariant) — extraction owns the model call, memory stays pure storage.
- New `app/routers/memory.py` — `GET /v1/memory` (all facts with timestamps) and `PATCH /v1/memory` (`{"facts": {key: value|null}}`; null deletes, upserts go through `remember()` so the cap applies, rejections returned as `rejected: [{key, reason}]`). The human can now audit/correct everything the model remembered or auto-extracted without chatting.

### 3. Contract repair discovered during this phase: `GET /v1/models`

The Android app (phase 04) has called `GET /v1/models` and sent a `model` field on `/v1/chat` since its model picker landed — but no backend route existed; the picker 404'd live and the field was silently ignored (pydantic drops unknown fields). Fixed in the same phase because it's a contract break, not a new feature:

- `app/routers/models.py` — `GET /v1/models` returning one entry per provider whose key is configured (`id` = provider name) plus `default_model_id`.
- `app/openai_client.py` — `resolve(model_id)` maps the request's `model` to a cached per-provider `AsyncOpenAI` client; unknown/missing falls back to the active provider rather than erroring (a rotated-out key shouldn't hard-fail the phone's saved selection). `ACTIVE_PROVIDER_NAME` exposed for the catalog.
- `app/routers/chat.py` — `ChatRequest.model` accepted and threaded into `_run_turn`.

### 4. Contract

`docs/CONTRACT.md` rewritten: Part 1 (SSE, unchanged shapes, explicit "no new frame types in phase 05 — sync is pull-based REST") + Part 2 (all REST endpoints above with exact shapes and the same tolerant-parsing rule). Re-copied by hand into `assistant-android/docs/CONTRACT.md` per the delegation-boundary rule — verify the header there when the companion lands.

## Deviations from the phase CONTEXT

- "Writes app/sse.py (thread/sync frames)" — **not done, deliberately**: REST pull covers every verification in either phase's CONTEXT (thread list on launch, resume on tap, fresh-install rehydrate) without a new frame type that both sides must version. Sync events become worth it when push-synced multi-device updates become a real requirement.
- "Writes app/db.py (thread persistence)" — no change required; phase 01's schema already persisted everything.

## Verification

- Local: `.venv/bin/pytest -q` → **76 passed** (31 new: threads 7, memory API 6, extraction 11, models 6, +1 conftest-affecting chat behavior unchanged). New `tests/conftest.py` stubs the background extraction schedule for chat tests so no hidden task races TestClient teardown; extraction tests exercise the real functions directly.
- Smoke (local uvicorn, throwaway token + tmp DB, 2026-08-31): `GET /v1/threads` → `{"threads":[]}`; `GET /v1/memory` → `{"facts":[]}`; `PATCH /v1/memory {"facts":{"timezone":"Australia/Sydney"}}` → stored and echoed with `updated_at`; `GET /v1/models` → `default_model_id: "minimax"` + the one locally-keyed provider (`opencode-zen`); unauthed `GET /v1/threads` → 401. NOTE: on this laptop only opencode-zen's key is set, so `default_model_id` (minimax) isn't in the local catalog — on the VPS the active provider's key is present, which is what makes it the active provider. Cosmetic dev-env quirk, documented here rather than papered over with fallback logic.

## Not done yet (live checks; need the VPS + a phone)

1. Deploy: git pull on the VPS + `systemctl --user restart assistant`, then `curl -H "Authorization: Bearer …" https://assistant.llmclouds.au/v1/threads` returns real threads.
2. Auto-extraction live proof: tell the assistant "my dog is called Rover" → `GET /v1/memory` shows `dog_name`; `PATCH` it and confirm the next turn's behavior reflects the edit.
3. Second device / reinstall with same token → thread list repopulates (this is assistant-android `phases/08`'s gate; its CONTEXT requires this phase landed + contract re-copied — done in the same session as this commit).
4. Model picker live proof: `GET /v1/models` from the phone returns the catalog and a selected provider routes chats (watch service logs for the per-provider base_url).
