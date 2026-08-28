# Phase 04 — skills (self-learning & evolving) Report

## What was built

1. **Skills Loader (`app/skills.py`)**:
   - YAML frontmatter parser for `skills/*.md` using `pyyaml`.
   - Immutable `Skill` dataclass (`name`, `description`, `when_to_use`, `content`, `tools`, `revision`, `path`).
   - Resilient loader: malformed/missing frontmatter logs warnings and skips without crashing startup.
   - In-memory overlay system allowing transient or MCP-provided auto-skills to survive reload cycles.
   - Atomic writer `save_skill` with revision increments, automatic history archiving in `.history/<name>-r<N>.md`, and 20-file history pruning.

2. **Skill Tools (`app/tools/skills_tools.py`)**:
   - `list_skills()`: compact JSON listing all loaded skills and activation counts from SQLite.
   - `use_skill(name)`: loads instructions, increments `skill_usage` activation counter.
   - `create_skill(name, description, when_to_use, content, reason)`: validates name (`^[a-z0-9][a-z0-9-]*$`, max 48 chars) and content length (≤16k chars), writes new skill file, reloads index.
   - `update_skill(name, content)`: atomic rewrite via `save_skill`, increments revision.

3. **Pattern-Based Self-Learning (`app/patterns.py`)**:
   - SQLite tables `skill_usage` and `action_patterns`.
   - Canonical JSON template hashing for tool call arguments.
   - Threshold tracking: exact crossing at 3 repeats triggers candidate nudge.
   - `pending_nudge_notice()` generates system prompt notices and enforces max 2 nudges per pattern.
   - Startup pruning of stale patterns (>60 days).

4. **Progressive Disclosure & Chat Loop Wiring (`app/routers/chat.py`)**:
   - Injects pending pattern notices and updated system prompt rules into system prompt before turn.
   - Request-scoped `activated` tool set: when `use_skill`, `create_skill`, or `update_skill` is called, referenced tools in `Skill.tools` are dynamically added to subsequent OpenAI completion roundtrips.
   - Records patterns for every successfully executed tool call.

5. **Shipped Example Skill (`skills/morning-brief.md`)**:
   - `morning-brief` referencing `list_todays_calendar` and `list_unread_emails`.

## Evidence

1. **Local Test Suite**:
   ```bash
   uv run pytest tests -q
   ```
   Output: `59 passed, 4 warnings in 3.17s` (including comprehensive `test_skills.py` and `test_patterns.py`).

2. **Skill Verification Command**:
   ```bash
   uv run python -c "from pathlib import Path; from app import skills; skills.load_skills(Path('skills')); s=skills.get_skill('morning-brief'); print(s.revision, s.tools)"
   ```
   Output: `1 ('list_todays_calendar', 'list_unread_emails')`

3. **VPS Deployment**:
   - Deployed code and `skills/` to `assistant-vps` (`/opt/assistant-backend/`).
   - Service restarted via systemd; verified active and running.

4. **Live Verification**:
   - `POST /v1/chat` with `"Give me a morning brief"` executed `list_todays_calendar`, `list_unread_emails`, `list_reminders`, `get_current_time` with live Google OAuth tokens and returned real user data.
   - `POST /v1/chat` with `"Please use create_skill to create a skill named flat-white..."` created `/opt/assistant-backend/skills/flat-white.md` live (revision 1) and confirmed file write.
   - Verified `action_patterns` rows in `/opt/assistant-backend/assistant.db` tracking counts for all executed tools.
