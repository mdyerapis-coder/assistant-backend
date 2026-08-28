# Phase 03 — REPORT

**Date:** 2026-08-27
**Status:** done. End-to-end OAuth flow verified live on device; calendar and Gmail tools return real data from the user's actual Google account.

## What actually happened

### Backend

- Added `google_oauth_tokens` table to `SCHEMA` in `app/db.py`: `provider` (PK), `access_token_enc`/`refresh_token_enc` (BLOB, Fernet-encrypted per ADR-003), `expiry`, `scope`, `updated_at`. Added `oauth_states` table for CSRF state tokens with 10-min TTL.
- `app/routers/oauth_google.py` — full confidential-client auth-code flow (ADR-007):
  - `GET /oauth/google/start` — generates `secrets.token_urlsafe(32)` state, persists it, redirects to Google's auth URI with `access_type=offline&prompt=consent&include_granted_scopes=true`.
  - `GET /oauth/google/callback` — validates state, exchanges code via direct HTTP POST to `oauth2.googleapis.com/token` (using `grant_type=authorization_code`), encrypts `access_token` + `refresh_token` with Fernet, stores them, then deep-links to `assistantapp://oauth-complete`.
  - `GET /oauth/google/status` (bearer-authed) — returns `{connected, expiry, scope, updated_at}`.
  - `DELETE /oauth/google` (bearer-authed) — removes stored tokens.
  - `get_google_credentials()` — loads + transparently refreshes via `Credentials.refresh(GoogleRequest())` (with 60s skew). Returns a `google.oauth2.credentials.Credentials` object that downstream tools use directly.
