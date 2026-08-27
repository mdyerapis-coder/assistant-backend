# ADR-009: flat append-only tool registry + progressive disclosure for anything non-core

**Status:** live, phase `01` (registry shape) / phase `03`+ (progressive disclosure actually matters)

`app/tools/registry.py` is a flat list — `{name, json_schema, fn, always_visible}` — never routing-logic branches inside `app/routers/chat.py`. Tools flagged `always_visible` (the core set: reminders, calendar, email, `remember`/`forget`) go into every OpenAI `tools=[...]` call. Anything added later that isn't core is reached via `list_skills()` (cheap: names + one-line descriptions) → the model calls `use_skill(name)` to get that skill's full schema injected for the rest of the turn.

**Why:** researched Goose and Hermes Agent/OpenHuman before choosing this split. Goose's extension config (a plain list of `{name, enabled, transport, env}` entries, no custom marketplace server) is the cleanest *registration* ergonomics of anything looked at — adding a tool is appending an entry, never touching routing code. Hermes and OpenHuman's progressive-disclosure retrieval (list-then-expand) is what keeps the per-request token cost from growing with every future capability. Adopting both from day one — cheap now, expensive to retrofit once the tool count grows past the core four.
