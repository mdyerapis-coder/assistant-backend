# docs/adr/

## OVERVIEW
One decision per file, numbered in creation order. Read before undoing any of these choices.

## INDEX
| ADR | Decision |
|-----|----------|
| 001 | Pure modules where possible — keep domain logic (e.g. `memory.py`) framework-free and testable in isolation |
| 002 | Errors carry intent — fail loudly on misconfiguration (e.g. missing bearer token) rather than silently degrading |
| 003 | Encrypt tokens at rest |
| 004 | No JVM toolchain (note only, 5 lines) |
| 005 | Backend-mediated tools — the phone never talks to OpenAI/Google directly; all tool state lives server-side |
| 006 | Reminder creation vs. delivery are separate concerns/phases |
| 007 | Google OAuth is backend-anchored, not phone-anchored |
| 008 | Two-tier memory: tier-1 size-capped facts in every prompt, tier-2 plain SQL search, no vector DB |
| 009 | Flat append-only tool registry + progressive disclosure for anything non-core |
| 010 | No vector DB in v1 |
| 011 | Bitwarden secret sync — `sync_secrets_from_bitwarden.sh` writes `assistant.env`, restart-on-change pull |
| 012 | Embedding this backend inside the Android APK — analysis of what it would take |
| 013 | Embed path OAuth + push — O1 thin OAuth relay, P1 WorkManager+local notifications, P2 in-process SMS. Operator surface: `docs/oauth-relay.md` |

## CONVENTIONS
- Each ADR is short (5-7 lines): status/phase line, the decision, one paragraph of why. Don't
  pad — if a decision needs more space than that, it probably needs its own section in
  `docs/plan.md` instead.
- `docs/plan.md` is the source of truth if an ADR and the plan ever disagree.

## ANTI-PATTERNS
- Don't add a new ADR for something already covered by an existing one — extend the existing file
  if the reasoning changes, add a new numbered file only for a genuinely new decision.
