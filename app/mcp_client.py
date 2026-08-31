"""MCP (Model Context Protocol) client for assistant-backend.

Connects to external MCP servers via stdio or streamable HTTP transports,
bridges their tools into the internal ToolSpec registry (always_visible=False),
and exposes them to the model through in-memory auto-skills (mcp-<server_name>).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from . import skills
from .skills import Skill
from .tools import registry
from .tools.registry import ToolSpec

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SESSIONS: list["McpSession"] = []


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    transport: str
    command: tuple[str, ...] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    env: dict[str, str] | None = None


def _substitute_env_val(val: Any) -> Any:
    if isinstance(val, str):
        return re.sub(r"env:([A-Za-z0-9_]+)", lambda m: os.environ.get(m.group(1), ""), val)
    elif isinstance(val, list):
        return [_substitute_env_val(v) for v in val]
    elif isinstance(val, dict):
        return {k: _substitute_env_val(v) for k, v in val.items()}
    return val


def load_mcp_config_from_dicts(servers_raw: list[dict[str, Any]]) -> list[McpServerConfig]:
    """Parse a list of raw server dicts into McpServerConfig instances."""
    configs: list[McpServerConfig] = []
    for raw in servers_raw:
        if not isinstance(raw, dict):
            logger.warning("skipping non-dict server entry")
            continue
        name = raw.get("name")
        transport = raw.get("transport")
        if not name or not isinstance(name, str) or not _NAME_RE.match(name):
            logger.warning("skipping mcp server with invalid name: %r", name)
            continue
        if transport not in ("stdio", "http"):
            logger.warning("skipping server %s with unknown transport %r", name, transport)
            continue

        raw_sub = _substitute_env_val(raw)
        command_list = raw_sub.get("command")
        command_tuple = (
            tuple(str(c) for c in command_list)
            if isinstance(command_list, list) and command_list
            else None
        )
        url = raw_sub.get("url")
        headers = raw_sub.get("headers") if isinstance(raw_sub.get("headers"), dict) else None
        env = raw_sub.get("env") if isinstance(raw_sub.get("env"), dict) else None

        if transport == "stdio" and not command_tuple:
            logger.warning("stdio server %s missing command, skipping", name)
            continue
        if transport == "http" and not (url and isinstance(url, str)):
            logger.warning("http server %s missing url, skipping", name)
            continue

        configs.append(
            McpServerConfig(
                name=name,
                transport=transport,
                command=command_tuple,
                url=url,
                headers=headers,
                env=env,
            )
        )
    return configs


def load_mcp_config(path: Path) -> list[McpServerConfig]:
    """Parse mcp_servers.json into a list of McpServerConfig.

    Invalid entries are logged and skipped without crashing startup.
    """
    if not path.is_file():
        logger.debug("mcp config file not found: %s", path)
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("failed to parse mcp config %s: %s", path, exc)
        return []

    servers_raw = data.get("servers", [])
    if not isinstance(servers_raw, list):
        logger.warning("mcp config %s 'servers' is not a list", path)
        return []
    return load_mcp_config_from_dicts(servers_raw)


class McpSession:
    """Manages an active connection to a single MCP server."""

    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._exit_stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self.registered_tools: list[str] = []

    async def start(self) -> None:
        """Establish transport and initialize MCP session."""
        self._exit_stack = AsyncExitStack()
        try:
            if self.config.transport == "stdio":
                assert self.config.command is not None
                env = {**os.environ, **(self.config.env or {})}
                cmd = self.config.command[0]
                if cmd in ("python", "python3"):
                    cmd = sys.executable
                params = StdioServerParameters(
                    command=cmd,
                    args=list(self.config.command[1:]),
                    env=env,
                )
                read_stream, write_stream = await self._exit_stack.enter_async_context(
                    stdio_client(params)
                )
            elif self.config.transport == "http":
                assert self.config.url is not None
                headers = self.config.headers or {}
                http_client = await self._exit_stack.enter_async_context(
                    httpx.AsyncClient(headers=headers)
                )
                read_stream, write_stream = await self._exit_stack.enter_async_context(
                    streamable_http_client(self.config.url, http_client=http_client)
                )
            else:
                raise ValueError(f"unsupported transport {self.config.transport}")

            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self._session.initialize()
        except Exception:
            await self.stop()
            raise

    def _make_caller(self, mcp_tool_name: str):
        async def fn(**kwargs: Any) -> str:
            if self._session is None:
                return f"Error: MCP server '{self.config.name}' is not connected."
            try:
                res = await self._session.call_tool(mcp_tool_name, arguments=kwargs)
                if getattr(res, "is_error", False):
                    err_msg = "".join(
                        getattr(c, "text", str(c)) for c in getattr(res, "content", [])
                    )
                    return f"Error: {err_msg}" if err_msg else "Error: tool execution failed"

                text_parts = []
                for item in getattr(res, "content", []):
                    if hasattr(item, "text") and item.text is not None:
                        text_parts.append(str(item.text))
                    else:
                        text_parts.append(str(item))

                if text_parts:
                    return "\n".join(text_parts)
                if getattr(res, "structured_content", None) is not None:
                    return json.dumps(res.structured_content)
                return "{}"
            except Exception as exc:
                return f"Error: {exc}"

        return fn

    async def register_tools(self) -> int:
        """Fetch tools from MCP server, register in ToolRegistry and create auto-skill."""
        if self._session is None:
            raise RuntimeError("session not started")

        tools_result = await self._session.list_tools()
        registered_count = 0
        self.registered_tools = []
        skill_lines = []

        for tool in tools_result.tools:
            registry_name = f"mcp_{self.config.name}_{tool.name}"
            if registry.get_tool(registry_name) is not None:
                logger.warning("tool %s already in registry; skipping", registry_name)
                continue

            schema = getattr(tool, "input_schema", getattr(tool, "inputSchema", {}))
            params = schema if isinstance(schema, dict) else {}
            description = tool.description or f"Tool {tool.name} from MCP server {self.config.name}"
            spec = ToolSpec(
                name=registry_name,
                description=description,
                parameters=params,
                fn=self._make_caller(tool.name),
                always_visible=False,
            )
            registry.register(spec)
            self.registered_tools.append(registry_name)
            skill_lines.append(f"- {tool.name}: {description}")
            registered_count += 1

        # Register in-memory auto-skill so model discovers MCP server via list_skills
        auto_skill_name = f"mcp-{self.config.name}"
        auto_skill_body = (
            f"# MCP Server: {self.config.name}\n\n"
            f"Available tools from this server:\n"
            + ("\n".join(skill_lines) if skill_lines else "No tools exported.")
        )
        auto_skill = Skill(
            name=auto_skill_name,
            description=f"Tools provided by MCP server '{self.config.name}'",
            when_to_use=f"When needing tools or integrations from {self.config.name}",
            content=auto_skill_body,
            tools=tuple(self.registered_tools),
            revision=0,
            path=None,
        )
        skills.install_skill(auto_skill)
        return registered_count

    async def stop(self) -> None:
        """Close active MCP session, unregister tools, and release resources."""
        if self.registered_tools:
            registry.unregister(self.registered_tools)
            self.registered_tools = []
        skills.uninstall_skills(f"mcp-{self.config.name}")
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception as exc:
                logger.warning("error closing MCP session %s: %s", self.config.name, exc)
            finally:
                self._exit_stack = None
                self._session = None

async def start_all(configs: list[McpServerConfig]) -> list[McpSession]:
    """Start all configured MCP sessions; failures are logged and skipped."""
    global _SESSIONS
    active: list[McpSession] = []
    for cfg in configs:
        session = McpSession(cfg)
        try:
            await session.start()
            count = await session.register_tools()
            active.append(session)
            logger.info("Started MCP server '%s' (%d tools registered)", cfg.name, count)
        except Exception as exc:
            logger.warning("Failed to start MCP server '%s': %s", cfg.name, exc)
    _SESSIONS = active
    return active


async def stop_all() -> None:
    """Shut down all running MCP sessions."""
    global _SESSIONS
    for session in reversed(_SESSIONS):
        try:
            await session.stop()
        except Exception as exc:
            logger.warning("error stopping session %s: %s", session.config.name, exc)
    _SESSIONS.clear()
