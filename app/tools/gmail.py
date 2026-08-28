"""Gmail tools — list recent unread messages, send a message.

Uses the OAuth credentials stored by app/routers/oauth_google.py. If the
user hasn't connected Google yet, returns a helpful message that tells
the model to ask the user to connect.
"""

import base64
import json
from email.mime.text import MIMEText

import aiohttp

from ..routers import oauth_google
from .registry import ToolSpec, register


async def _list_unread_emails(max_results: int = 10) -> str:
    creds = await oauth_google.get_google_credentials()
    if creds is None:
        return (
            "Gmail is not connected. Ask the user to connect Google by "
            "opening the assistant app and tapping the 'Connect to Google' "
            "button."
        )

    headers = {"Authorization": f"Bearer {creds.token}"}
    params = {
        "q": "is:unread",
        "maxResults": str(max_results),
    }

    async with aiohttp.ClientSession() as session:
        # List unread message IDs
        async with session.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            params=params,
            headers=headers,
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                return f"Gmail API error ({resp.status}): {body[:200]}"
            list_data = await resp.json()

        messages = list_data.get("messages", [])
        if not messages:
            return "No unread emails."

        # Fetch each message's metadata. Limit fields to keep response small.
        results = []
        for msg_meta in messages[:max_results]:
            msg_id = msg_meta["id"]
            async with session.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}",
                params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    continue
                msg = await resp.json()
                headers_list = msg.get("payload", {}).get("headers", [])
                subject = next((h["value"] for h in headers_list if h["name"] == "Subject"), "(no subject)")
                from_ = next((h["value"] for h in headers_list if h["name"] == "From"), "(unknown)")
                date = next((h["value"] for h in headers_list if h["name"] == "Date"), "")
                results.append({
                    "id": msg_id,
                    "subject": subject,
                    "from": from_,
                    "date": date,
                    "snippet": msg.get("snippet", ""),
                })

    return json.dumps(results)


async def _send_email(to: str, subject: str, body: str) -> str:
    creds = await oauth_google.get_google_credentials()
    if creds is None:
        return (
            "Gmail is not connected. Ask the user to connect Google by "
            "opening the assistant app and tapping the 'Connect to Google' "
            "button."
        )

    # Build a MIME message
    mime = MIMEText(body)
    mime["to"] = to
    mime["subject"] = subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()

    payload = {"raw": raw}
    headers = {
        "Authorization": f"Bearer {creds.token}",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            json=payload,
            headers=headers,
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                return f"Gmail send failed ({resp.status}): {body[:200]}"
            data = await resp.json()

    return f"Email sent to {to}. Message id: {data.get('id', 'unknown')}"


register(
    ToolSpec(
        name="list_unread_emails",
        description=(
            "List the user's unread Gmail messages. Returns a JSON array with "
            "subject, from, date, and snippet for each message. If Gmail is "
            "not connected, returns a message telling the user to connect."
        ),
        parameters={
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of messages to return (default 10).",
                    "default": 10,
                },
            },
            "required": [],
        },
        fn=_list_unread_emails,
    )
)

register(
    ToolSpec(
        name="send_email",
        description=(
            "Send an email on the user's behalf via Gmail. The model must "
            "have already confirmed the recipient, subject, and body with "
            "the user before calling this."
        ),
        parameters={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address.",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line.",
                },
                "body": {
                    "type": "string",
                    "description": "Email body (plain text).",
                },
            },
            "required": ["to", "subject", "body"],
        },
        fn=_send_email,
    )
)
