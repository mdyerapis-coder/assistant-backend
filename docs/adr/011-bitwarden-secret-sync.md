# ADR-011: secrets sync from Bitwarden on a schedule, restart-on-change

**Status:** live, phase `00`

A separate, more tightly scoped systemd unit than the app itself pulls from Bitwarden's personal vault (`bw` CLI) roughly every 20 minutes, diffs against the current `assistant.env`, and — only if something changed — rewrites it and restarts the `assistant` service. The app itself never talks to Bitwarden and never reads live from the vault.

**Why, and the tradeoff being accepted, not hidden:** Mason is on Bitwarden's regular personal vault, not Secrets Manager (their dedicated machine-secrets product). Unlocking the personal vault non-interactively requires the master password to exist somewhere on the server — `~/.bw-sync.env`, 0600, read only by the sync unit. That file is now the single most sensitive thing on the box; treat it accordingly. This is a real, accepted limitation of the personal-vault approach, not a solved problem — revisit if Bitwarden Secrets Manager becomes available (it has a free tier for a small number of secrets and needs no master password at all). Restart-on-change rather than live in-process reload is deliberate too: it avoids a process running half with an old key and half with a new one mid-request.
