# Phase 01.5 — tool-calling plumbing proof

**Reads:** phase `01`'s `REPORT.md` (must exist first). `docs/CONTRACT.md`'s `tool_call_started/progress/finished` events.

**Does:** register one trivial fake tool (`get_current_time`, pure Python, no I/O) in `app/tools/registry.py` alongside the memory tools, wire the execute-and-continue loop in `app/routers/chat.py` (model requests a tool → backend runs it → result fed back into the same OpenAI turn → `tool_call_*` events forwarded to the phone throughout). This validates the entire tool-calling seam — both the backend's loop and the Android side's `ChatReducer` — against a trivial tool, so plumbing bugs are caught before a real tool (reminders) exists to blame instead.

**Writes:** an addition to `app/tools/registry.py`, the tool-execution loop inside `app/routers/chat.py`.

**Human check:** ask "what time is it" — confirm the phone shows a tool-call chip going pending → done, and the model's final answer reflects the tool's result. Separately: say "remember that I go by [name]," start a *new* conversation, confirm it still knows without being told again — this is the real proof tier-1 memory is wired into the system prompt, not just that the tool call itself succeeded.

**When done:** write `REPORT.md`.
