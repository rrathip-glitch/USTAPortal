# QUESTIONS.md — open questions for the user

Each question gets a short ID (Q-NNN) so other docs can reference it. Resolved questions move out of this file into the doc where the answer now lives (RECON.md, DECISIONS.md, DATA_MODEL.md, etc.) and the resolution is noted in CHANGELOG.md.

Questions are surfaced here only when the answer materially changes scope, architecture, or UX. Preferences inside an already-approved scope get picked and documented, not asked.

---

## Open

_None._

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
