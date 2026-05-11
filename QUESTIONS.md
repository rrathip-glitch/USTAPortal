# QUESTIONS.md — open questions for the user

Each question gets a short ID (Q-NNN) so other docs can reference it. Resolved questions move out of this file into the doc where the answer now lives (RECON.md, DECISIONS.md, DATA_MODEL.md, etc.) and the resolution is noted in CHANGELOG.md.

Questions are surfaced here only when the answer materially changes scope, architecture, or UX. Preferences inside an already-approved scope get picked and documented, not asked.

---

## Open

- **Q-017 — What is Janav's USTA player GUID in the new commingled-ES tournament index?** We have three identifiers for Janav: his Clubspark GUID (`971BA48D-A2EA-4FB7-8305-F42EA466F6DF`, from the pre-breakthrough Clubspark URL recon), his CoreTennis id (`203938`), and his UTR id (`3059480`). What we do **not** have is a GUID that correlates against the new anonymous tournament index hits returned by `https://prod-api-playtennis.usta.com/playtennis/tournaments/query`. The hits themselves do not surface Janav directly because the U12 events at L3 are stored under `levelCategories` with `level=junior`, and the anonymous endpoints do not expose per-player rosters. **Next step:** search the tournament hits for the four real events Janav played (per RECON.md "Janav Thasen — real match history") and reverse-engineer his id from a draw response. This step is gated on the per-id detail endpoints, which return 403 / "Missing Authentication Token" anonymously — so completing Q-017 requires either (a) auth, (b) a CoreTennis cross-walk from the event names back to USTA tournament ids that the anonymous API exposes, or (c) inspection of the AEM SPA's runtime requests for any anonymous detail surface we have not yet discovered.

## Newly opened (follow-up from Q-008 resolution)

- **Q-010 — Notification delivery mechanism.** Should we send email via (a) an SMTP relay configured by env vars (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFY_TO`), or (b) a transactional email API (Resend, Postmark, Mailgun, SendGrid)? The SMTP route is zero-cost and works from Railway out of the box but is fragile (Railway's egress to common SMTP providers is sometimes blocked). The API route is more reliable but requires a free-tier signup. Recommend (b) Resend (3k emails/month free tier, no credit card). Open.

---

## Resolved

- **Q-011 — Residential egress for recon and sync.** **Resolved 2026-05-11 — superseded by ADR-006.** The 2026-05-11 breakthrough found an anonymous, Cloudflare-free AWS API Gateway at `https://prod-api-playtennis.usta.com` that is reachable from this environment's GCP egress. The residential-egress requirement is no longer a release blocker. Answer now lives in [RECON.md](RECON.md) "2026-05-11 breakthrough" and [DECISIONS.md](DECISIONS.md) ADR-006. Sub-question (b) — Railway egress against Cloudflare — is moot for v1 since the primary data plane is not behind Cloudflare. If the auth-walled Clubspark surface ever becomes load-bearing again, the sub-question reopens under a new ID.

## Resolved (2026-05-10) — user inline answers preserved verbatim

Each resolved question lists the doc that now owns the answer in operational form.

- **Q-001 — Live recon authorization and credentials.** **User:** "Permission Granted and credentials stored." **Effect:** authenticated recon may proceed. Credentials live in `.env.example` (see SECURITY notice below). Answer now lives in [RECON.md](RECON.md) "Findings (live recon attempt, 2026-05-10)" and in CHANGELOG 2026-05-10.
- **Q-002 — Hosting target.** **User:** "Railway is good." **Effect:** Railway + Nixpacks is canonical; `Procfile`, `railway.json`, `nixpacks.toml`, `Dockerfile` (fallback) committed. Answer now lives in [README.md](README.md) "Deploy on Railway" and [RUNBOOK.md](RUNBOOK.md) "Railway-specific notes".
- **Q-003 — Doubles WTN scope.** **User:** "Do what is most efficient and data complete." **Effect:** capture both singles and doubles WTN whenever exposed. `WTNSnapshot.type` already supports both. Answer now lives in [DATA_MODEL.md](DATA_MODEL.md) "WTNSnapshot". **Note (2026-05-11):** the UTR search endpoint (ADR-007) partly fills the per-player rating gap — it returns UTR ratings rather than WTN, but UTR is the rating axis the broader junior community now uses. True WTN remains behind the auth-walled Clubspark surface; deferred but no longer a release blocker.
- **Q-004 — Multi-user vs single-user.** **User:** "Single user for now." **Effect:** single-user v1 (Janav). Parents/coach are read-only viewers. Multi-user is Phase 5. Answer now lives in [SPEC.md](SPEC.md) (scope sections) and [TODO.md](TODO.md) Phase 5.
- **Q-005 — UI framework.** **User:** "Make sure you do whatever makes it mobile and desktop friendly as a high priority." **Effect:** FastAPI + Jinja2 + responsive CSS chosen (Streamlit rejected). Mobile-first templates landed in `src/ui/templates/`. Answer now lives in [SPEC.md](SPEC.md) UI section.
- **Q-006 — Junior vs adult age scope.** **User:** "Junior only scope." **Effect:** v1 covers junior tournaments only. `age_category` field stays general so adult expansion is non-breaking later. Answer now lives in [DATA_MODEL.md](DATA_MODEL.md) "Player" and [SPEC.md](SPEC.md) scope.
- **Q-007 — Default scouting-card fields.** **User:** (no override). **Effect:** spec defaults stand — ranking, WTN singles + doubles, last 8 results, h2h, common opponents, surface preference. Answer now lives in [SPEC.md](SPEC.md) scouting-card section.
- **Q-008 — Notifications.** **User:** "Yes use the usta email for notifications." **Effect:** sync-failure alerts and meaningful state changes go to the USTA email address configured for the account. Delivery mechanism tracked as Q-010 above. Answer now lives in [SPEC.md](SPEC.md) notifications section.
- **Q-009 — Anonymization in fixtures.** **User:** "Do not anonomize." **Effect:** fixtures may be committed with real names and USTA IDs. The anonymizer (`tests/anonymize.py` + `usta anonymize` CLI) stays as an opt-in tool. Answer now lives in [TESTING.md](TESTING.md) "Anonymized fixtures".

---

## SECURITY notice — credentials in git history

User committed real USTA credentials into `.env.example` (commit `aa88f32`) on 2026-05-10. This file is tracked in git and visible to anyone with read access to the repository. Recommended remediation:

1. **Rotate the USTA password immediately.** The current password should be considered compromised.
2. After rotation, move new credentials to `.env` (already in `.gitignore`).
3. Reset `.env.example` back to the empty template.
4. Scrub git history with `git filter-repo` (or BFG) and force-push so the credentials no longer appear in any reachable commit.

Until remediation completes, treat the repo as if its credential contents are public.
