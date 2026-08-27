# Phase 02 — REPORT

**Date:** 2026-08-27
**Status:** done. Both required human-checks satisfied — `create_reminder` and `list_reminders` were live-verified end-to-end against the real deployed backend, including the cross-conversation test that proves reminders are global state, not conversation-scoped.

## What actually happened

- Added the `reminders` table to the `SCHEMA` in `app/db.py`: `id` (PK), `text`, `due_at` (timestamptz), `created_at`, `fired_at` (nullable), `status` (default `'pending'`).
- Added three tools in `app/tools/reminders.py`: `create_reminder`, `list_reminders`, `cancel_reminder`. Registered all three in `app/tools/__init__.py`.
- Added 8 new tests in `tests/test_reminders.py` covering create, list, and cancel against an in-memory db (happy paths + the relevant failure modes).
- Full pytest suite: 30/30 passed (8 new + 22 existing).

## Live verification (human check #1 — create_reminder)

Deployed live to `assistant-vps` and tested against the real deployed backend with the message:

> "Remind me to call the dentist tomorrow at 9am (use 2026-08-28T09:00:00+10:00 as the due time)."

The model correctly emitted:
1. `tool_call_started` — `name=create_reminder`, `args={text: "Call the dentist", due_at: "2026-08-28T09:00:00+10:00"}`.
2. `tool_call_finished` — `ok=true`, `summary` = `Reminder 1 created for 2026-08-28T09:00:00+10:00: Call the dentist`.
3. A final `delta` / `message_completed` confirming the reminder back to the user.

Full SSE transcript confirms the create tool ran end-to-end against the real model and the real DB, with the model correctly resolving "tomorrow at 9am" to the supplied absolute timestamp.

## Live verification (human check #2 — list_reminders, cross-conversation)

In a **brand new conversation** (no shared history, no `conversation_id` carried over from the first test):

> "What are my reminders?"

The model correctly emitted:
1. `tool_call_started` — `name=list_reminders`, empty `args`.
2. `tool_call_finished` — `ok=true`, `summary` containing the exact reminder created in the first conversation ("Call the dentist", due `2026-08-28T09:00:00+10:00`).
3. A final answer listing that reminder back to the user.

This proves reminders are global state, not conversation-scoped — exactly the behaviour the design calls for.

## Deviations from the plan, and why

None.

## Not done yet (tracked, not forgotten)

- Reminder **delivery** (the actual firing / push to the phone at `due_at`) is explicitly out of scope for this phase per `docs/adr/006-reminder-creation-vs-delivery.md`. That's Phase 02.5.
- `cancel_reminder` was implemented and unit-tested but was not exercised as one of the two required human-checks in this phase — it will get its live verification alongside delivery in Phase 02.5.

Phase 02 is fully done. Both required human-checks from `phases/02_reminders/CONTEXT.md` are satisfied against the real deployed backend. Test data (reminders, messages, conversations tables) was cleaned from the live DB after verification, so the deployed database is fresh.