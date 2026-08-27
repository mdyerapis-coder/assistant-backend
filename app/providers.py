"""Model provider registry — a flat, append-only list, Goose-style (see
docs/adr/009-tool-registry-and-progressive-disclosure.md — same philosophy
applied to model providers, not just tools).

Every provider is OpenAI-Chat-Completions-compatible (confirmed for each
before adding it here, not assumed), so the OpenAI SDK's own client works
against all of them via base_url + api_key — no per-provider client code.

Credentials load from env vars populated by
scripts/sync_secrets_from_bitwarden.sh (see docs/adr/011). A provider with
an unset env var simply won't appear in AVAILABLE_PROVIDERS — no crash, no
placeholder entry with an empty key.
"""

from dataclasses import dataclass

import os


@dataclass(frozen=True)
class ModelProvider:
    name: str
    base_url: str
    api_key_env: str
    default_model: str
    note: str = ""


# The shortlist. Every model id below was verified against the provider's
# own current docs/changelog on 2026-08-27 — not guessed from stale
# knowledge, this landscape moves fast enough that a wrong id fails silently
# with a confusing 404, not a helpful error.
PROVIDERS: list[ModelProvider] = [
    ModelProvider(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env="GOOGLE_GEMINI_API_KEY",
        default_model="gemini-3.1-pro",
        note="Strongest pure-reasoning option, GA since Feb 2026.",
    ),
    ModelProvider(
        name="mistral",
        base_url="https://api.mistral.ai/v1",
        api_key_env="MISTRAL_API_KEY",
        default_model="mistral-large-3",
        note="Flagship, Apache 2.0 open-weight.",
    ),
    ModelProvider(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        default_model="openai/gpt-oss-120b",
        note="Fastest inference of the shortlist — good for snappy chat.",
    ),
    ModelProvider(
        name="deepseek",
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        default_model="deepseek-v4-pro",
        note="Alternate flagship, different lab/training lineage than the rest.",
    ),
    ModelProvider(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        default_model="anthropic/claude-sonnet-4-6",
        note="Router, not a single model — flexible catch-all/fallback.",
    ),
    ModelProvider(
        name="minimax",
        base_url="https://api.minimax.chat/v1",  # TODO verify exact path before Phase 1 wiring
        api_key_env="MINIMAX_API_KEY",
        default_model="MiniMax-M3",
        note="Current general-purpose flagship, multimodal.",
    ),
    ModelProvider(
        name="mimo",
        base_url="https://token-plan-sgp.xiaomimimo.com/v1",
        api_key_env="MIMO_API_KEY",
        default_model="mimo-lite",  # TODO confirm exact model id string with the provider
        note="Xiaomi MiMo — item also has an anthropic_base_url field, unused here.",
    ),
    ModelProvider(
        name="opencode-zen",
        base_url="https://opencode.ai",  # TODO confirm exact path (likely /zen/v1 or similar)
        api_key_env="OPENCODE_API_KEY",
        default_model="deepseek-v4-flash-free",  # TODO free models rotate — verify before use
        note=(
            "OpenCode's own gateway, 'OpenCode Zen'. Free tier has rotating "
            "models — treat default_model here as unstable, re-check periodically."
        ),
    ),
]


def available_providers() -> list[ModelProvider]:
    """Providers whose API key is actually set in the environment."""
    return [p for p in PROVIDERS if os.environ.get(p.api_key_env)]


def get_provider(name: str) -> ModelProvider | None:
    return next((p for p in available_providers() if p.name == name), None)
