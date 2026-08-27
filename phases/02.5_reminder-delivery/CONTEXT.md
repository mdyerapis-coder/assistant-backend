# Phase 02.5 — reminder delivery (separately shippable, needs Firebase)

**Reads:** phase `02`'s `REPORT.md`. `docs/adr/006-reminder-creation-vs-delivery.md`.

**Does:** a scheduler that fires when a `reminders.due_at` passes and pushes a notification to the phone. New external dependency this phase introduces and phase `02` did not need: a Firebase project, a service account, and FCM token registration from the Android app (which needs its own corresponding piece of work — coordinate with whichever tool owns `assistant-android` before starting this).

**Writes:** a scheduling loop (polling `reminders` for `status = 'pending' AND due_at <= now`, or a proper job scheduler if polling proves too coarse), FCM send integration, `reminders.fired_at`/`status` updates.

**Human check:** create a reminder due 2 minutes out, confirm a push notification actually lands on the phone at (approximately) the right time, confirm `reminders.status` flips to `fired`.

**When done:** write `REPORT.md`.
