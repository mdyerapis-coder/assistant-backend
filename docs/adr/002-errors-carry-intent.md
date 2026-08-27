# ADR-002: error responses carry intent, not just a status code

**Status:** live

Distinguish, explicitly, in every error path: was this retryable, does it mean the bearer token is dead, is it fatal, or did a specific tool call fail? Don't let a bare HTTP status code be the only signal — the Android side has to decide "show a retry button" vs. "kick back to onboarding" vs. "show the error inline in this one message," and it shouldn't have to guess from a status code alone.

**Why:** mirrors the Android side's `AppError` sealed type (`Retryable`/`AuthExpired`/`Fatal`/`ToolExecutionFailed`) — see `assistant-android`'s equivalent ADR once that repo exists. The `error` SSE event (`docs/CONTRACT.md`) carries a `retryable: bool` for exactly this reason; extend that pattern rather than adding a second one if new failure classes show up.
