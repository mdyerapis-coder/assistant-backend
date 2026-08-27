# ADR-007: Google OAuth is backend-anchored (confidential client), not phone-side PKCE

**Status:** live, phase `03`

The backend already holds a confidential OAuth client (`client_secret_*.apps.googleusercontent.com.json`, GCP project `182773386348`) and is the thing that actually executes calendar/email tools — so it runs a standard authorization-code flow itself. The phone's role shrinks to launching a Custom Tab (never a WebView) at `GET /oauth/google/start` and being redirected back via `assistantapp://oauth-complete` once the backend has completed the exchange.

**Why:** a confidential client shouldn't be reduced to a public-client PKCE flow just because that's the more commonly documented mobile pattern — PKCE exists for clients that *can't* hold a secret safely, and this backend can. What's still worth reusing from the phone-side-PKCE playbook: encrypted, TTL'd, constant-time-compared CSRF `state` tracking on the redirect — that's general OAuth2 hygiene, not specific to which side holds the secret.
