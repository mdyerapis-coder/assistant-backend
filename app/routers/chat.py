"""POST /v1/chat — the whole chat loop in one place: OpenAI streaming call,
tool-execution loop, SSE encoding, SQLite persistence. See docs/CONTRACT.md
for the wire format this streams (owning source: app/sse.py) and
docs/adr/008/009 for the memory/tool-registry design wired in here.
"""

import datetime
import json
import uuid
from typing import AsyncIterator, cast, TypedDict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolUnionParam
from pydantic import BaseModel, ConfigDict

from .. import db, extraction, memory, openai_client, patterns, providers, skills
from ..auth import require_bearer_token
from ..sse import DONE, encode_event
from ..tools import memory_tools  # noqa: F401  ensures tools are registered
from ..tools import plugin_tools  # noqa: F401  ensures plugin tools are registered
from ..tools import skills_tools  # noqa: F401  ensures skill tools are registered
from ..tools import registry

router = APIRouter()

SYSTEM_PROMPT_BASE = (
    "You are a personal assistant living on the user's phone. Be concise. "
    "Use the remember/forget tools to track durable facts about the user "
    "across conversations, and search_past_conversations when they "
    "reference something you don't have in front of you. Skills you create "
    "or update succeed only after the frontmatter is valid. When the user "
    "repeats a workflow 3+ times, call create_skill to learn it as a skill; "
    "when the user corrects a procedure, update_skill the affected skill."
)


class ChatRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    conversation_id: str | None = None
    message: str
    model: str | None = None


class ModelOptionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    model: str
    provider: str
    description: str


class ModelsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    default_model_id: str | None
    models: list[ModelOptionResponse]


class ToolCallAccumulator(TypedDict):
    id: str | None
    name: str | None
    arguments: list[str]


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


async def _load_history(conversation_id: str) -> list[dict[str, object]]:
    conn = db.get_connection()
    async with conn.execute(
        "SELECT role, content, tool_calls_json, tool_call_id, name FROM messages "
        "WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    messages: list[dict[str, object]] = []
    for role, content, tool_calls_json, tool_call_id, name in rows:
        msg: dict[str, object] = {"role": role, "content": content}
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
    tool_calls: list[dict[str, object]] | None = None,
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


async def _run_turn(
    conversation_id: str, runtime: openai_client.ModelRuntime
) -> AsyncIterator[str]:
    facts = await memory.get_all_facts()
    system_prompt = SYSTEM_PROMPT_BASE + memory.render_facts_block(facts)
    pattern_notice = await patterns.pending_nudge_notice()
    if pattern_notice:
        system_prompt += "\n\n" + pattern_notice
    history = await _load_history(conversation_id)
    messages = list(history)
    messages.insert(0, {"role": "system", "content": system_prompt})

    activated: set[str] = set()

    while True:
        active_specs = [
            s
            for n in sorted(activated)
            if (s := registry.get_tool(n)) is not None
        ]
        tool_defs = registry.openai_tool_defs(
            registry.always_visible_tools() + active_specs
        )
        stream = await runtime.client.chat.completions.create(
            model=runtime.model,
            messages=cast(list[ChatCompletionMessageParam], messages),
            tools=cast(list[ChatCompletionToolUnionParam], tool_defs),
            stream=True,
            extra_body=runtime.extra_body,
        )

        content_parts: list[str] = []
        tool_call_accum: dict[int, ToolCallAccumulator] = {}

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
                        tc.index, {"id": None, "name": None, "arguments": []}  # type: ignore[typeddict-item]
                    )
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"].append(tc.function.arguments)

        assistant_content = "".join(content_parts) or None

        if not tool_call_accum:
            await _save_message(conversation_id, "assistant", assistant_content)
            break

        ordered = [tool_call_accum[i] for i in sorted(tool_call_accum)]
        openai_tool_calls_payload: list[dict[str, object]] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": "".join(tc["arguments"])},
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
            args_json = "".join(tc["arguments"]) or "{}"
            yield encode_event(
                {
                    "type": "tool_call_started",
                    "conversation_id": conversation_id,
                    "id": tc["id"],
                    "name": tc["name"],
                    "args_json": args_json,
                }
            )

            tool_name = tc["name"]
            tool_spec = registry.get_tool(tool_name) if tool_name is not None else None
            if tool_spec is None:
                result = f"Unknown tool: {tool_name}"
                ok = False
            else:
                try:
                    kwargs = json.loads(args_json) if args_json else {}
                    result = await tool_spec.fn(**kwargs)
                    ok = True
                except Exception as exc:  # a broken tool call must not kill the turn
                    result = f"Tool '{tool_name}' failed: {exc}"
                    ok = False
                    kwargs = {}

            if ok:
                try:
                    await patterns.record_pattern(tool_name, kwargs)
                except Exception:
                    pass
                if tool_name in {"use_skill", "create_skill", "update_skill"}:
                    skill_name = kwargs.get("name")
                    if isinstance(skill_name, str):
                        skill_obj = skills.get_skill(skill_name)
                        if skill_obj is not None:
                            for t in skill_obj.tools:
                                if registry.get_tool(t) is not None:
                                    activated.add(t)
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
                conversation_id, "tool", result, tool_call_id=tc["id"], name=tool_name
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
    runtime = openai_client.resolve_model(request.model)
    if runtime is None:
        raise HTTPException(status_code=422, detail="Selected model is unavailable")

    conversation_id = await _ensure_conversation(request.conversation_id)
    await _save_message(conversation_id, "user", request.message)

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for frame in _run_turn(conversation_id, runtime):
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
            return
        # Turn completed cleanly — opportunistically extract durable facts
        # from this exchange in the background (phase 05). Never blocks the
        # stream; failures are logged inside the task, never surfaced.
        extraction.schedule(conversation_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get(
    "/v1/models",
    dependencies=[Depends(require_bearer_token)],
    response_model=ModelsResponse,
)
async def models() -> ModelsResponse:
    return ModelsResponse(
        default_model_id=openai_client.default_model_id(),
        models=[
            ModelOptionResponse(
                id=provider.name,
                model=provider.default_model,
                provider=provider.name,
                description=provider.note,
            )
            for provider in providers.selectable_providers()
        ],
    )
