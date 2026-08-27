# ADR-003: encrypt Google OAuth tokens at the application layer, even on a controlled server

**Status:** live, applies starting phase `03`

`google_oauth_tokens.access_token_enc`/`refresh_token_enc` are encrypted with `cryptography.fernet`, keyed off an env-supplied secret — not stored as plaintext columns, even though the SQLite file lives on a VPS Mason controls end to end.

**Why:** defense in depth against the DB file itself leaking — a backup copied somewhere it shouldn't be, a misconfigured permission, a future contributor with read access to the box for an unrelated reason. "The server is trusted" is true today and is exactly the assumption that ages worst. Mirrors the Android side's Keystore-not-`EncryptedSharedPreferences` instinct (see `assistant-android`'s equivalent ADR).