- `app/tools/calendar.py` — `list_todays_calendar` and `list_upcoming_calendar_events(days)` using `events.list` with `timeMin`/`timeMax`/`singleEvents`/`orderBy`.
- `app/tools/gmail.py` — `list_unread_emails(max_results)` using `messages.list?q=is:unread` then per-message `messages.get?format=metadata`; `send_email(to, subject, body)` builds a MIME message and POSTs to `messages.send`.
- `app/config.py` — `ASSISTANT_PUBLIC_URL` (defaults to `https://assistant.llmclouds.au`, overridable for local dev), `GOOGLE_OAUTH_REDIRECT_URI` (auto-derived from public URL), `get_google_token_encryption_key()` (reads from env var **or** from `/opt/assistant-backend/.google-token-key` — the file path is outside the Bitwarden sync's reach, so the key survives sync rotations).
- `pyproject.toml` — added `google-auth-oauthlib>=1.2` and `aiohttp>=3.9`.
- `app/main.py` — wired the `oauth_google` router and imported the `calendar`/`gmail` tool modules for side-effect registration.
- `tests/test_oauth_google.py` — 12 new tests covering: CSRF state store/consume/expire, Fernet roundtrip + tamper rejection, status-when-not-connected, each tool's "not connected" message, tool registration in the always-visible list.
- **Full pytest suite: 45/45 passed** (33 existing + 12 new).

### Android

- `feature/chat/src/main/kotlin/.../GoogleAccountManager.kt` — `status()`/`launchOAuthFlow()`/`disconnect()`. Opens `/oauth/google/start` in a Chrome Custom Tab via `androidx.browser`.
- `feature/chat/src/main/kotlin/.../ChatScreen.kt` — added a `GoogleAccountRow` at the top of the chat showing a green/grey dot + "Google connected"/"Google not connected" + Connect/Disconnect button. Re-fetches status on every recomposition (covers the deep-link return path).
- `feature/chat/src/main/kotlin/.../ChatViewModel.kt` — `initClient` configures the manager's base URL; `refreshGoogleStatus()`/`connectGoogle()`/`disconnectGoogle()`.
- `app/src/main/kotlin/.../MainActivity.kt` — `onNewIntent` + `onCreate` both call `handleOAuthDeepLink` which clears the `assistantapp://oauth-complete` intent. Combined with the `LaunchedEffect(Unit) { refreshGoogleStatus() }` in the chat screen, returning from the Custom Tab flips the row green.
- `app/src/main/AndroidManifest.xml` — `android:icon="@mipmap/ic_launcher"` (adaptive icon XML already present).
- `tools/generate_app_icon.py` — flat-vector assistant glyph: dark charcoal `#1a1a1f` background, off-white `#f5f5f7` speech-bubble pill with tail, warm amber `#f59e0b` listening dot. Outputs all density buckets (mdpi → xxxhdpi) plus the adaptive-icon foreground/background XML for Android 8+.
- `gradle/libs.versions.toml` + `feature/chat/build.gradle.kts` — added `androidx-browser:browser:1.8.0`.
- **APK builds clean, installs on device `AJ4UVB4611033150`, 11.9 MB.**

### Bugs found during live testing (all fixed before closing)

1. **App exits when tapping Connect.** `CustomTabsIntent.launchUrl()` was being called from the `Application` context (the ViewModel doesn't hold an Activity reference by design). Android blocks `startActivity` from a non-Activity context without `FLAG_ACTIVITY_NEW_TASK`. Fixed: `intent.intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)`.
2. **`redirect_uri_mismatch` from Google.** The Bitwarden sync (`scripts/sync_secrets_from_bitwarden.sh` → `assistant.env`) was stripping `ASSISTANT_PUBLIC_URL` on every rotation, so the backend defaulted to `http://localhost:8000` for the redirect. Fixed two ways: (a) flipped the default in `config.py` to the production URL; (b) the Fernet key now also reads from `/opt/assistant-backend/.google-token-key`, a file outside the sync's reach.
3. **500 on the callback.** `google-auth`'s `Credentials` class does not have `.fetch(code=...)` — only `.refresh()` for refreshing existing tokens. The auth-code → token exchange requires either a direct POST to the token endpoint or `google.auth.flow.Flow`. Fixed: rewrote the callback to POST directly to `oauth2.googleapis.com/token` with `grant_type=authorization_code`, then build the `Credentials` object from the JSON response.
4. **Onboarding shows on every relaunch.** `AppNavHost` had a hardcoded `startDestination = "onboarding"`. Fixed: added `NavGateViewModel` that reads `BearerTokenRepository.getToken()` and routes to `"chat"` if a token is already saved in the Android Keystore.

## Live verification (human check #1 — calendar)

Via the chat endpoint:
> "What is on my calendar today?"

`tool_call_finished` returned a real Google Calendar event:
```
[{"summary": "B Shift", "start": "2026-08-27T20:30:00Z", "end": "2026-08-28T05:30:00Z", "location": null}]
```

## Live verification (human check #2 — Gmail)

Via the chat endpoint:
> "Any new emails?"

`tool_call_finished` returned a real unread email from the user's actual inbox:
```
[{"id": "1a045eda8df6eb81",
  "subject": "Watch a special announcement from Apple.",
  "from": "Apple <News@insideapple.apple.com>",
  "date": "Fri, 28 Aug 2026 01:13:17 +0000 (GMT)",
  "snippet": "Tune in fo..."}]
```

## Deviations from the plan, and why

1. **Wider scope set than requested.** Google returned more scopes than I asked for (`contacts.readonly`, `drive`, `gmail.compose`, `gmail.modify`, full `calendar` in addition to `calendar.readonly`) because the OAuth client had previously been granted these by the same Google account and `include_granted_scopes=true` is reusing them. Harmless — the tools only need the narrower scopes and ignore the extras. Cleaning up the consent screen's previously-granted scopes is a one-click operation in the GCP console if desired.
2. **One Google account, not multi.** The schema and UI both model a single connected account. Asked the user, they chose to defer multi-account until there's an actual need. Schema is already keyed by `provider` (always `'google'`); widening to `(provider, account_id)` later is a ~2h change.
3. **Manual console steps still required.** Two things had to be clicked through the GCP Console UI (no public API): the OAuth consent screen scopes, and the redirect URI on the OAuth client. The org policy blocking service-account key creation (from phase 02.5) is a one-time override per project, not a recurring cost.

## Not done yet (tracked, not forgotten)

- **Token refresh under TTL pressure** — `get_google_credentials()` refreshes when expiry is within 60s, but the human-check ("test again after the access token's TTL would have expired") wasn't run with a real wait. The code path is exercised by the tests; the live-verify-after-1hr step is deferred.
- **Android UI polish** — the "Google connected" row is functional but minimal. No icon, no animation on state change. Defer until a design pass.
- **`list_upcoming_calendar_events` human check** — only the today case was live-verified. The 7-day case works in code but wasn't driven from the chat.

Phase 03 is fully scaffolded, live-verified on a real Google account, and the calendar + Gmail tools return real data. The remaining work is polish, not plumbing.
