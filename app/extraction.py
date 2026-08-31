"""Post-turn auto-extraction of durable facts (phase 05).

Lives in its own module, not app/memory.py, because memory.py is
deliberately framework-free (no OpenAI schema, no FastAPI — see its
docstring) and stays that way: this module owns the model call, memory.py
stays pure storage.

Called by the chat router after every cleanly completed turn. Never raises
into the caller: a failed extraction is logged and dropped — it must never
break or delay a chat stream. Extraction is additive on top of the model's
own explicit remember()/forget() tool calls, which remain the primary
write path.
"""

import asyncio
import json
import logging
from typing import Any

from . import db, memory, openai_client

logger = logging.getLogger(__name__)

EXTRACTION_SYSTEM_PROMPT = (
    "You extract durable facts about the user from a single chat exchange. "
    "Durable means still true weeks from now: preferences, standing "
    "commitments, names of people/pets/things they care about, timezone, "
    "job details. NOT durable: the topic of this exchange, one-off "
    "requests, transient states, small talk. You will be shown the facts "
    "already known. Output ONLY a JSON object like "
    '{"facts": {"key": "value"}} containing facts that are new, or whose '
    "value has changed. Use short stable keys (e.g. 'timezone', "
    "'dog_name'). If there is nothing worth storing, output "
    '{"facts": {}}. Never restate an already-known fact with the same '
    "value."
)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort JSON object recovery — models sometimes wrap output in
    markdown fences or prose despite the prompt."""
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


async def extract_facts(user_message: str, assistant_message: str) -> dict[str, str]:
    """Ask the model which durable facts this exchange revealed.

    Returns {} on any failure — callers treat extraction as best-effort.
    """
    if not user_message.strip() or not assistant_message.strip():
        return {}

    known = await memory.get_all_facts()
    user_prompt = (
        f"Already-known facts: {json.dumps(known)}\n\n"
        f"User: {user_message}\n\nAssistant: {assistant_message}"
    )
    try:
        completion = await openai_client.client.chat.completions.create(
            model=openai_client.DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            extra_body=openai_client.EXTRA_BODY,
        )
    except Exception:
        logger.warning("fact extraction model call failed", exc_info=True)
        return {}

    raw = completion.choices[0].message.content or ""
    parsed = _extract_json_object(raw)
    if parsed is None:
        logger.info("fact extraction produced unparseable output: %r", raw[:200])
        return {}
    facts = parsed.get("facts")
    if not isinstance(facts, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in facts.items()
        if str(key).strip() and str(value).strip()
    }


async def extract_and_store(conversation_id: str) -> None:
    """Extract facts from the conversation's most recent exchange and
    store them via memory.remember (which enforces the size cap)."""
    conn = db.get_connection()
    async with conn.execute(
        "SELECT id, content FROM messages WHERE conversation_id = ? "
        "AND role = 'user' ORDER BY id DESC LIMIT 1",
        (conversation_id,),
    ) as cursor:
        last_user = await cursor.fetchone()
    if last_user is None:
        return
    user_id, user_content = last_user

    async with conn.execute(
        "SELECT content FROM messages WHERE conversation_id = ? "
        "AND role = 'assistant' AND content IS NOT NULL AND content != '' "
        "AND id > ? ORDER BY id DESC LIMIT 1",
        (conversation_id, user_id),
    ) as cursor:
        last_assistant = await cursor.fetchone()
    if last_assistant is None:
        return

    new_facts = await extract_facts(user_content, last_assistant[0])
    if not new_facts:
        return

    existing = await memory.get_all_facts()
    for key, value in new_facts.items():
        if existing.get(key) == value:
            continue
        result = await memory.remember(key, value)
        if not result.startswith("Remembered"):
            # e.g. size-cap rejection — fine, just log it
            logger.info("auto-extracted fact %r not stored: %s", key, result)
        else:
            logger.info("auto-extracted fact %r", key)


def schedule(conversation_id: str) -> None:
    """Fire-and-forget wrapper the chat router uses after a completed
    turn. Exceptions inside the task are logged, never propagated."""
    task = asyncio.create_task(extract_and_store(conversation_id))
    task.add_done_callback(_log_task_exception)


def _log_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("fact extraction task failed", exc_info=exc)
