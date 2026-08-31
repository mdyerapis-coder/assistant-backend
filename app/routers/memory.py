"""GET/PATCH /v1/memory — inspect and edit tier-1 facts (phase 05).

The model's remember()/forget() tools remain the primary write path
during chats; this router exists so the human can audit and correct what
has been stored (including auto-extracted facts — see app/extraction.py)
without talking to the model. Contract: docs/CONTRACT.md.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import memory
from ..auth import require_bearer_token

router = APIRouter(dependencies=[Depends(require_bearer_token)])


class MemoryPatchRequest(BaseModel):
    # value null = delete the key; otherwise upsert via memory.remember,
    # which enforces the size cap and reports rejections in the response.
    facts: dict[str, str | None]


@router.get("/v1/memory")
async def get_memory() -> dict:
    return {"facts": await memory.list_facts()}


@router.patch("/v1/memory")
async def patch_memory(request: MemoryPatchRequest) -> dict:
    rejected: list[dict] = []
    for key, value in request.facts.items():
        if value is None:
            await memory.forget(key)
            continue
        result = await memory.remember(key, value)
        if not result.startswith("Remembered"):
            rejected.append({"key": key, "reason": result})
    return {"facts": await memory.list_facts(), "rejected": rejected}
