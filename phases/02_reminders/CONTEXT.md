# Phase 02 — reminders (creation, not delivery)

**Reads:** phase `01.5`'s `REPORT.md`. `docs/adr/006-reminder-creation-vs-delivery.md` — read this before assuming delivery (scheduled push) belongs in this phase; it explicitly doesn't.

**Does:** add the `reminders` table and `create_reminder`/`list_reminders`/`cancel_reminder` tools to the registry, marked `always_visible`. Zero external dependencies — no Firebase, no push infra. Fully exercised through chat alone.

**Writes:** `app/tools/reminders.py`, `reminders` table in `app/db.py`.

**Human check:** "remind me to call the dentist tomorrow at 9am" → confirm a row lands in `reminders` with the correct `due_at`. "What are my reminders" → confirm it lists back correctly, including the one just created.

**When done:** write `REPORT.md`.
