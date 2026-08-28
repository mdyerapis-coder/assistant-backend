"""list_skills / use_skill / create_skill / update_skill — the model's
interface to app/skills.py, wrapped as OpenAI-schema tools. Kept separate
from skills.py so that module stays framework-free and testable on its own.
"""

from __future__ import annotations

import datetime
import json
import re

import yaml

from .. import db, skills
from .registry import ToolSpec, register

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_NAME_LEN = 48
MAX_CONTENT_CHARS = skills.MAX_CONTENT_CHARS


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


async def _activations() -> dict[str, int]:
    conn = db.get_connection()
    async with conn.execute("SELECT name, activations FROM skill_usage") as cursor:
        rows = await cursor.fetchall()
    return {name: activations for name, activations in rows}


async def _list_skills() -> str:
    activations = await _activations()
    payload = [
        {
            "name": s.name,
            "description": s.description,
            "when_to_use": s.when_to_use,
            "revision": s.revision,
            "activations": activations.get(s.name, 0),
        }
        for s in skills.all_skills()
    ]
    return json.dumps(payload)


async def _use_skill(name: str) -> str:
    skill = skills.get_skill(name)
    if skill is None:
        names = ", ".join(s.name for s in skills.all_skills()) or "(none)"
        return f"Error: unknown skill '{name}'. Available skills: {names}"
    conn = db.get_connection()
    await conn.execute(
        "INSERT INTO skill_usage (name, activations, last_used_at) VALUES (?, 1, ?) "
        "ON CONFLICT(name) DO UPDATE SET activations = activations + 1, "
        "last_used_at = excluded.last_used_at",
        (skill.name, _now()),
    )
    await conn.commit()
    return skill.content


async def _create_skill(
    name: str,
    description: str = "",
    when_to_use: str = "",
    content: str = "",
    reason: str = "",
) -> str:
    if not _NAME_RE.match(name) or len(name) > MAX_NAME_LEN:
        return (
            f"Error: invalid skill name '{name}' — must match "
            f"[a-z0-9][a-z0-9-]* (max {MAX_NAME_LEN} chars)."
        )
    if len(content) > MAX_CONTENT_CHARS:
        return (
            f"Error: content too long ({len(content)} chars; "
            f"max {MAX_CONTENT_CHARS})."
        )
    if skills.get_skill(name) is not None:
        return f"Error: skill '{name}' already exists — use update_skill."
    skills_dir = skills.SKILLS_DIR
    if skills_dir is None:
        return "Error: skills directory not loaded — cannot create skill."
    path = skills_dir / f"{name}.md"
    meta: dict[str, object] = {
        "name": name,
        "description": description,
        "when_to_use": when_to_use,
        "tools": [],
        "revision": 1,
    }
    body = (
        "---\n"
        + yaml.safe_dump(meta, sort_keys=False)
        + "---\n"
        + content.strip()
        + "\n"
    )
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)
    skills.load_skills(skills_dir)  # refresh index so use_skill sees it now
    note = f" (reason: {reason})" if reason else ""
    return f"Created skill {name}{note}"


async def _update_skill(name: str, content: str) -> str:
    skill = skills.get_skill(name)
    if skill is None:
        return (
            f"Error: unknown skill '{name}' — create it first "
            "or use list_skills to see available skills."
        )
    if skill.path is None:
        return f"Error: skill '{name}' is read-only (built-in)."
    if len(content) > MAX_CONTENT_CHARS:
        return (
            f"Error: content too long ({len(content)} chars; "
            f"max {MAX_CONTENT_CHARS})."
        )
    updated = skills.save_skill(skill, content)
    skills.load_skills(skills.SKILLS_DIR)  # reload (overlay survives)
    return f"Updated skill {name} to revision {updated.revision}"


register(
    ToolSpec(
        name="list_skills",
        description=(
            "List all learned skills: name, description, when_to_use, "
            "revision, activation count. Use this to find which skill covers "
            "the user's request before calling use_skill."
        ),
        parameters={"type": "object", "properties": {}},
        fn=_list_skills,
    )
)

register(
    ToolSpec(
        name="use_skill",
        description=(
            "Load a skill's instructions by name. The skill may reference "
            "additional tools that become available after you load it."
        ),
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        fn=_use_skill,
    )
)

register(
    ToolSpec(
        name="create_skill",
        description=(
            "Learn a new skill: persist a reusable procedure (e.g. how to "
            "produce a morning brief) so future requests can use_skill it. "
            "Use when the user repeats a workflow 3+ times or describes a "
            "standing procedure. Name must match [a-z0-9][a-z0-9-]*."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "when_to_use": {"type": "string"},
                "content": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["name", "description", "when_to_use", "content"],
        },
        fn=_create_skill,
    )
)

register(
    ToolSpec(
        name="update_skill",
        description=(
            "Rewrite an existing skill's instructions with new content. "
            "Use when the user corrects an earlier procedure."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["name", "content"],
        },
        fn=_update_skill,
    )
)
