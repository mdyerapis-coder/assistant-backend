# Phase 06 — Plugins (bundled extension packages)

Execution spec transcribed from `v2-feature-program-plan.md` (approved). ICM convention: this file is the execution spec; `REPORT.md` carries completed evidence. Completes the backend track (skills → MCP → plugins; plugins bundle skills, tools, and MCP servers).

## Does

Adds a modular plugin system where extension packages placed in `assistant-backend/plugins/<name>/` are discovered and managed via `manifest.json`.

- Manifest format `plugins/<name>/manifest.json`:
  - `name`: string matching directory name (`^[a-z0-9][a-z0-9_-]*$`)
  - `version`: semantic version string
  - `description`: package summary
  - `skills`: list of glob patterns (e.g. `["skills/*.md"]`)
  - `tools`: list of glob patterns (e.g. `["tools/*.py"]`)
  - `mcp_servers`: list of MCP server configuration dicts
- Database schema: `plugins (name TEXT PRIMARY KEY, version TEXT, enabled INTEGER DEFAULT 1, installed_at TEXT)` in `app/db.py`.
- `app/plugins.py`:
  - `PluginManifest` dataclass.
  - `load_plugins(plugins_dir: Path) -> None`: discovers manifests, initializes DB rows, activates enabled plugins.
  - Tool loading: dynamically imports plugin tool modules using `importlib.util` (modules call `registry.register` on import).
  - Skill loading: invokes `skills.merge_skills(skills_dir, namespace=plugin_name)` so skills are namespaced as `f"{plugin}.{skillname}"`.
  - MCP server loading: initializes plugin-defined MCP sessions via `mcp_client`.
  - `enable_plugin(name)` / `disable_plugin(name)`: updates DB state and performs live registration/unregistration.
- Chat tools (`app/tools/plugin_tools.py`):
  - `list_plugins()`: returns JSON of name, version, description, enabled, tool count, skill count.
  - `enable_plugin(name)`: enables plugin and activates components.
  - `disable_plugin(name)`: disables plugin and unloads components.
  - Registered as `always_visible=True`.
- Wire into `app/main.py` lifespan: load plugins after skills and core MCP startup; shutdown plugin MCP sessions on exit.

## Verification

- `uv run pytest tests -q` passes (includes `tests/test_plugins.py`).
- Shipped example fixture plugin (`plugins/demo/manifest.json` with a tool, skill, and mcp config).
- Live VPS verification: `list_plugins` returns enabled demo plugin, `use_skill` executes the namespaced plugin skill, `disable_plugin` removes it from `list_skills`, `enable_plugin` restores it.

## Non-goals

- No remote marketplace or package repository (filesystem installation only: git clone / scp into `plugins/`).
- Plugin Python code is trusted (self-hosted, single user) — no sandboxing.
