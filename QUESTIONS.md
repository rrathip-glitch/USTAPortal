# QUESTIONS.md — open questions for the user

Each question gets a short ID (Q-NNN) so other docs can reference it. Resolved questions move out of this file into the doc where the answer now lives (RECON.md, DECISIONS.md, DATA_MODEL.md, etc.) and the resolution is noted in CHANGELOG.md.

Questions are surfaced here only when the answer materially changes scope, architecture, or UX. Preferences inside an already-approved scope get picked and documented, not asked.

---

## Open

- **Q-011 — Residential egress for recon and sync (TOP PRIORITY).** Live recon from this development environment (egress IP `34.58.203.104`, GCP) hit a hard Cloudflare 403 on `playtennis.usta.com` and on every Clubspark host (`prod-us-kube.clubspark.io`, `prd-itf-kube.clubspark.pro`, `worldtennisnumber.com`) before login could be attempted. Real Chromium 141 with anti-detection flags reproduces the block, confirming the rule is on IP/ASN not TLS fingerprint. **The user must re-run `scripts/live_recon.py` from a residential network** (their own laptop, or via a port-forward / SSH tunnel through their home router) to capture authenticated GraphQL traffic. Without this, ADR-001's chosen Strategy C is filed but **unverified against real data-plane traffic**, and Phase 1 (the fetch layer) has no captured GraphQL contracts to build against. Sub-questions: (a) Will the user run recon from their machine with the existing script? (b) For the eventual Railway production deploy, are Railway's egress IPs also Cloudflare-blocked? If yes, we need a residential-egress proxy story before Phase 4 — track as a follow-up after (a) resolves.

## Newly opened (follow-up from Q-008 resolution)

- **Q-010 — Notification delivery mechanism.** Should we send email via (a) an SMTP relay configured by env vars (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFY_TO`), or (b) a transactional email API (Resend, Postmark, Mailgun, SendGrid)? The SMTP route is zero-cost and works from Railway out of the box but is fragile (Railway's egress to common SMTP providers is sometimes blocked). The API route is more reliable but requires a free-tier signup. Recommend (b) Resend (3k emails/month free tier, no credit card). Open.

---

## Resolved (2026-05-10) — user inline answers preserved verbatim

- **Q-001 — Live recon authorization and credentials.** **User:** "Permission Granted and credentials stored." **Effect:** authenticated recon may proceed. Credentials live in `.env.example` (see SECURITY notice below).
- **Q-002 — Hosting target.** **User:** "Railway is good." **Effect:** Railway + Nixpacks is canonical; `Procfile`, `railway.json`, `nixpacks.toml`, `Dockerfile` (fallback) committed.
- **Q-003 — Doubles WTN scope.** **User:** "Do what is most efficient and data complete." **Effect:** capture both singles and doubles WTN whenever exposed. `WTNSnapshot.type` already supports both.
- **Q-004 — Multi-user vs single-user.** **User:** "Single user for now." **Effect:** single-user v1 (Janav). Parents/coach are read-only viewers. Multi-user is Phase 5.
- **Q-005 — UI framework.** **User:** "Make sure you do whatever makes it mobile and desktop friendly as a high priority." **Effect:** FastAPI + Jinja2 + responsive CSS chosen (Streamlit rejected). Mobile-first templates landed in `src/ui/templates/`.
- **Q-006 — Junior vs adult age scope.** **User:** "Junior only scope." **Effect:** v1 covers junior tournaments only. `age_category` field stays general so adult expansion is non-breaking later.
- **Q-007 — Default scouting-card fields.** **User:** (no override). **Effect:** spec defaults stand — ranking, WTN singles + doubles, last 8 results, h2h, common opponents, surface preference.
- **Q-008 — Notifications.** **User:** "Yes use the usta email for notifications." **Effect:** sync-failure alerts and meaningful state changes (new draw posted, schedule change) go to the USTA email address configured for the account. Delivery mechanism tracked as Q-010.
- **Q-009 — Anonymization in fixtures.** **User:** "Do not anonomize." **Effect:** fixtures may be committed with real names and USTA IDs. The anonymizer (`tests/anonymize.py` + `usta anonymize` CLI) stays as an opt-in tool. TESTING.md is updated to reflect this.

---

## SECURITY notice — credentials in git history

User committed real USTA credentials into `.env.example` (commit `aa88f32`) on 2026-05-10. This file is tracked in git and visible to anyone with read access to the repository. Recommended remediation:

1. **Rotate the USTA password immediately.** The current password should be considered compromised.
2. After rotation, move new credentials to `.env` (already in `.gitignore`).
3. Reset `.env.example` back to the empty template.
4. Scrub git history with `git filter-repo` (or BFG) and force-push so the credentials no longer appear in any reachable commit.

Until remediation completes, treat the repo as if its credential contents are public.
