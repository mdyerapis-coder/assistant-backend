# app/tools/

## OVERVIEW
Flat, append-only registry of model-callable tools (ADR-009) — `chat.py` never branches on tool names.

## WHERE TO LOOK
| Task | Location |
|------|----------|
| Add a new tool | new file here, call `register(ToolSpec(...))` at import time |
| Change what tools the model sees per-request | `registry.always_visible_tools()` |
| Wire a tool module into the chat loop | import it (for side effects) in `app/routers/chat.py`, `# noqa: F401` |
| Reminders CRUD | `reminders.py` (creation/list/cancel only — delivery is a separate phase, ADR-006) |
| Durable user facts + conversation search | `memory_tools.py` (thin wrapper over `app/memory.py`) |
| Trivial no-I/O reference tool | `time_tool.py` — keep as the canonical "prove the seam" example |

## CONVENTIONS
- One file per tool/tool-group; each file both defines the async fn(s) and calls `register()` at
  module scope — importing the module is what registers it, no separate init step.
- `ToolSpec.fn` is always `async def`, always returns `str` (or something `json.dumps`-able that
  gets stringified) — the chat loop feeds the return value straight back to the model as tool output.
- Tool functions never touch FastAPI/OpenAI types — keep them plain `db`/domain calls so they stay
  independently testable (mirrors why `memory.py` itself is framework-free).
- Errors from a tool call are caught in `chat.py`, not here — a tool function can raise; it doesn't
  need its own try/except unless it wants a specific user-facing message instead of the generic
  `Tool '{name}' failed: {exc}`.

## ANTI-PATTERNS
- Don't add `always_visible=False` tools yet — `list_skills()`/`use_skill()` (progressive
  disclosure) isn't built (phase 03+, see ADR-009). Every registered tool today is always-visible.
- Don't give a tool function FastAPI/Pydantic parameters — `chat.py` calls `fn(**kwargs)` from
  parsed JSON args, not through FastAPI's DI.
