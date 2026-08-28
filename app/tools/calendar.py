"""Google Calendar tool — list today's events.

Uses the OAuth credentials stored by app/routers/oauth_google.py. If the
user hasn't connected Google yet, returns a helpful message that tells
the model to ask the user to connect.
"""

import json
from datetime import datetime, timezone

import aiohttp

from ..routers import oauth_google
from .registry import ToolSpec, register


async def _list_today_events() -> str:
    creds = await oauth_google.get_google_credentials()
    if creds is None:
        return (
            "Google Calendar is not connected. Ask the user to connect Google "
            "by opening the assistant app and tapping the 'Connect to Google' "
            "button."
        )

    # Calculate the start and end of today in UTC. Calendar's 'singleEvents'
    # query handles the rest.
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day.replace(hour=23, minute=59, second=59)

    params = {
        "timeMin": start_of_day.isoformat(),
        "timeMax": end_of_day.isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "20",
    }
    headers = {"Authorization": f"Bearer {creds.token}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            params=params,
            headers=headers,
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                return f"Calendar API error ({resp.status}): {body[:200]}"
            data = await resp.json()

    events = data.get("items", [])
    if not events:
        return "No events scheduled for today."

    return json.dumps(
        [
            {
                "summary": e.get("summary", "(no title)"),
                "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date")),
                "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date")),
                "location": e.get("location"),
            }
            for e in events
        ]
    )


async def _list_upcoming_events(days: int = 7) -> str:
    creds = await oauth_google.get_google_credentials()
    if creds is None:
        return (
            "Google Calendar is not connected. Ask the user to connect Google "
            "by opening the assistant app and tapping the 'Connect to Google' "
            "button."
        )

    now = datetime.now(timezone.utc)
    end_window = now.replace() + (
        __import__("datetime").timedelta(days=days)
    )

    params = {
        "timeMin": now.isoformat(),
        "timeMax": end_window.isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "50",
    }
    headers = {"Authorization": f"Bearer {creds.token}"}

    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            params=params,
            headers=headers,
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                return f"Calendar API error ({resp.status}): {body[:200]}"
            data = await resp.json()

    events = data.get("items", [])
    if not events:
        return f"No events in the next {days} days."

    return json.dumps(
        [
            {
                "summary": e.get("summary", "(no title)"),
                "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date")),
                "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date")),
                "location": e.get("location"),
            }
            for e in events
        ]
    )


register(
    ToolSpec(
        name="list_todays_calendar",
        description=(
            "List the user's Google Calendar events for today. Returns a JSON "
            "array of events with summary, start, end, and location. If Google "
            "is not connected, returns a message telling the user to connect."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        fn=_list_today_events,
    )
)

register(
    ToolSpec(
        name="list_upcoming_calendar_events",
        description=(
            "List the user's Google Calendar events for the next N days "
            "(default 7). Returns a JSON array of events."
        ),
        parameters={
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to look ahead (default 7).",
                    "default": 7,
                },
            },
            "required": [],
        },
        fn=_list_upcoming_events,
    )
)
