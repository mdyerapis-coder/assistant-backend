# Phase 06 — Plugins (bundled extension packages) Report

## What was built

1. **Plugin Package Architecture (`app/plugins.py`)**:
   - `PluginManifest` dataclass parsing `plugins/<name>/manifest.json`.
   - Validates that manifest `name` matches directory name (`^[a-z0-9][a-z0-9_-]*$`).
   - SQLite table `plugins` tracking `name`, `version`, `enabled`, `installed_at`.
   - `load_plugins(plugins_dir)` discovers plugins at startup, initializes SQLite state, and activates enabled packages.

2. **Modular Component Loading**:
   - **Tools**: Dynamic module import using `importlib.util` for files matching `tools/*.py`. Tools self-register into `registry.py` and are tracked by plugin name for precise unregistration.
   - **Skills**: Namespaced markdown loading via `skills.merge_skills(skills_dir, namespace=plugin_name)`, publishing skills as `<plugin_name>.<skill_name>`.
   - **MCP Servers**: Embedded MCP servers declared in `manifest.json` are initialized via `McpSession` and tracked per plugin.

3. **Lifecycle Management & Chat Tools (`app/tools/plugin_tools.py`)**:
   - `list_plugins()`: JSON summary of all installed packages, enabled flags, version, tool count, and skill count.
   - `enable_plugin(name)`: updates DB state to `enabled=1`, imports tools, merges skills, and starts MCP servers.
   - `disable_plugin(name)`: updates DB state to `enabled=0`, unregisters tools via `registry.unregister`, uninstalls skills, and halts MCP sessions.
   - All tools registered with `always_visible=True`.

4. **Shipped Example Plugin (`plugins/demo/`)**:
   - `manifest.json` declaring metadata and glob patterns.
   - `skills/demo-procedure.md` containing `demo-procedure` skill.
   - `tools/demo_tools.py` registering `plugin_demo_greet`.

## Evidence

1. **Automated Unit Tests**:
   ```bash
   uv run pytest tests -q
   ```
   Output: `65 passed, 4 warnings in 9.31s` (including comprehensive `tests/test_plugins.py` exercising 1 tool, 1 skill, and 1 embedded MCP server).

2. **VPS Deployment**:
   - Synchronized `app/` and `plugins/` to `assistant-vps`.
   - Restarted `assistant.service` via systemd; verified active status and clean log output.

3. **Live End-to-End Chat Verification**:
   - Executed live `POST /v1/chat` on `https://assistant.llmclouds.au/v1/chat`:
     1. Prompt: `"Please list the plugins, then use the demo skill to greet Mason"`
        - `list_plugins` returned `demo` (v0.1.0, enabled: true).
        - `use_skill(name="demo.demo-procedure")` loaded the namespaced skill and activated `plugin_demo_greet`.
        - Model executed `plugin_demo_greet(name="Mason")` and streamed `"Hello, Mason! This is from the demo plugin."`.
     2. Prompt: `"Please disable the demo plugin using disable_plugin"`
        - `disable_plugin(name="demo")` successfully updated DB and unlinked components.
     3. Prompt: `"Please enable the demo plugin using enable_plugin"`
        - Model inspected `list_plugins` (showed `enabled: false`), invoked `enable_plugin(name="demo")`, and confirmed reactivation.
