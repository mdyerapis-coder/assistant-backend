#!/usr/bin/env python3
"""Resolve secrets from Bitwarden into assistant.env.

Called by sync_secrets_from_bitwarden.sh after it has an unlocked session.
Not meant to be run standalone except for manual testing (pass --session
yourself). Reads item ids from bitwarden_items.py, base_urls from
app/providers.py — neither value is duplicated here.

Fields the assistant service needs but that no Bitwarden item currently
covers (ASSISTANT_BEARER_TOKEN, the Cline OPENAI_API_KEY/OPENAI_BASE_URL,
GOOGLE_CLIENT_SECRET_JSON, ASSISTANT_DB_PATH) are read from the existing
env file and carried through unchanged — this script only ever touches the
keys it has a Bitwarden item id for.

O1 relay keys (ASSISTANT_PUBLIC_URL, GOOGLE_OAUTH_*, GOOGLE_TOKEN_ENCRYPTION_KEY)
are also passthrough, but only when already present — never written empty, so
a rewrite cannot blank the production OAuth redirect. See docs/oauth-relay.md.
None of the Google confidential material belongs in the APK.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from bitwarden_items import API_KEY_ITEM_IDS  # noqa: E402
from app.providers import PROVIDERS  # noqa: E402

# env var name -> base_url, derived from the provider registry so a url
# never has to be typed twice.
BASE_URL_BY_ENV = {p.api_key_env: p.base_url for p in PROVIDERS}

# Keys this script never touches — carried through from the existing file
# verbatim, in this order, at the top of the rewritten file.
PASSTHROUGH_KEYS = [
    "ASSISTANT_BEARER_TOKEN",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "GOOGLE_CLIENT_SECRET_JSON",
    "ASSISTANT_DB_PATH",
]

# O1 relay keys (docs/oauth-relay.md). Only copied if already present so we
# never write `ASSISTANT_PUBLIC_URL=` (empty) and override config.py's
# production default into a broken Google redirect_uri.
OAUTH_RELAY_PASSTHROUGH_KEYS = [
    "ASSISTANT_PUBLIC_URL",
    "GOOGLE_OAUTH_REDIRECT_URI",
    "GOOGLE_OAUTH_DEEPLINK",
    "GOOGLE_TOKEN_ENCRYPTION_KEY",
]


def get_item_value(item_id: str, session: str) -> str:
    raw = subprocess.run(
        ["bw", "get", "item", item_id, "--session", session],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    item = json.loads(raw)

    fields = {f.get("name"): f.get("value") for f in item.get("fields", []) or []}
    if fields.get("api_key"):
        return fields["api_key"]

    password = (item.get("login") or {}).get("password")
    if password:
        return password

    notes = item.get("notes")
    if notes:
        return notes.strip()

    return ""


def parse_existing_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key] = value
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    parser.add_argument("--env-file", required=True, type=Path)
    args = parser.parse_args()

    existing = parse_existing_env(args.env_file)

    lines = [f"{key}={existing.get(key, '')}" for key in PASSTHROUGH_KEYS]
    for key in OAUTH_RELAY_PASSTHROUGH_KEYS:
        if key in existing:
            lines.append(f"{key}={existing[key]}")

    for env_key, item_id in API_KEY_ITEM_IDS.items():
        value = get_item_value(item_id, args.session)
        lines.append(f"{env_key}={value}")
        base_url = BASE_URL_BY_ENV.get(env_key)
        if base_url:
            base_url_key = env_key.replace("_API_KEY", "_BASE_URL")
            lines.append(f"{base_url_key}={base_url}")

    new_content = "\n".join(lines) + "\n"
    old_content = args.env_file.read_text() if args.env_file.exists() else ""

    if new_content == old_content:
        print("[secrets-sync] no change")
        return 0

    args.env_file.write_text(new_content)
    args.env_file.chmod(0o600)
    print("[secrets-sync] secrets changed — restarting assistant.service")
    subprocess.run(["systemctl", "restart", "assistant.service"], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
