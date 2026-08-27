"""Mapping from env var name -> Bitwarden item id, for the sync script.

This is the ONLY place Bitwarden item ids are recorded. base_url values are
NOT duplicated here — app/providers.py is the source of truth for those
(see sync_secrets_from_bitwarden.py, which imports it), so a provider's URL
never has two places that can drift apart.

Add a new credential by adding one line here — nothing else needs editing
except, if it's a model provider, also adding the matching ModelProvider
entry to app/providers.py.
"""

API_KEY_ITEM_IDS: dict[str, str] = {
    # The Cline gateway key (OPENAI_API_KEY/OPENAI_BASE_URL in assistant.env)
    # has no Bitwarden item yet, so it's deliberately absent here — this
    # sync script leaves OPENAI_API_KEY untouched on every run, same as it
    # already treats ASSISTANT_BEARER_TOKEN. Create a Bitwarden item and add
    # its id here if you want the Cline key to auto-rotate too.
    # --- model provider registry (app/providers.py) ---
    "GOOGLE_GEMINI_API_KEY": "3db867ef-e0f2-4320-86df-b4ab0105b70f",
    "MISTRAL_API_KEY": "16f4722e-0bba-47a5-a99e-b4b101469210",
    "GROQ_API_KEY": "bf591473-8dcf-4cfc-be19-b4ab0105bea5",
    "DEEPSEEK_API_KEY": "74e1e518-e7b9-4b50-a94a-b4ab0105a7b4",
    "OPENROUTER_API_KEY": "94ba126c-16b5-4a4d-a092-b4ab0105f586",
    "MINIMAX_API_KEY": "893459de-89d7-4e88-b839-b4b2005fb349",
    "MIMO_API_KEY": "9788507d-159b-40ec-a2b3-b4ab0105cd86",
    "OPENCODE_API_KEY": "0d0f2ab3-f33e-4a25-8b50-b4ab0105e3fa",
    # Not yet found in the API Keys folder (checked fields/password/notes,
    # none had a value) — left out until located:
    # "GLM_API_KEY": "7a57c792-4b68-475b-8db2-b4af00e2b2bc",
}
