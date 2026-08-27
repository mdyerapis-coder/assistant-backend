"""POST /v1/chat — the whole chat loop in one place: OpenAI streaming call,
tool-execution loop, SSE encoding, SQLite persistence. See docs/CONTRACT.md
for the wire format this streams (owning source: app/sse.py) and
docs/adr/008/009 for the memory/tool-registry design wired in here.
"""

import datetime
import json
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import db, memory, openai_client
from ..auth import require_bearer_token
from ..sse import DONE, encode_event
from ..tools import memory_tools  # noqa: F401  ensures tools are registered
from ..tools import registry

router = APIRouter()

SYSTEM_PROMPT_BASE = (
    "You are a personal assistant living on the user's phone. Be concise. "
    "Use the remember/forget tools to track durable facts about the user "
    "across conversations, and search_past_conversations when they "
    "reference something you don't have in front of you."
)


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


async def _ensure_conversation(conversation_id: str | None) -> str:
    conn = db.get_connection()
    if conversation_id is not None:
        async with conn.execute(
            "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
        ) as cursor:
            if await cursor.fetchone() is not None:
                return conversation_id
    new_id = conversation_id or str(uuid.uuid4())
    await conn.execute(
        "INSERT INTO conversations (id, created_at) VALUES (?, ?)", (new_id, _now())
    )
    await conn.commit()
    return new_id


async def _load_history(conversation_id: str) -> list[dict]:
    conn = db.get_connection()
    async with conn.execute(
        "SELECT role, content, tool_calls_json, tool_call_id, name FROM messages "
        "WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    messages: list[dict] = []
    for role, content, tool_calls_json, tool_call_id, name in rows:
        msg: dict = {"role": role, "content": content}
        if tool_calls_json:
            msg["tool_calls"] = json.loads(tool_calls_json)
        if tool_call_id:
            msg["tool_call_id"] = tool_call_id
        if name:
            msg["name"] = name
        messages.append(msg)
    return messages


async def _save_message(
    conversation_id: str,
    role: str,
    content: str | None,
    tool_calls: list[dict] | None = None,
    tool_call_id: str | None = None,
    name: str | None = None,
) -> None:
    conn = db.get_connection()
    await conn.execute(
        "INSERT INTO messages (conversation_id, role, content, tool_calls_json, "
        "tool_call_id, name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            conversation_id,
            role,
            content,
            json.dumps(tool_calls) if tool_calls else None,
            tool_call_id,
            name,
            _now(),
        ),
    )
    await conn.commit()


async def _run_turn(conversation_id: str) -> AsyncIterator[str]:
    facts = await memory.get_all_facts()
    system_prompt = SYSTEM_PROMPT_BASE + memory.render_facts_block(facts)
    history = await _load_history(conversation_id)
    messages: list[dict] = [{"role": "system", "content": system_prompt}] + history

    tool_defs = registry.openai_tool_defs(registry.always_visible_tools())

    while True:
        stream = await openai_client.client.chat.completions.create(
            model=openai_client.DEFAULT_MODEL,
            messages=messages,
            tools=tool_defs,
            stream=True,
            extra_body=openai_client.EXTRA_BODY,
        )

        content_parts: list[str] = []
        tool_call_accum: dict[int, dict] = {}

        async for chunk in stream:
            choice = chunk.choices[0]
            delta = choice.delta
            if delta.content:
                content_parts.append(delta.content)
                yield encode_event(
                    {
                        "type": "delta",
                        "conversation_id": conversation_id,
                        "content": delta.content,
                    }
                )
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    slot = tool_call_accum.setdefault(
                        tc.index, {"id": None, "name": None, "arguments": ""}
                    )
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments

        assistant_content = "".join(content_parts) or None

        if not tool_call_accum:
            await _save_message(conversation_id, "assistant", assistant_content)
            break

        ordered = [tool_call_accum[i] for i in sorted(tool_call_accum)]
        openai_tool_calls_payload = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"]},
            }
            for tc in ordered
        ]
        await _save_message(
            conversation_id,
            "assistant",
            assistant_content,
            tool_calls=openai_tool_calls_payload,
        )
        messages.append(
            {
                "role": "assistant",
                "content": assistant_content,
                "tool_calls": openai_tool_calls_payload,
            }
        )

        for tc in ordered:
            args_json = tc["arguments"] or "{}"
            yield encode_event(
                {
                    "type": "tool_call_started",
                    "conversation_id": conversation_id,
                    "id": tc["id"],
                    "name": tc["name"],
                    "args_json": args_json,
                }
            )

            tool_spec = registry.get_tool(tc["name"])
            if tool_spec is None:
                result = f"Unknown tool: {tc['name']}"
                ok = False
            else:
                try:
                    kwargs = json.loads(args_json) if args_json else {}
                    result = await tool_spec.fn(**kwargs)
                    ok = True
                except Exception as exc:  # a broken tool call must not kill the turn
                    result = f"Tool '{tc['name']}' failed: {exc}"
                    ok = False

            yield encode_event(
                {
                    "type": "tool_call_finished",
                    "conversation_id": conversation_id,
                    "id": tc["id"],
                    "ok": ok,
                    "summary": result[:200],
                }
            )

            await _save_message(
                conversation_id, "tool", result, tool_call_id=tc["id"], name=tc["name"]
            )
            messages.append(
                {"role": "tool", "tool_call_id": tc["id"], "content": result}
            )

        # loop again — feed the tool result(s) back for the model to continue

    message_id = str(uuid.uuid4())
    yield encode_event(
        {
            "type": "message_completed",
            "conversation_id": conversation_id,
            "message_id": message_id,
        }
    )
    yield DONE


@router.post("/v1/chat", dependencies=[Depends(require_bearer_token)])
async def chat(request: ChatRequest) -> StreamingResponse:
    conversation_id = await _ensure_conversation(request.conversation_id)
    await _save_message(conversation_id, "user", request.message)

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for frame in _run_turn(conversation_id):
                yield frame
        except Exception as exc:
            yield encode_event(
                {
                    "type": "error",
                    "conversation_id": conversation_id,
                    "message": str(exc),
                    "retryable": False,
                }
            )
            yield DONE

    return StreamingResponse(event_stream(), media_type="text/event-stream")
