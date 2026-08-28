# Phase 05 — MCP (Model Context Protocol) Client Report

## What was built

1. **MCP Configuration Loader (`app/mcp_client.py`)**:
   - `load_mcp_config(path)` parses `mcp_servers.json` for `stdio` and `http` server definitions.
   - Recursive environment variable substitution for `env:VAR_NAME` in headers, URLs, commands, and environment dictionaries.
   - Robust error handling: invalid paths, malformed JSON, and invalid configurations are skipped with warnings without halting application startup.

2. **Session Lifecycle & Transport (`app/mcp_client.py`)**:
   - `McpSession` manages transport contexts (`stdio_client` and `streamable_http_client` via `AsyncExitStack`).
   - Resolves Python executable seamlessly across environments.
   - `start_all()` and `stop_all()` wired into `app/main.py` FastAPI lifespan.

3. **Tool Bridging & Auto-Skills**:
   - Dynamic tool discovery via `ClientSession.list_tools()`.
   - Tool namespacing: `mcp_{server_name}_{tool.name}`.
   - Tools registered into `registry.py` with `always_visible=False` (preserving base token budget).
   - In-memory auto-skill registered via `skills.install_skill` (`mcp-<server_name>`) referencing all bridged tools.
   - Tool execution wrapper (`_make_caller`) handling result strings, structured contents, and error isolation.
   - Clean unregistration: `McpSession.stop()` removes tools and uninstalls auto-skills.

4. **Standalone Demo Server (`scripts/mcp_demo_server.py`)**:
   - Executable stdio MCP server exposing `echo` and `add` tools.

## Evidence

1. **Automated Unit Tests**:
   ```bash
   uv run pytest tests -q
   ```
   Output: `63 passed, 4 warnings in 7.24s` (including comprehensive `tests/test_mcp_client.py`).

2. **VPS Deployment**:
   - Synchronized `app/`, `scripts/mcp_demo_server.py`, `mcp_servers.json` to `assistant-vps`.
   - Installed `mcp` SDK in the VPS virtual environment and restarted `assistant.service`.
   - Verified service running and `/v1/health` responding 200 OK.

3. **Live End-to-End Chat Verification**:
   - Executed live `POST /v1/chat` on `https://assistant.llmclouds.au/v1/chat`:
     1. Prompt: `"Use list_skills, find the demo MCP skill, and use it to echo hello"`
        - `list_skills` discovered `mcp-demo`.
        - `use_skill(name="mcp-demo")` activated `mcp_demo_echo` and `mcp_demo_add`.
        - Executed `mcp_demo_echo(text="hello")` and returned output.
     2. Prompt: `"Use list_skills, find the demo MCP skill, and use it to add 40 and 2"`
        - Discovered `mcp-demo`, activated tools, executed `mcp_demo_add(a=40, b=2)`, and streamed answer `"40 + 2 = **42**"`.
