# One-time Bitwarden setup (do this yourself, don't paste secrets into chat)

The sync script and systemd units are already deployed to the VPS but the timer is **not enabled yet** — it needs this setup done first.

## 1. Get your personal API key

Bitwarden web vault → Account Settings → Security → Keys → **View API Key**. Note the `client_id` and `client_secret`.

## 2. Log the CLI in on the VPS (interactive, values never touch this chat)

```
! ssh assistant-vps
bw login --apikey
# prompts for client_id / client_secret interactively
```

## 3. Create Bitwarden items for the secrets

In your vault, create a login-type item per secret (name doesn't matter, e.g. "assistant-openai-key"), with the actual key value in the **password** field. Do this for:
- OpenAI API key
- Google client secret (the JSON content, or just the secret value — your call)

## 4. Find each item's ID and write `~/.bw-sync.env` on the VPS

Still in your SSH session on the VPS:

```
bw unlock   # prompts for master password interactively
bw list items --search "assistant-openai-key" --session <the session key it printed>
# note the "id" field
```

Then create `~/.bw-sync.env` (root's home, i.e. `/root/.bw-sync.env`) with:

```
BW_CLIENTID=<from step 1>
BW_CLIENTSECRET=<from step 1>
BW_MASTER_PASSWORD=<your vault master password>
```

and export the two item IDs into the environment the sync script reads — easiest is to add them to the same file:

```
OPENAI_ITEM_ID=<id from bw list items>
GOOGLE_CLIENT_SECRET_ITEM_ID=<id from bw list items>
```

Then:
```
chmod 600 ~/.bw-sync.env
```

**This file is now the single most sensitive thing on the box — it contains your Bitwarden master password.** Treat it accordingly.

## 5. Test it once, then enable the timer

```
sudo bash /opt/assistant-backend/scripts/sync_secrets_from_bitwarden.sh
cat /opt/assistant-backend/assistant.env   # confirm OPENAI_API_KEY got filled in
systemctl enable --now assistant-secrets-sync.timer
```

Tell me once this is done and I'll verify the timer's actually running and picking up the values correctly.
