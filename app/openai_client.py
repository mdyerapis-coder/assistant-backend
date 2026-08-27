"""Thin wrapper around the OpenAI SDK's async client.

base_url/api_key come from config — currently Cline's own gateway
(api.cline.bot), which is OpenAI-Chat-Completions-compatible, so no client
code differs from talking to api.openai.com directly. See app/providers.py
for the separate model-provider registry (Gemini/Mistral/GROQ/etc.) — not
wired into the chat loop yet, letting the user pick a provider per-request
is a later concern than proving the loop works at all.
"""

from openai import AsyncOpenAI

from . import config

# Verified working against Cline's gateway during phase 00 credential setup
# (2026-08-27) — a namespaced model id, not a raw OpenAI/Anthropic one.
DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"

# "unset" placeholder: the SDK now refuses to construct with an empty-string
# key. Production always has a real OPENAI_API_KEY via assistant.env: an
# unset key here would only bite in a dev/test environment, where every
# call site either doesn't reach the network or monkeypatches `create`
# directly, so the placeholder value itself is never used.
client = AsyncOpenAI(
    api_key=config.OPENAI_API_KEY or "unset", base_url=config.OPENAI_BASE_URL
)
