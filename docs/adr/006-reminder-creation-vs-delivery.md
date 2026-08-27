# ADR-006: reminder creation and reminder delivery are separately shippable

**Status:** live, phase `02` (creation) vs. `02.5` (delivery)

Creating/listing/cancelling reminders is pure backend logic — a tool-calling loop plus a SQLite table, zero external dependencies. *Delivering* a reminder at its due time (a scheduler pushing a notification to the phone) needs Firebase Cloud Messaging: a Firebase project, a service account, and FCM token registration from the Android app.

**Why:** don't gate the reminders demo on Firebase setup. "Remind me to call the dentist" → tool call → row created → confirmed back in chat is a complete, demoable loop on its own. Delivery is real, wanted, and a distinct piece of work — see `docs/plan.md` §3, phase `02.5`.
