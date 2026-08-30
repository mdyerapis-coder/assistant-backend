# Phase 06 — skills platform + SMS

**Reads:** `docs/plan.md` §1.5 (skills/tools — progressive disclosure), `docs/adr/009-tool-registry-and-progressive-disclosure.md`, `app/tools/registry.py` (flat `always_visible` list), `phases/03_calendar-email/REPORT.md` (single-account `google_oauth_tokens` baseline). Companion: `assistant-android` `phases/10_skills-sms` (owns phone-side relay).

**Does:**
1. Progressive-disclosure seam — `list_skills()`/`use_skill(name)` over `app/tools/registry.py` (`always_visible=false` hidden until expanded) + `SKILL.md` loader (YAML frontmatter + markdown under `skills/`, loaded at startup; adding a skill = writing a file).
2. First non-core skill — SMS: backend tools `send_sms`/`read_sms` dispatched via connected phone; this phase owns backend tool + relay coordination, Android owns on-device relay.
3. Optional slot (~2h, if time): multi-account Google — widen `google_oauth_tokens` to `(provider, account_id)`, deferred from phase 03.

**Writes:** `app/tools/registry.py` (seam), `skills/*.md` + loader, `app/tools/sms.py` (+ relay endpoint/queue); optionally `app/db.py` + `app/tools/calendar.py`/`gmail.py` + `app/routers/oauth_google.py` for multi-account.

**Human check:** `list_skills` returns SMS (and any file-added skill) without inflating `always_visible`; `use_skill("sms")` injects schema then `send_sms`/`read_sms` round-trips via phone. Verify adding a skill = writing `skills/<name>.md` + restart (no code change). Optional: second Google account connects and calendar/email disambiguate.

**When done:** write `REPORT.md`.
