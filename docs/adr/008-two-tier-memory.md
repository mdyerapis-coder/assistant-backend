# ADR-008: two-tier memory, not a knowledge graph — borrowed from Hermes Agent

**Status:** live, phase `01`

Tier 1 (`user_facts`) is small, size-capped, and loaded once per request into the system prompt — never fetched mid-conversation. A write past the cap fails loudly and tells the model to consolidate/replace an existing key, rather than silently auto-summarizing. Tier 2 is the existing `messages` table, searched on demand via plain SQLite text search (`search_past_conversations`).

**Why:** researched Hermes Agent (`NousResearch/hermes-agent` — confirmed to be the software behind Mason's own self-hosted `hermes-gateway`), OpenHuman, and Khoj before choosing this. Hermes's two-tier design (bounded always-in-context facts vs. separate searchable history) is the cheapest of the three to build and the one that best fits a project this size — no vector DB, no knowledge-graph engine. Loading tier 1 once per request rather than mid-conversation specifically preserves prompt-cache stability. "Learning" here is not a separate subsystem: it's the model itself deciding to call `remember(...)` when it notices something worth keeping — see `docs/plan.md` §1.5 for the full comparison against all four projects researched.
