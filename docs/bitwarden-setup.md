# One-time Bitwarden setup (do this yourself, don't paste secrets into chat)

The sync script and systemd units are already deployed to the VPS but the timer is **not enabled yet** — it needs this setup done first.

## 1. Get your personal API key

Bitwarden web vault → Account Settings → Security → Keys → **View API Key**. Note the `client_id` and `client_secret`.

## 2. Log the CLI in on the VPS (interactive, values never touch this chat)

```
! ssh assistant-vps
bw login --apikey   # prompts for client_id / client_secret interactively
```

(Already done for `dyer.mason1994@gmail.com` as of 2026-08-27 — skip unless re-logging in.)

## 3. Write `~/.bw-sync.env` on the VPS

Still in your SSH session on the VPS, create `/root/.bw-sync.env`:

```
BW_CLIENTID=<from step 1>
BW_CLIENTSECRET=<from step 1>
```

Then:
```
chmod 600 ~/.bw-sync.env
```

This file holds the API key pair only — alone it can log the CLI in but can't decrypt anything without also unlocking the vault. The master password itself never goes in here (see step 4).

## 4. Encrypt your master password as a systemd credential

**Run this yourself on the VPS — the plaintext password should never be pasted into this chat.**

```
! ssh assistant-vps
echo -n 'your actual master password' | systemd-creds encrypt - /root/.bw-master-password.cred
chmod 600 /root/.bw-master-password.cred
```

`systemd-creds` encrypts it with a key derived from the machine's TPM (or a host-local key if no TPM) — the resulting file is only decryptable on this specific VPS, and only by root, and only for the duration of a unit run (`assistant-secrets-sync.service` already has `LoadCredentialEncrypted=BW_MASTER_PASSWORD:/root/.bw-master-password.cred` wired in). It's never written to disk as plaintext anywhere, including during this step (the `echo -n | systemd-creds encrypt -` pipe keeps it out of shell history too).

## 5. Confirm every credential has an item in your vault

`scripts/bitwarden_items.py` is the source of truth for which env vars sync — currently 8 model-provider keys (Gemini, Mistral, GROQ, DeepSeek, OpenRouter, MiniMax, MiMo, OpenCode Zen), already pointed at existing items in your "API Keys" folder. The Cline gateway key (`OPENAI_API_KEY`) and the Google client secret aren't in Bitwarden yet, so the sync script leaves both untouched on every run — no action needed unless you want those to auto-rotate too, in which case: create a Bitwarden item, add its id to `bitwarden_items.py`.

Google OAuth confidential material (`GOOGLE_CLIENT_SECRET_JSON`, `GOOGLE_TOKEN_ENCRYPTION_KEY`) stays on this VPS and **must never go in the APK**. See [docs/oauth-relay.md](oauth-relay.md). The Fernet key is safer as `/opt/assistant-backend/.google-token-key` than as an env var the rewrite might drop; the sync script now passthrough-copies OAuth relay keys *only if they already exist* in `assistant.env`.

## 6. Test it once, then enable the timer

```
! ssh assistant-vps
sudo systemd-run --pipe --wait --collect \
  -p LoadCredentialEncrypted=BW_MASTER_PASSWORD:/root/.bw-master-password.cred \
  /usr/bin/bash /opt/assistant-backend/scripts/sync_secrets_from_bitwarden.sh
cat /opt/assistant-backend/assistant.env   # confirm the provider keys got filled in
systemctl enable --now assistant-secrets-sync.timer
```

Tell me once this is done and I'll verify the timer's actually running and picking up the values correctly.
