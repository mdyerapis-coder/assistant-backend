import json
import os
from pathlib import Path

os.environ.setdefault("ASSISTANT_BEARER_TOKEN", "test-token")
os.environ.setdefault("ASSISTANT_DB_PATH", ":memory:")

import pytest

from app import db, skills
from app.tools import skills_tools
from app.tools.registry import always_visible_tools, get_tool


@pytest.fixture(autouse=True)
async def _db(tmp_path: Path):
    await db.connect()
    skills.clear_overlay()
    # Point skills at tmp_path for clean isolation per test
    skills.load_skills(tmp_path)
    yield
    skills.clear_overlay()
    await db.disconnect()

def test_skills_tools_registered():
    visible = {t.name for t in always_visible_tools()}
    assert {"list_skills", "use_skill", "create_skill", "update_skill"} <= visible


def test_load_morning_brief_skill():
    repo_skills = Path(__file__).parent.parent / "skills"
    loaded = skills.load_skills(repo_skills)
    mb = skills.get_skill("morning-brief")
    assert mb is not None
    assert mb.name == "morning-brief"
    assert "calendar" in mb.description.lower()
    assert mb.tools == ("list_todays_calendar", "list_unread_emails")
    assert mb.revision == 1
    assert "Summarize today's calendar" in mb.content


def test_load_skills_skips_invalid_files(tmp_path: Path):
    valid = tmp_path / "valid.md"
    valid.write_text(
        "---\nname: valid-one\ndescription: test\nwhen_to_use: test\n---\nbody\n"
    )
    invalid = tmp_path / "invalid.md"
    invalid.write_text("No frontmatter at all here.")
    bad_yaml = tmp_path / "bad.md"
    bad_yaml.write_text("---\n[invalid yaml: \n---\nbody\n")

    loaded = skills.load_skills(tmp_path)
    assert len(loaded) == 1
    assert loaded[0].name == "valid-one"


def test_save_skill_creates_history_and_increments_revision(tmp_path: Path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    skill_file = skills_dir / "my-skill.md"
    skill_file.write_text(
        "---\nname: my-skill\ndescription: d\nwhen_to_use: w\ntools: [list_reminders]\nrevision: 1\n---\nold body\n"
    )
    skills.load_skills(skills_dir)
    original = skills.get_skill("my-skill")
    assert original is not None
    assert original.revision == 1

    updated = skills.save_skill(original, "new body content")
    assert updated.revision == 2
    assert updated.content == "new body content"

    # Verify history snapshot
    history_file = skills_dir / ".history" / "my-skill-r1.md"
    assert history_file.exists()
    assert "old body" in history_file.read_text()


@pytest.mark.asyncio
async def test_list_and_use_skill_flow(tmp_path: Path):
    skill_file = tmp_path / "test-skill.md"
    skill_file.write_text(
        "---\nname: test-skill\ndescription: do a thing\nwhen_to_use: when asked\n---\nStep 1: relax\n"
    )
    skills.load_skills(tmp_path)

    # list_skills should return 0 activations initially
    list_tool = get_tool("list_skills")
    assert list_tool is not None
    listed_json = await list_tool.fn()
    items = json.loads(listed_json)
    assert len(items) == 1
    assert items[0]["name"] == "test-skill"
    assert items[0]["activations"] == 0

    # use_skill returns content and records activation
    use_tool = get_tool("use_skill")
    assert use_tool is not None
    content = await use_tool.fn(name="test-skill")
    assert content == "Step 1: relax"

    # activations should now be 1
    listed_json2 = await list_tool.fn()
    items2 = json.loads(listed_json2)
    assert items2[0]["activations"] == 1


@pytest.mark.asyncio
async def test_use_unknown_skill_returns_error_string():
    use_tool = get_tool("use_skill")
    assert use_tool is not None
    res = await use_tool.fn(name="nonexistent")
    assert "Error: unknown skill 'nonexistent'" in res


@pytest.mark.asyncio
async def test_create_and_update_skill_tools(tmp_path: Path):
    skills.load_skills(tmp_path)
    create_tool = get_tool("create_skill")
    assert create_tool is not None

    res = await create_tool.fn(
        name="coffee-procedure",
        description="Make a flat white",
        when_to_use="When user asks for coffee",
        content="1. Pull double espresso\n2. Steam milk\n3. Pour",
        reason="User explained coffee steps",
    )
    assert "Created skill coffee-procedure" in res
    assert (tmp_path / "coffee-procedure.md").exists()

    # Skill should now be loaded in memory
    created = skills.get_skill("coffee-procedure")
    assert created is not None
    assert created.revision == 1
    assert "espresso" in created.content

    # update_skill
    update_tool = get_tool("update_skill")
    assert update_tool is not None
    up_res = await update_tool.fn(
        name="coffee-procedure",
        content="1. Pull double espresso\n2. Steam oat milk\n3. Pour with latte art",
    )
    assert "Updated skill coffee-procedure to revision 2" in up_res
    updated = skills.get_skill("coffee-procedure")
    assert updated is not None
    assert updated.revision == 2
    assert "oat milk" in updated.content


@pytest.mark.asyncio
async def test_create_skill_validates_name_and_content():
    create_tool = get_tool("create_skill")
    assert create_tool is not None

    # Invalid name (uppercase, special chars)
    res_bad_name = await create_tool.fn(
        name="Bad_Name!",
        description="desc",
        when_to_use="when",
        content="content",
    )
    assert "Error: invalid skill name" in res_bad_name

    # Content too long
    res_long = await create_tool.fn(
        name="valid-name",
        description="desc",
        when_to_use="when",
        content="x" * 20_000,
    )
    assert "Error: content too long" in res_long
