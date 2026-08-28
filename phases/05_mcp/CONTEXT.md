# Phase 05 — MCP (Model Context Protocol) client

Execution spec transcribed from `v2-feature-program-plan.md` (approved). ICM convention: this file is the execution spec; `REPORT.md` carries completed evidence. Builds on Phase `04` (skills overlay and tool activation).

## Does

Adds MCP client capabilities to `assistant-backend`, allowing it to connect to external MCP servers (stdio and HTTP transports) configured via `mcp_servers.json`. Tools exposed by connected MCP servers are automatically prefixed and registered in the flat registry as `always_visible=False`. For each server, an in-memory auto-skill (`mcp-<server_name>`) is published into the skills index, enabling the model to discover and activate the server's tools on-demand via `list_skills` and `use_skill`.

- **Dependency**: `mcp` (official Python SDK).
- `assistant-backend/mcp_servers.json`: server configuration format supporting `stdio` and `http` transports, command argv, URLs, and environment variable substitution (`env:VAR_NAME`).
- `app/mcp_client.py`:
  - `McpServerConfig` frozen dataclass and `load_mcp_config(path)`.
  - `McpSession` managing client lifecycles, session initialization, and tool bridging.
  - Prefixing: `mcp_{server_name}_{tool.name}`.
  - Automatic `ToolSpec` wrapping with `always_visible=False`.
  - In-memory auto-skill registration via `skills.install_skill` (`name="mcp-<server_name>"`, `revision=0`, `path=None`, `tools=tuple(registered_mcp_tools)`).
  - Lifecycle management: `start_all(configs)` / `stop_all()` invoked in `app/main.py` lifespan.
- Tests & Fixtures:
  - `scripts/mcp_demo_server.py`: standalone stdio MCP server exposing `echo` and `add` tools.
  - `tests/test_mcp_client.py`: config parsing, tool prefixing and execution, error handling, bad config resilience.

## Verification

- `uv run pytest tests -q` passes.
- `tests/test_mcp_client.py` tests stdio server tool calling end-to-end.
- Deployment to VPS with `mcp_servers.json` containing the demo server or configured servers; `/v1/health` remains 200; `list_skills` displays `mcp-demo`; calling `"echo hello"` triggers `use_skill` / tool execution.

## Non-goals

- No SSE transport (deprecated in MCP SDK; streamable HTTP and stdio only).
- No UI for MCP configuration (file-based `mcp_servers.json` configuration).
