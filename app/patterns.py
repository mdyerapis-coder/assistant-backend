"""Repeat-action learning: patterns of tool calls the user has repeated.

Everything done more than twice becomes a candidate skill. This module
records every successful tool call; when the same tool+args show up 3+
times, the model is nudged (in the next request's system prompt) to call
create_skill. Nudging stops after two ignored nudges per pattern.

Rows are pruned on startup: anything last seen more than 60 days ago is
dropped (personal-use volume).
"""

from __future__ import annotations

import datetime
import json

from . import db

PATTERN_THRESHOLD = 3
MAX_NUDGES = 2
MAX_ARGS_TEMPLATE = 512
PRUNE_DAYS = 60


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _args_template(args: dict) -> str:
    payload = json.dumps(args, sort_keys=True, separators=(",", ":"))
    return payload[:MAX_ARGS_TEMPLATE]


async def record_pattern(tool_name: str, args: dict) -> bool:
    """Upsert one execution; returns True exactly when count crosses 3."""
    template = _args_template(args)
    conn = db.get_connection()
    await conn.execute(
        "INSERT INTO action_patterns (name, args_template, count, first_at, last_at) "
        "VALUES (?, ?, 1, ?, ?) "
        "ON CONFLICT(name, args_template) DO UPDATE SET "
        "count = count + 1, last_at = excluded.last_at",
        (tool_name, template, _now(), _now()),
    )
    await conn.commit()
    cursor = await conn.execute(
        "SELECT count FROM action_patterns WHERE name = ? AND args_template = ?",
        (tool_name, template),
    )
    row = await cursor.fetchone()
    return row[0] == PATTERN_THRESHOLD


async def patterns_needing_nudge() -> list[tuple[str, str]]:
    """(name, args_template) of patterns at/above threshold with nudges left."""
    conn = db.get_connection()
    async with conn.execute(
        "SELECT name, args_template FROM action_patterns "
        "WHERE count >= ? AND nudge_count < ? "
        "ORDER BY count DESC, last_at DESC",
        (PATTERN_THRESHOLD, MAX_NUDGES),
    ) as cursor:
        rows = await cursor.fetchall()
    return [(row[0], row[1]) for row in rows]


async def bump_nudge(name: str, args_template: str) -> None:
    conn = db.get_connection()
    await conn.execute(
        "UPDATE action_patterns SET nudge_count = nudge_count + 1 "
        "WHERE name = ? AND args_template = ?",
        (name, args_template),
    )
    await conn.commit()


async def pending_nudge_notice() -> str:
    """System-prompt block for patterns due a nudge ("" when nothing due).
    Bumps each pattern's nudge_count as a side effect — one nudge per
    request, so two ignored nudges end the nudging for that pattern.
    """
    rows = await patterns_needing_nudge()
    if not rows:
        return ""
    lines = [
        f'Pattern notice: you have performed "{name}" with "{args_template}" '
        "3+ times."
        for name, args_template in rows
    ]
    lines.append(
        "If this is a recurring workflow, call create_skill to learn it as a skill."
    )
    for name, args_template in rows:
        await bump_nudge(name, args_template)
    return "\n".join(lines)


async def prune_old_patterns() -> None:
    conn = db.get_connection()
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=PRUNE_DAYS
    )
    await conn.execute("DELETE FROM action_patterns WHERE last_at < ?", (cutoff.isoformat(),))
    await conn.commit()
