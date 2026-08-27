# ADR-005: backend-mediated tool execution is mandatory, not a convenience

**Status:** live

The phone never holds the OpenAI key or a Google token, and never calls either API directly. Every tool call — reminders, calendar, email, memory reads/writes — executes here, server-side, inside the same OpenAI turn that requested it.

**Why:** tool execution needs server-held state (SQLite rows, refresh tokens, the API key) that must never live on a device that can be lost or rooted. There's no version of "the phone talks to OpenAI directly" that doesn't also require a round-trip to a backend for tool execution anyway — so direct-to-OpenAI buys nothing and costs key custody. See `docs/plan.md` §1 for the full API shape this produces.
