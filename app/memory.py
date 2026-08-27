"""Tier-1 (user_facts) and tier-2 (message search) memory.

See docs/adr/008-two-tier-memory.md. Tier 1 is small, size-capped, and
loaded once per request into the system prompt — never fetched
mid-conversation, which is what preserves prompt-cache stability. A write
past the cap fails loudly and asks the model to consolidate/replace an
existing key, rather than silently auto-summarizing — that would hide the
wrong kind of failure. Tier 2 is plain SQLite text search over the existing
`messages` table — no vector DB in v1, see docs/adr/010-no-vector-db-in-v1.md.

Deliberately framework-free (no OpenAI schema, no FastAPI) — the tool
wrapping around these functions lives in app/tools/memory_tools.py so this
module stays testable on its own.
"""

import datetime

from . import db

# Mirrors Hermes's ~800-token budget, approximated in characters (~4
# chars/token) since nothing here tokenizes for real.
MAX_FACTS_CHARS = 3200


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


async def get_all_facts() -> dict[str, str]:
    conn = db.get_connection()
    async with conn.execute("SELECT key, value FROM user_facts ORDER BY key") as cursor:
        rows = await cursor.fetchall()
    return {key: value for key, value in rows}


def render_facts_block(facts: dict[str, str]) -> str:
    if not facts:
        return ""
    lines = "\n".join(f"- {key}: {value}" for key, value in facts.items())
    return f"\n\nWhat you know about the user (from remember()):\n{lines}"


async def remember(key: str, value: str) -> str:
    facts = await get_all_facts()
    existing_size = len(key) + len(facts.get(key, ""))
    current_size = sum(len(k) + len(v) for k, v in facts.items())
    new_size = current_size - existing_size + len(key) + len(value)

    if new_size > MAX_FACTS_CHARS and key not in facts:
        return (
            f"Cannot add '{key}' — memory is at its {MAX_FACTS_CHARS}-character "
            "cap. Consolidate or forget an existing fact first, then try again."
        )

    conn = db.get_connection()
    await conn.execute(
        "INSERT INTO user_facts (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
        "updated_at = excluded.updated_at",
        (key, value, _now()),
    )
    await conn.commit()
    return f"Remembered: {key} = {value}"


async def forget(key: str) -> str:
    conn = db.get_connection()
    cursor = await conn.execute("DELETE FROM user_facts WHERE key = ?", (key,))
    await conn.commit()
    if cursor.rowcount == 0:
        return f"No fact named '{key}' was stored."
    return f"Forgot: {key}"


async def search_past_conversations(query: str, limit: int = 10) -> list[dict]:
    conn = db.get_connection()
    like = f"%{query}%"
    async with conn.execute(
        "SELECT conversation_id, role, content, created_at FROM messages "
        "WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?",
        (like, limit),
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {"conversation_id": r[0], "role": r[1], "content": r[2], "created_at": r[3]}
        for r in rows
    ]
