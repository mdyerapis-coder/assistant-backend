#!/usr/bin/env python3
"""One-off: print a fresh bearer token for ASSISTANT_BEARER_TOKEN.

Run once, put the result in assistant.env on the server, paste the same
value into the Android app's onboarding screen. Not meant to be run again
unless rotating the token (in which case the app also needs re-onboarding).
"""

import secrets

if __name__ == "__main__":
    print(secrets.token_urlsafe(32))
