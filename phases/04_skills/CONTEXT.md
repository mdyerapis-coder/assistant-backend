# Phase 04 — skills (self-learning & evolving)

Execution spec transcribed from `v2-feature-program-plan.md` (approved). ICM convention: this file is the execution spec; `REPORT.md` carries completed evidence. Phase `03` is live on the VPS; this phase ships after it without touching calendar/Gmail or the SSE contract (`app/sse.py` unchanged).

## Does

Skills are files in `assistant-backend/skills/*.md` (source of truth, committed), loaded at startup. The model can list/use skills, learn new ones via `create_skill` (self-learning), update them via `update_skill`, and repeat-action learning nudges after 3+ identical tool calls. Skills can reference non-visible tools, which are activated (progressive disclosure) into the roundtrip when the skill is used.

- `assistant-backend/skills/` dir with one `SKILL.md`-style file per skill (YAML frontmatter + markdown body). Shipped example: `morning-brief.md`.
- `app/skills.py` (framework-free, mirrors `app/memory.py`):
  - `Skill` frozen dataclass: `name, description, when_to_use, content, tools: tuple[str, ...], revision: int, path: Path`.
  - `load_skills(skills_dir: Path, namespace: str | None = None) -> list[Skill]` — reads `*.md`; parses frontmatter with `pyyaml` (**new dep**); missing/invalid frontmatter → log warning + skip (never crash); `revision` default 1; `tools` default `()`; `content` = body after frontmatter (stripped). With `namespace`, skill `name` becomes `f"{namespace}.{name}"` (used by plugins in Phase 06).
  - Module-level `SKILLS: list[Skill]`, `_SKILL_MAP: dict[str, Skill]`; `get_skill(name)`, `all_skills()`.
  - `save_skill(skill: Skill, new_content: str) -> Skill` — atomic write (tmp + `os.replace`); frontmatter rewritten with `revision = old + 1`; prior file copied to `skills/.history/<name>-r<old_cr>.md`; prune `.history` to 20 newest; returns new `Skill`.
- `action_patterns` + `skill_usage` tables in `app/db.py` schema.
- `app/patterns.py`: `record_pattern(tool_name, args) -> bool` — args_template = canonical JSON (`sort_keys`, compact, ≤512 chars); upsert count+1; returns True exactly when count crosses 3. Startup prune of rows with `last_at < now - 60 days`.
- `app/tools/skills_tools.py`: `list_skills`, `use_skill`, `create_skill`, `update_skill` — registered via import (pattern like `memory_tools`); all `always_visible=True`.
- `app/routers/chat.py`:
  - `SYSTEM_PROMPT_BASE` gains a skills line (repeating a workflow 3+ times → `create_skill`; corrections → `update_skill`).
  - After each successful tool call: `await record_pattern(tool_name, kwargs)`.
  - On each request, before `messages.insert(0, ...)`: if any pattern has `count >= 3 AND nudge_count < 2`, append pattern-notice block to `system_prompt` and `nudge_count += 1` (persisted). Stops after 2 ignored nudges.
  - Progressive disclosure: `activated: set[str]` per request; when executed tool is `use_skill`/`create_skill`/`update_skill`, add that skill's `tools` names to `activated`; subsequent roundtrips use `always_visible_tools() + activated` tool defs. Set grows only within the request.
- `app/main.py` lifespan: `skills.load_skills()` before `yield` (after tool imports so activation can reference registered tools).
- `.gitignore`: add `skills/.history/`.

## Verification

- `uv run pytest tests -q` green (existing 48 + new skills/patterns tests).
- `uv run python -c "from app import skills; skills.load_skills('skills'); s=skills.get_skill('morning-brief'); print(s.revision, s.tools)"` → `1 ('list_todays_calendar', 'list_unread_emails')`.
- Live on VPS (rsync `app/` + `skills/` + restart): morning-brief request → stream shows skill-driven tool calls with real calendar/Gmail data; 3× same tool call → `action_patterns` count=3, 4th request bumps `nudge_count` to 1; `create_skill` live → `skills/coffee_procedure.md` exists, `use_skill` returns it.

## Non-goals (boundaries)

- No skill marketplace, no sandboxing, no schema-driven skill execution — skills are markdown prompts the model reads.
- Pattern learning is tool-call based only; plain-text repetition is not counted.
- Runtime writes on the VPS copy are rsynced back to the repo after verification — not automated in this phase.
