# PROJECT KNOWLEDGE BASE

**Generated:** 2026-08-28
**Commit:** 83b7378
**Branch:** master

## OVERVIEW
FastAPI backend for a single-user personal-assistant app: OpenAI-Chat-Completions-style
streaming chat with tool-calling (reminders now; calendar/email later), SSE to a native
Android client, SQLite for all state. See `CONTEXT.md`/`CLAUDE.md` for the phase-based
build process — this file covers the code itself.

## STRUCTURE
```
app/
├── main.py            # FastAPI app + lifespan (db connect/disconnect)
├── config.py           # env-var config, no defaults for secrets
├── db.py                # aiosqlite connection + schema, one shared connection
├── auth.py              # single static bearer token, constant-time compare
├── memory.py            # tier-1 (facts) / tier-2 (message search) memory, framework-free
├── openai_client.py      # AsyncOpenAI client pointed at the active provider
├── providers.py           # flat provider list, OpenAI-compatible base_url + key per provider
├── sse.py                  # SSE event encoding — owning source for docs/CONTRACT.md
├── routers/                 # chat.py (the whole chat loop), health.py
└── tools/                    # flat tool registry (see app/tools/AGENTS.md)
docs/
├── plan.md              # full approved design, source of truth for disagreements
├── CONTRACT.md            # SSE wire format — the only file assistant-android should read
└── adr/                     # one decision per file (see docs/adr/AGENTS.md)
phases/                       # build order, CONTEXT.md + REPORT.md per phase (see root CLAUDE.md)
scripts/                       # gen_bearer_token.py, bitwarden secret sync
tests/                          # pytest-asyncio, one file per app module
```

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Add/change a model-callable tool | `app/tools/` | see `app/tools/AGENTS.md` |
| Change the chat loop / SSE stream | `app/routers/chat.py` | keep `docs/CONTRACT.md` in sync, same commit |
| Add a model provider | `app/providers.py` | verify base_url/model id against live docs, not memory |
| Change auth | `app/auth.py` + `app/config.py` | one static token, no refresh — by design |
| Change persisted schema | `app/db.py` (`SCHEMA` string) | plain SQL, no migrations tool yet |
| Understand a past design decision | `docs/adr/` | see `docs/adr/AGENTS.md` for the index |
| Start/resume a build phase | `phases/*/CONTEXT.md` | root `CLAUDE.md` has the full routing table |

## CODE MAP
| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `app.main:app` | FastAPI instance | `app/main.py` | entry point, `uvicorn app.main:app` |
| `chat._run_turn` | async generator | `app/routers/chat.py` | the whole loop: stream, tool-exec, persist |
| `registry.TOOLS` / `register()` | list + fn | `app/tools/registry.py` | flat append-only tool catalog |
| `providers.PROVIDERS` | list | `app/providers.py` | flat append-only model-provider catalog |
| `memory.remember/forget` | async fn | `app/memory.py` | tier-1 facts, size-capped at `MAX_FACTS_CHARS` |
| `sse.encode_event` | fn | `app/sse.py` | owning source for `docs/CONTRACT.md` |
| `db.SCHEMA` | str | `app/db.py` | full SQLite schema, applied via `executescript` on connect |

## CONVENTIONS
- Flat, append-only registries (tools, providers) instead of branching logic — `chat.py` never
  special-cases a tool/provider name. See ADR-009.
- Every module that talks to an external system carries a docstring explaining *why* its current
  shape exists (which provider, which workaround, which ADR) — not just what it does. Follow this
  pattern; a bare docstring is a regression here.
- `docs/CONTRACT.md` and `app/sse.py` are one contract in two files — any change to one lands in
  the same commit as the other.
- No ORM, no migrations tool: plain SQL in `db.py`, `CREATE TABLE IF NOT EXISTS` only.

## ANTI-PATTERNS (THIS PROJECT)
- Don't add per-tool or per-provider `if name == ...` branches — extend the registry instead.
- Don't guess a provider's model id or base_url from training knowledge — this landscape moves
  fast; a wrong id fails silently as a 404. Verify live, then note the verification date.
- Don't silently auto-summarize memory past its cap (`app/memory.py`) — fail loudly and ask the
  model to consolidate.
- Don't let `app/sse.py`'s actual frames drift from `docs/CONTRACT.md` — that's the *only* file
  `assistant-android` reads from this repo.
- Don't mark a phase done without an actual `REPORT.md` — see root `CLAUDE.md`.

## COMMANDS
```bash
uv sync --extra dev              # or pip install -e .[dev]
uvicorn app.main:app --reload    # run locally
pytest                            # asyncio_mode=auto, no --asyncio-mode flag needed
python scripts/gen_bearer_token.py
./scripts/sync_secrets_from_bitwarden.sh   # populates assistant.env from Bitwarden
```

## NOTES
- Active model provider is hardcoded to `minimax` in `app/openai_client.py`
  (`_ACTIVE_PROVIDER_NAME`) — the original plan (Cline's gateway) is blocked on a billing issue.
  Swapping providers today means editing that constant, not a config value.
- `ASSISTANT_BEARER_TOKEN` has no default on purpose — the app refuses to start rather than run
  with no real auth (ADR-002 philosophy: errors carry intent).
- Test the SSE contract, not the ADRs: `docs/adr/*.md` are historical record, not upheld by CI.
