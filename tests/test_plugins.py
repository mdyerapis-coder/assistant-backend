import json
import os
import sys
from pathlib import Path

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

import pytest

from app import db, plugins, skills
from app.tools.registry import get_tool


@pytest.fixture(autouse=True)
async def _db(tmp_path: Path):
    await db.connect()
    skills.clear_overlay()
    skills.load_skills(tmp_path)
    yield
    await plugins.stop_all_plugins()
    skills.clear_overlay()
    await db.disconnect()


def test_load_manifest_valid_and_invalid(tmp_path: Path):
    # Valid manifest
    valid_dir = tmp_path / "my_plugin"
    valid_dir.mkdir()
    (valid_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": "my_plugin",
                "version": "1.2.0",
                "description": "A great plugin",
                "skills": ["skills/*.md"],
                "tools": ["tools/*.py"],
            }
        )
    )
    manifest = plugins.load_manifest(valid_dir)
    assert manifest is not None
    assert manifest.name == "my_plugin"
    assert manifest.version == "1.2.0"
    assert manifest.description == "A great plugin"
    assert manifest.skills == ("skills/*.md",)
    assert manifest.tools == ("tools/*.py",)

    # Name mismatch
    mismatch_dir = tmp_path / "dir_name"
    mismatch_dir.mkdir()
    (mismatch_dir / "manifest.json").write_text(
        json.dumps({"name": "different_name", "version": "1.0.0"})
    )
    assert plugins.load_manifest(mismatch_dir) is None


@pytest.mark.asyncio
async def test_load_plugins_and_lifecycle(tmp_path: Path):
    demo_script = Path(__file__).parent.parent / "scripts" / "mcp_demo_server.py"
    assert demo_script.exists()

    # Setup a fixture plugin in tmp_path with 1 tool, 1 skill, and 1 MCP server
    plugin_dir = tmp_path / "sample"
    plugin_dir.mkdir()
    skills_dir = plugin_dir / "skills"
    skills_dir.mkdir()
    tools_dir = plugin_dir / "tools"
    tools_dir.mkdir()

    (plugin_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": "sample",
                "version": "0.1.0",
                "description": "Sample plugin for test",
                "skills": ["skills/*.md"],
                "tools": ["tools/*.py"],
                "mcp_servers": [
                    {
                        "name": "sub",
                        "transport": "stdio",
                        "command": [sys.executable, str(demo_script)],
                    }
                ],
            }
        )
    )
    (skills_dir / "sample-skill.md").write_text(
        "---\nname: sample-skill\ndescription: sample\nwhen_to_use: sample\n---\nSample skill body\n"
    )
    (tools_dir / "sample_tool.py").write_text(
        "from app.tools.registry import ToolSpec, register\n"
        "async def _tool_fn(): return 'sample output'\n"
        "register(ToolSpec(name='sample_tool_fn', description='sample', parameters={'type': 'object'}, fn=_tool_fn, always_visible=False))\n"
    )
    # 1. Load plugins
    await plugins.load_plugins(tmp_path)

    # Tool registered
    tool = get_tool("sample_tool_fn")
    assert tool is not None
    assert await tool.fn() == "sample output"

    # Skill registered under namespace 'sample.sample-skill'
    skill = skills.get_skill("sample.sample-skill")
    assert skill is not None
    assert "Sample skill body" in skill.content

    # Embedded MCP server tools and auto-skill registered
    mcp_echo = get_tool("mcp_sample_sub_echo")
    assert mcp_echo is not None
    assert await mcp_echo.fn(text="plugin mcp test") == "plugin mcp test"
    mcp_skill = skills.get_skill("mcp-sample_sub")
    assert mcp_skill is not None
    list_tool = get_tool("list_plugins")
    assert list_tool is not None
    res = await list_tool.fn()
    plugin_list = json.loads(res)
    assert len(plugin_list) == 1
    assert plugin_list[0]["name"] == "sample"
    assert plugin_list[0]["enabled"] is True
    assert plugin_list[0]["tools_count"] == 1
    assert plugin_list[0]["skills_count"] == 1

    # 2. Disable plugin
    disable_tool = get_tool("disable_plugin")
    assert disable_tool is not None
    dis_res = await disable_tool.fn(name="sample")
    assert "disabled" in dis_res

    # Tool and skill should now be gone
    # Tool, skill, and MCP tools should now be gone
    assert get_tool("sample_tool_fn") is None
    assert skills.get_skill("sample.sample-skill") is None
    assert get_tool("mcp_sample_sub_echo") is None
    assert skills.get_skill("mcp-sample_sub") is None

    # 3. Enable plugin
    enable_tool = get_tool("enable_plugin")
    assert enable_tool is not None
    en_res = await enable_tool.fn(name="sample")
    assert "enabled" in en_res

    # Tool, skill, and MCP tools should be back
    assert get_tool("sample_tool_fn") is not None
    assert skills.get_skill("sample.sample-skill") is not None
    assert get_tool("mcp_sample_sub_echo") is not None
    assert skills.get_skill("mcp-sample_sub") is not None
