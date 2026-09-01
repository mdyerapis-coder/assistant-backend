"""Thin wrapper around the OpenAI SDK's async client.

Points at app/providers.py's "minimax" entry, not Cline's gateway (the
original plan) — Cline's account has a negative credit balance as of
2026-08-27 (confirmed by hitting api.cline.bot directly: every model
returns insufficient_credits or model-not-found), so this backend is
unusable until that's topped up. See
phases/01_chat-loop/REPORT.md. Swapping the active provider is just
changing _ACTIVE_PROVIDER_NAME below until real per-request provider
selection is built (that's still a later concern than proving the loop
works — see app/providers.py's module docstring).
"""

import os
from dataclasses import dataclass

from openai import AsyncOpenAI

from . import providers


@dataclass(frozen=True, slots=True)
class ModelRuntime:
    client: AsyncOpenAI
    model: str
    extra_body: dict[str, object]

_ACTIVE_PROVIDER_NAME = "ollama"
_active = providers.get_provider(_ACTIVE_PROVIDER_NAME)

if _active is not None:
    _default_model = _active.default_model
    _api_key = os.environ[_active.api_key_env]
    _base_url = _active.base_url
    # MiniMax-specific: its OpenAI-compatible endpoint defaults to inlining
    # <think>...</think> chain-of-thought straight into `content` (confirmed
    # live 2026-08-27 — leaks into the SSE delta stream otherwise, which
    # docs/CONTRACT.md has no event type for). Disabling it outright is
    # simpler than adding a reasoning-content event just for one provider;
    # revisit if/when real per-provider config lands.
    _default_extra_body: dict[str, object] = (
        {"thinking": {"type": "disabled"}} if _ACTIVE_PROVIDER_NAME == "minimax" else {}
    )
else:
    # dev/test fallback: no real provider key set in this environment (e.g.
    # local pytest runs). Every call site here either monkeypatches
    # `create` directly or never reaches the network, so this placeholder
    # value itself is never actually used — it only needs to let the SDK
    # construct without erroring (it now refuses an empty-string key).
    _default_model = "unset"
    _api_key = "unset"
    _base_url = None
    _default_extra_body = {}

client = AsyncOpenAI(api_key=_api_key, base_url=_base_url)
DEFAULT_MODEL = _default_model
EXTRA_BODY = _default_extra_body


def _extra_body(provider: providers.ModelProvider) -> dict[str, object]:
    return {"thinking": {"type": "disabled"}} if provider.name == "minimax" else {}


def default_model_id() -> str | None:
    configured = providers.selectable_providers()
    if any(provider.name == _ACTIVE_PROVIDER_NAME for provider in configured):
        return _ACTIVE_PROVIDER_NAME
    return configured[0].name if configured else None


def resolve_model(model_id: str | None) -> ModelRuntime | None:
    if model_id is None:
        return ModelRuntime(client=client, model=DEFAULT_MODEL, extra_body=EXTRA_BODY)

    # Qualified form "provider:model" — used for live-expanded catalog entries
    # so the exact model choice survives the provider lookup.
    if ":" in model_id:
        provider_name, actual_model = model_id.split(":", 1)
        provider = providers.get_provider(provider_name)
        if provider is None or not provider.selectable:
            return None
        selected_client = (
            client
            if _active is not None and provider.name == _active.name
            else AsyncOpenAI(
                api_key=os.environ.get(provider.api_key_env, "ollama"),
                base_url=provider.base_url,
            )
        )
        return ModelRuntime(
            client=selected_client,
            model=actual_model,
            extra_body=_extra_body(provider),
        )

    # Legacy / single-model path: model_id is a provider name
    provider = providers.get_provider(model_id)
    if provider is None or not provider.selectable:
        # Fallback: maybe the raw model id was sent without provider prefix
        # (e.g. from an older client). Search live catalogs for it.
        for cand in providers.selectable_providers():
            # Check static default first
            if cand.default_model == model_id:
                provider = cand
                break
            # Check live cache if available (populated after /v1/models)
            cached = providers._live_cache.get(cand.name)
            if cached and model_id in cached[1]:
                provider = cand
                break
        if provider is None:
            return None

    selected_client = (
        client
        if _active is not None and provider.name == _active.name
        else AsyncOpenAI(
            api_key=os.environ.get(provider.api_key_env, "ollama"),
            base_url=provider.base_url,
        )
    )
    # Raw live model id vs. provider-name legacy: use the id directly unless
    # the caller sent the provider name itself (legacy), then use default.
    model = provider.default_model if model_id == provider.name else model_id
    return ModelRuntime(
        client=selected_client,
        model=model,
        extra_body=_extra_body(provider),
    )
