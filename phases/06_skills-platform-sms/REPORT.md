# Phase 06 — skills platform + SMS — Report

**Status:** backend side COMPLETE (85 tests passed); phone-side relay is
`assistant-android` phase 10's job — the end-to-end SMS round-trip lands there.

## What landed (backend, commit `b0b49c5`)

### 1. Progressive-disclosure seam (verified, mostly pre-existing from the VPS merge)
- `app/skills.py` — SKILL.md loader (YAML frontmatter + markdown body, revisions
  via `.history/`), loaded at startup; adding a skill = writing `skills/<name>.md`
  + restart, no code change.
- `app/tools/skills_tools.py` — `list_skills` / `use_skill` / `create_skill` /
  `update_skill` registered in the always-visible set (the discovery seam itself
  is core, per ADR-009). `use_skill("name")` activates the skill's `tools:`
  list for the rest of the turn (chat.py `activated` set → `active_specs`).
- `skills/` now carries `morning-brief.md`, `flat-white.md`, and new `sms.md`.

### 2. SMS relay — backend tool + coordination (new this session)
- `app/tools/sms.py` — `send_sms(phone, message)`, `read_sms(phone?, limit)`,
  `get_sms_result(request_id)` registered with `always_visible=False` (hidden
  until `use_skill("sms")`). Dispatch = FCM data push to the registered device
  token (`action: send_sms|read_sms`, `request_id`, payload) + `sms_relay`
  tracking row (`dispatched`).
- `app/routers/sms.py` — `POST /v1/sms/results` (bearer-gated): the phone's
  report-back channel. Accepts `{request_id, ok, error?}` and
  `{request_id, ok, messages: [{from_number, message, received_at}]}`; 404 on
  unknown id.
- `app/db.py` — `sms_relay` + `sms_relay_messages` tables.
- `skills/sms.md` — skill file so `list_skills` exposes SMS without inflating
  the always-visible tool set.
- `docs/CONTRACT.md` — "SMS relay (phase 06)" section (FCM data payload shapes
  + `POST /v1/sms/results`), re-copied into `assistant-android/docs/CONTRACT.md`
  in the same commit (`e0b02de`) per the delegation-boundary rule.

## Verification
- `pytest` — **85 passed** (77 pre-existing + 8 new in `tests/test_sms.py`):
  hidden registration, skill file presence, FCM dispatch payload + relay row,
  no-phone guidance, results-endpoint failure/read-message recording, 404/401,
  pending/unknown read-back.
- Live smoke (local backend on 8420): `POST /v1/sms/results` unknown id → 404,
  no auth → 401, health 200.

## Human check — partially blocked, owned by the companion phase
- `list_skills` → SMS visible, always-visible tool set unchanged: ✅ (verified by
  unit test + skill file).
- `use_skill("sms")` → `send_sms`/`read_sms` round-trip via phone: needs the
  Android relay (FCM data-push handling + Android SMS APIs + results POST) —
  `assistant-android` phase 10. The backend side (dispatch, tracking, report
  channel, read-back) is complete and tested; the wire format is frozen in
  `docs/CONTRACT.md`.

## Optional slot — multi-account Google
Not done; deferred as the phase permits ("if time"). No schema or router change
was made for it.
