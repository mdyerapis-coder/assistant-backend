import json
import os
import sys
from pathlib import Path

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

import pytest

from app import db, mcp_client, skills
from app.mcp_client import McpServerConfig, McpSession, load_mcp_config
from app.tools.registry import always_visible_tools, get_tool


@pytest.fixture(autouse=True)
async def _db(tmp_path: Path):
    await db.connect()
    skills.load_skills(tmp_path)
    yield
    await mcp_client.stop_all()
    await db.disconnect()


def test_load_mcp_config_valid_and_env_substitution(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "secret_key_123")
    monkeypatch.setenv("TEST_PORT", "9090")

    config_file = tmp_path / "mcp_servers.json"
    config_file.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "local_stdio",
                        "transport": "stdio",
                        "command": ["python3", "server.py"],
                        "env": {"API_KEY": "env:TEST_API_KEY"},
                    },
                    {
                        "name": "remote_http",
                        "transport": "http",
                        "url": "http://localhost:env:TEST_PORT/mcp",
                        "headers": {"Authorization": "Bearer env:TEST_API_KEY"},
                    },
                    {
                        "name": "invalid_transport",
                        "transport": "unknown",
                    },
                    {
                        "name": "bad_name!",
                        "transport": "stdio",
                        "command": ["ls"],
                    },
                ]
            }
        )
    )

    configs = load_mcp_config(config_file)
    assert len(configs) == 2

    stdio_cfg = configs[0]
    assert stdio_cfg.name == "local_stdio"
    assert stdio_cfg.transport == "stdio"
    assert stdio_cfg.command == ("python3", "server.py")
    assert stdio_cfg.env == {"API_KEY": "secret_key_123"}

    http_cfg = configs[1]
    assert http_cfg.name == "remote_http"
    assert http_cfg.transport == "http"
    assert http_cfg.url == "http://localhost:9090/mcp"
    assert http_cfg.headers == {"Authorization": "Bearer secret_key_123"}


def test_load_mcp_config_missing_or_corrupt(tmp_path: Path):
    assert load_mcp_config(tmp_path / "nonexistent.json") == []

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("invalid json content {{{")
    assert load_mcp_config(corrupt) == []


@pytest.mark.asyncio
async def test_mcp_session_stdio_end_to_end():
    demo_script = Path(__file__).parent.parent / "scripts" / "mcp_demo_server.py"
    assert demo_script.exists(), "mcp_demo_server.py must exist"

    cfg = McpServerConfig(
        name="demo",
        transport="stdio",
        command=(sys.executable, str(demo_script)),
    )

    session = McpSession(cfg)
    await session.start()
    try:
        count = await session.register_tools()
        assert count == 2
        assert "mcp_demo_echo" in session.registered_tools
        assert "mcp_demo_add" in session.registered_tools

        # MCP tools must NOT be always visible in the root prompt
        visible_names = {t.name for t in always_visible_tools()}
        assert "mcp_demo_echo" not in visible_names
        assert "mcp_demo_add" not in visible_names

        # Auto-skill must be generated in skills index
        skill = skills.get_skill("mcp-demo")
        assert skill is not None
        assert skill.tools == ("mcp_demo_echo", "mcp_demo_add")
        assert "echo" in skill.content
        assert "add" in skill.content

        # Test tool execution: echo
        echo_tool = get_tool("mcp_demo_echo")
        assert echo_tool is not None
        res_echo = await echo_tool.fn(text="hello from test")
        assert res_echo == "hello from test"

        # Test tool execution: add
        add_tool = get_tool("mcp_demo_add")
        assert add_tool is not None
        res_add = await add_tool.fn(a=12, b=30)
        assert "42" in res_add
    finally:
        await session.stop()


@pytest.mark.asyncio
async def test_mcp_tool_activation_via_use_skill():
    demo_script = Path(__file__).parent.parent / "scripts" / "mcp_demo_server.py"
    cfg = McpServerConfig(
        name="demo",
        transport="stdio",
        command=(sys.executable, str(demo_script)),
    )
    session = McpSession(cfg)
    await session.start()
    try:
        await session.register_tools()
        use_tool = get_tool("use_skill")
        assert use_tool is not None
        content = await use_tool.fn(name="mcp-demo")
        assert "Available tools" in content
        assert "echo" in content
    finally:
        await session.stop()
