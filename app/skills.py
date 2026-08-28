"""Skill loading and saving — skills are markdown files with YAML frontmatter.

Deliberately framework-free (mirrors app/memory.py): the tool wrapping
around these functions lives in app/tools/skills_tools.py so this module
stays testable on its own.

Skill file format:

    ---
    name: morning-brief
    description: ...
    when_to_use: ...
    tools: ["list_todays_calendar", "list_unread_emails"]
    revision: 1
    ---
    # Instructions (markdown body)

`revision` and `tools` are optional (defaults 1 and ()). The body after the
frontmatter is the skill content. A skill with `namespace="<plugin>"` gets
name `f"{plugin}.{skillname}"` — used by the plugin loader (Phase 06).

The skills directory is the source of truth. Runtime writes (create/update
via the model) happen here; `.history/` keeps prior revisions.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 16_000
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MAX_NAME_LEN = 48
HISTORY_KEEP = 20

SKILLS: list["Skill"] = []
_SKILL_MAP: dict[str, "Skill"] = {}
_history_dir: Path | None = None
SKILLS_DIR: Path | None = None  # set by load_skills; where new skills get written
_OVERLAY: list["Skill"] = []  # in-memory skills (MCP auto-skills); path is None


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    when_to_use: str
    content: str
    tools: tuple[str, ...] = ()
    revision: int = 1
    path: Path | None = None


def _parse_skill_file(path: Path, namespace: str | None) -> Skill | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        logger.warning("skill %s: missing frontmatter, skipped", path.name)
        return None
    raw_parts = text.split("---", 2)
    if len(raw_parts) < 3:
        logger.warning("skill %s: malformed frontmatter, skipped", path.name)
        return None
    frontmatter = raw_parts[1]
    body = raw_parts[2].strip()
    try:
        meta = yaml.safe_load(frontmatter)
    except yaml.YAMLError:
        logger.warning("skill %s: invalid frontmatter YAML, skipped", path.name)
        return None
    if not isinstance(meta, dict):
        logger.warning("skill %s: frontmatter is not a mapping, skipped", path.name)
        return None
    name = str(meta.get("name", path.stem)).strip()
    if namespace:
        name = f"{namespace}.{name}"
    description = str(meta.get("description", "")).strip()
    when_to_use = str(meta.get("when_to_use", "")).strip()
    tools = meta.get("tools", [])
    if not isinstance(tools, list):
        logger.warning("skill %s: tools is not a list, using default", path.name)
        tools = []
    tools_tuple = tuple(str(t).strip() for t in tools if str(t).strip())
    try:
        revision = int(meta.get("revision", 1))
    except (TypeError, ValueError):
        revision = 1
    return Skill(
        name=name,
        description=description,
        when_to_use=when_to_use,
        content=body,
        tools=tools_tuple,
        revision=revision,
        path=path,
    )


def _reindex() -> None:
    global SKILLS, _SKILL_MAP
    merged = {s.name: s for s in SKILLS}
    for skill in _OVERLAY:
        merged[skill.name] = skill
    SKILLS = list(merged.values())
    _SKILL_MAP = merged


def load_skills(skills_dir: Path, namespace: str | None = None) -> list[Skill]:
    """Replace the in-memory index with the skills found in `skills_dir`.

    Files with missing/invalid frontmatter are skipped with a warning —
    a broken skill file must never crash startup. In-memory overlay skills
    (MCP auto-skills, path=None) survive the reload.
    """
    global SKILLS_DIR
    SKILLS_DIR = skills_dir
    loaded: list[Skill] = []
    if skills_dir.is_dir():
        for path in sorted(skills_dir.glob("*.md")):
            skill = _parse_skill_file(path, namespace)
            if skill is not None:
                loaded.append(skill)
            else:
                logger.warning("skill %s skipped", path.name)
    else:
        logger.warning("skills dir not found: %s", skills_dir)
    global SKILLS
    SKILLS = loaded
    _reindex()
    return SKILLS


def merge_skills(skills_dir: Path, namespace: str) -> list[Skill]:
    """Upsert skills from `skills_dir` under `namespace` into the index.

    Unlike load_skills this does not replace existing entries — used by the
    plugin loader so a plugin's skills coexist with core + other plugins.
    """
    global SKILLS
    new_skills = [
        s
        for path in sorted(skills_dir.glob("*.md"))
        if (s := _parse_skill_file(path, namespace)) is not None
    ]
    names = {s.name for s in new_skills}
    SKILLS = [s for s in SKILLS if s.name not in names] + new_skills
    _reindex()
    return new_skills


def install_skill(skill: Skill) -> None:
    """Register an in-memory skill (path=None) that must survive reloads."""
    global _OVERLAY
    _OVERLAY = [s for s in _OVERLAY if s.name != skill.name] + [skill]
    _reindex()


def uninstall_skills(name_prefix: str) -> None:
    """Remove core+overlay skills whose name starts with `name_prefix`."""
    global SKILLS, _OVERLAY
    SKILLS = [s for s in SKILLS if not s.name.startswith(name_prefix)]
    _OVERLAY = [s for s in _OVERLAY if not s.name.startswith(name_prefix)]
    _reindex()


def clear_overlay() -> None:
    """Clear all in-memory overlay skills."""
    global _OVERLAY
    _OVERLAY.clear()
    _reindex()


def get_skill(name: str) -> Skill | None:
    return _SKILL_MAP.get(name)


def all_skills() -> list[Skill]:
    return list(SKILLS)


def _default_history_dir(skill_path: Path) -> Path:
    global _history_dir
    if _history_dir is None:
        _history_dir = skill_path.parent / ".history"
    return _history_dir


def save_skill(skill: Skill, new_content: str) -> Skill:
    """Atomic rewrite of a skill with revision+1; old revision snapshotted.

    The caller is responsible for updating the in-memory index (via
    `load_skills` or direct _SKILL_MAP assignment) — this function only
    writes the file system.
    """
    if skill.path is None:
        raise ValueError(f"skill {skill.name!r} has no file path (cannot save)")
    old = skill.revision
    new = replace(skill, content=new_content, revision=old + 1)

    history = _default_history_dir(skill.path)
    history.mkdir(parents=True, exist_ok=True)
    snapshot = history / f"{skill.name}-r{old}.md"
    snapshot.write_text(skill.path.read_text(encoding="utf-8"), encoding="utf-8")

    meta: dict[str, object] = {
        "name": new.name,
        "description": new.description,
        "when_to_use": new.when_to_use,
        "tools": list(new.tools),
        "revision": new.revision,
    }
    frontmatter = "---\n" + yaml.safe_dump(meta, sort_keys=False) + "---\n"
    content = frontmatter + new.content.strip() + "\n"

    tmp = skill.path.with_name(skill.path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, skill.path)

    _prune_history(history)
    return new


def _prune_history(history_dir: Path) -> None:
    files = sorted(history_dir.glob("*.md"), key=lambda p: p.stat().st_mtime)
    excess = len(files) - HISTORY_KEEP
    for stale in files[:excess]:
        try:
            stale.unlink()
        except OSError:
            logger.warning("could not prune history file %s", stale)
