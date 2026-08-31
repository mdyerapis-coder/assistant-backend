"""Plugin loader and lifecycle manager for assistant-backend.

Bundled extension packages live under `assistant-backend/plugins/<name>/`.
Each plugin contains a `manifest.json` declaring its metadata, skills,
tools, and embedded MCP servers.

Plugin Python code is trusted (single-user self-hosted system) and executed
directly. Tools are registered into the global ToolRegistry and skills are
namespaced as `<plugin_name>.<skill_name>`.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import db, mcp_client, skills
from .mcp_client import McpServerConfig, McpSession
from .tools import registry

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

PLUGINS_DIR: Path | None = None
_PLUGINS: dict[str, "PluginManifest"] = {}
_PLUGIN_TOOLS: dict[str, set[str]] = {}
_PLUGIN_SESSIONS: dict[str, list[McpSession]] = {}


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: str
    description: str
    skills: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    mcp_servers: tuple[dict[str, Any], ...] = ()
    dir_path: Path | None = None


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def load_manifest(plugin_dir: Path) -> PluginManifest | None:
    """Parse manifest.json from plugin_dir; returns None if invalid."""
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("invalid JSON in %s: %s", manifest_path, exc)
        return None

    if not isinstance(data, dict):
        return None

    name = data.get("name")
    if not name or not isinstance(name, str) or not _NAME_RE.match(name):
        logger.warning("invalid plugin name %r in %s", name, manifest_path)
        return None

    if name != plugin_dir.name:
        logger.warning(
            "plugin name %r does not match directory name %r, skipping",
            name,
            plugin_dir.name,
        )
        return None

    version = str(data.get("version", "0.1.0"))
    description = str(data.get("description", ""))
    skills_patterns = tuple(
        str(s) for s in data.get("skills", []) if isinstance(s, str)
    )
    tools_patterns = tuple(
        str(t) for t in data.get("tools", []) if isinstance(t, str)
    )
    mcp_servers = tuple(
        s for s in data.get("mcp_servers", []) if isinstance(s, dict)
    )

    return PluginManifest(
        name=name,
        version=version,
        description=description,
        skills=skills_patterns,
        tools=tools_patterns,
        mcp_servers=mcp_servers,
        dir_path=plugin_dir,
    )


async def _activate_plugin(manifest: PluginManifest) -> None:
    """Load and register a plugin's tools, skills, and MCP servers."""
    assert manifest.dir_path is not None
    logger.info("Activating plugin '%s' v%s", manifest.name, manifest.version)

    # 1. Tools: import python files matching globs
    registered_before = set(registry._TOOL_MAP.keys())
    for pattern in manifest.tools:
        for tool_file in sorted(manifest.dir_path.glob(pattern)):
            if tool_file.suffix == ".py" and tool_file.is_file():
                module_name = f"plugin_{manifest.name}_{tool_file.stem}"
                try:
                    spec = importlib.util.spec_from_file_location(
                        module_name, tool_file
                    )
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                except Exception as exc:
                    logger.warning(
                        "failed to import tool file %s for plugin %s: %s",
                        tool_file,
                        manifest.name,
                        exc,
                    )
    new_tools = set(registry._TOOL_MAP.keys()) - registered_before
    _PLUGIN_TOOLS[manifest.name] = new_tools

    # 2. Skills: merge markdown files with namespace prefix
    for pattern in manifest.skills:
        # e.g. "skills/*.md" -> look in manifest.dir_path / "skills"
        glob_path = manifest.dir_path / pattern
        search_dir = glob_path.parent
        if search_dir.is_dir():
            skills.merge_skills(search_dir, namespace=manifest.name)

    # 3. MCP Servers: start any embedded MCP server definitions
    if manifest.mcp_servers:
        raw_servers = []
        for server_raw in manifest.mcp_servers:
            server_name = f"{manifest.name}_{server_raw.get('name', 'server')}"
            raw_copy = dict(server_raw)
            raw_copy["name"] = server_name
            raw_servers.append(raw_copy)

        cfg_list = mcp_client.load_mcp_config_from_dicts(raw_servers)
        sessions: list[McpSession] = []
        for cfg in cfg_list:
            session = McpSession(cfg)
            try:
                await session.start()
                await session.register_tools()
                sessions.append(session)
            except Exception as exc:
                logger.warning(
                    "failed to start MCP server %s for plugin %s: %s",
                    cfg.name,
                    manifest.name,
                    exc,
                )
        _PLUGIN_SESSIONS[manifest.name] = sessions


