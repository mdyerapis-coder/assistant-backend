"""Firebase Cloud Messaging integration using firebase-admin SDK.

Initialized with a service account JSON file. Sends push notifications
to registered device tokens. See docs/adr/006-reminder-creation-vs-delivery.md.
"""

import logging
import os
from pathlib import Path
from typing import Sequence

import firebase_admin
from firebase_admin import credentials, messaging

logger = logging.getLogger(__name__)

_initialized = False


def _init_firebase() -> None:
    """Initialize Firebase Admin SDK with the service account key."""
    global _initialized
    if _initialized:
        return

    cred_path = os.environ.get(
        "FIREBASE_CREDENTIALS",
        str(Path(__file__).parent.parent / "service-account.json"),
    )

    if not os.path.exists(cred_path):
        logger.warning(
            "Firebase credentials not found at %s — FCM will be a no-op",
            cred_path,
        )
        return

    try:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        _initialized = True
        logger.info("Firebase Admin SDK initialized with %s", cred_path)
    except Exception:
        logger.exception("Failed to initialize Firebase Admin SDK")


async def send_notification(
    tokens: Sequence[str],
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> bool:
    """Send an FCM push notification to one or more device tokens.

    Returns True if all sends succeeded, False otherwise.
    If Firebase is not initialized, logs and returns True (no-op).
    """
    _init_firebase()

    if not _initialized:
        logger.warning("FCM not initialized — skipping notification: %s", body)
        return True

    try:
        messages = [
            messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=data or {},
                token=token,
            )
            for token in tokens
        ]
        response = messaging.send_each(messages)

        if response.failure_count > 0:
            logger.error(
                "FCM: %d/%d sends failed",
                response.failure_count,
                len(messages),
            )
            for i, send_response in enumerate(response.responses):
                if not send_response.success:
                    logger.error(
                        "  Token %d failed: %s", i, send_response.exception
                    )
            return False

        logger.info("FCM: sent to %d tokens successfully", len(messages))
        return True
    except Exception:
        logger.exception("FCM send failed")
        return False
