from app.tools import memory_tools  # noqa: F401  registers the memory tools
from app.tools.registry import always_visible_tools, get_tool, openai_tool_defs


def test_memory_tools_registered_and_visible():
    names = {t.name for t in always_visible_tools()}
    assert {"remember", "forget", "search_past_conversations"} <= names


def test_get_tool_returns_none_for_unknown_name():
    assert get_tool("does_not_exist") is None


def test_get_tool_returns_matching_spec():
    spec = get_tool("remember")
    assert spec is not None
    assert spec.name == "remember"


def test_openai_tool_defs_shape():
    defs = openai_tool_defs(always_visible_tools())
    remember_def = next(d for d in defs if d["function"]["name"] == "remember")
    assert remember_def["type"] == "function"
    assert "key" in remember_def["function"]["parameters"]["properties"]
    assert "value" in remember_def["function"]["parameters"]["properties"]