async def _deactivate_plugin(name: str) -> None:
    """Unload tools, skills, and stop MCP servers for a plugin."""
    logger.info("Deactivating plugin '%s'", name)
    # 1. Tools
    tools_to_remove = _PLUGIN_TOOLS.pop(name, set())
    if tools_to_remove:
        registry.unregister(tools_to_remove)

    # 2. Skills
    skills.uninstall_skills(f"{name}.")

    # 3. MCP Servers
    sessions = _PLUGIN_SESSIONS.pop(name, [])
    for session in sessions:
        await session.stop()


async def load_plugins(plugins_dir: Path) -> None:
    """Discover all plugins in `plugins_dir`, sync DB rows, and activate enabled plugins."""
    global PLUGINS_DIR, _PLUGINS
    PLUGINS_DIR = plugins_dir
    _PLUGINS.clear()

    if not plugins_dir.is_dir():
        logger.debug("plugins directory %s does not exist", plugins_dir)
        return

    conn = db.get_connection()
    for child in sorted(plugins_dir.iterdir()):
        if not child.is_dir():
            continue
        manifest = load_manifest(child)
        if manifest is None:
            continue

        _PLUGINS[manifest.name] = manifest

        # Check / upsert row in database
        async with conn.execute(
            "SELECT enabled FROM plugins WHERE name = ?", (manifest.name,)
        ) as cursor:
            row = await cursor.fetchone()

        if row is None:
            await conn.execute(
                "INSERT INTO plugins (name, version, enabled, installed_at) "
                "VALUES (?, ?, 1, ?)",
                (manifest.name, manifest.version, _now()),
            )
            await conn.commit()
            enabled = 1
        else:
            enabled = row[0]

        if enabled == 1:
            await _activate_plugin(manifest)


async def enable_plugin(name: str) -> str:
    """Enable a plugin and activate its tools, skills, and MCP servers."""
    if name not in _PLUGINS:
        return f"Error: unknown plugin '{name}'"
    conn = db.get_connection()
    await conn.execute("UPDATE plugins SET enabled = 1 WHERE name = ?", (name,))
    await conn.commit()
    await _activate_plugin(_PLUGINS[name])
    return f"Plugin '{name}' enabled successfully."


async def disable_plugin(name: str) -> str:
    """Disable a plugin and remove its tools, skills, and MCP servers."""
    if name not in _PLUGINS:
        return f"Error: unknown plugin '{name}'"
    conn = db.get_connection()
    await conn.execute("UPDATE plugins SET enabled = 0 WHERE name = ?", (name,))
    await conn.commit()
    await _deactivate_plugin(name)
    return f"Plugin '{name}' disabled successfully."


async def list_plugins() -> list[dict[str, Any]]:
    """List all known plugins with their enabled status and resource counts."""
    conn = db.get_connection()
    async with conn.execute(
        "SELECT name, version, enabled, installed_at FROM plugins"
    ) as cursor:
        rows = await cursor.fetchall()
    db_status = {r[0]: {"version": r[1], "enabled": bool(r[2]), "installed_at": r[3]} for r in rows}

    result = []
    for name, manifest in _PLUGINS.items():
        st = db_status.get(name, {"version": manifest.version, "enabled": True, "installed_at": _now()})
        tool_count = len(_PLUGIN_TOOLS.get(name, set()))
        skill_count = len(
            [s for s in skills.all_skills() if s.name.startswith(f"{name}.")]
        )
        result.append(
            {
                "name": name,
                "version": st["version"],
                "description": manifest.description,
                "enabled": st["enabled"],
                "tools_count": tool_count,
                "skills_count": skill_count,
                "installed_at": st["installed_at"],
            }
        )
    return result


async def stop_all_plugins() -> None:
    """Stop all active plugin MCP sessions."""
    for name in list(_PLUGIN_SESSIONS.keys()):
        await _deactivate_plugin(name)
