"""GET /v1/threads + GET /v1/threads/{id}/messages — phase 05.

Read-only views over the conversations/messages tables the chat loop has
populated since phase 01 — the server is the source of truth for history;
the phone (assistant-android phase 08) caches these responses into Room
and never treats local rows as authoritative. Contract: docs/CONTRACT.md
(REST section) — if this file and that doc disagree, that's a bug; fix
both in the same commit.
"""

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..auth import require_bearer_token

router = APIRouter(dependencies=[Depends(require_bearer_token)])

TITLE_MAX_CHARS = 80
PREVIEW_MAX_CHARS = 140


def _truncate(text: str | None, limit: int, fallback: str) -> str:
    text = (text or "").strip()
    if not text:
        return fallback
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


@router.get("/v1/threads")
async def list_threads() -> dict:
    conn = db.get_connection()
    async with conn.execute(
        """
        SELECT c.id,
               c.created_at,
               (SELECT m.content FROM messages m
                  WHERE m.conversation_id = c.id AND m.role = 'user'
                  ORDER BY m.id LIMIT 1) AS title,
               (SELECT m.content FROM messages m
                  WHERE m.conversation_id = c.id
                    AND m.role IN ('user', 'assistant')
                    AND m.content IS NOT NULL AND m.content != ''
                  ORDER BY m.id DESC LIMIT 1) AS preview,
               (SELECT COUNT(*) FROM messages m
                  WHERE m.conversation_id = c.id) AS message_count,
               (SELECT MAX(m.created_at) FROM messages m
                  WHERE m.conversation_id = c.id) AS last_message_at
        FROM conversations c
        WHERE EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id)
        ORDER BY last_message_at DESC
        """
    ) as cursor:
        rows = await cursor.fetchall()
    return {
        "threads": [
            {
                "id": row[0],
                "title": _truncate(row[2], TITLE_MAX_CHARS, "Untitled"),
                "preview": _truncate(row[3], PREVIEW_MAX_CHARS, ""),
                "created_at": row[1],
                "last_message_at": row[5],
                "message_count": row[4],
            }
            for row in rows
        ]
    }


@router.get("/v1/threads/{thread_id}/messages")
async def list_thread_messages(thread_id: str) -> dict:
    conn = db.get_connection()
    async with conn.execute(
        "SELECT id FROM conversations WHERE id = ?", (thread_id,)
    ) as cursor:
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="unknown thread")

    async with conn.execute(
        "SELECT id, role, content, created_at FROM messages "
        "WHERE conversation_id = ? AND role IN ('user', 'assistant') "
        "AND content IS NOT NULL AND content != '' ORDER BY id",
        (thread_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return {
        "thread_id": thread_id,
        "messages": [
            {
                "id": row[0],
                "role": row[1],
                "content": row[2],
                "created_at": row[3],
            }
            for row in rows
        ],
    }
