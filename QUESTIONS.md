# QUESTIONS.md — open questions for the user

Each question gets a short ID (Q-NNN) so other docs can reference it. Resolved questions move out of this file into the doc where the answer now lives (RECON.md, DECISIONS.md, DATA_MODEL.md, etc.) and the resolution is noted in CHANGELOG.md.

Questions are surfaced here only when the answer materially changes scope, architecture, or UX. Preferences inside an already-approved scope get picked and documented, not asked.

---

## High priority — block forward progress

- **Q-001 — Live recon authorization and credentials.** To start Phase 0 recon, a follow-up session needs: (a) USTA credentials in `.env`, (b) the user's explicit authorization for live network activity against `playtennis.usta.com` and the `prod-us-kube.clubspark.io` GraphQL endpoint. This bootstrap session did NOT perform any live fetches — RECON.md is a plan, not findings. Open.
Permission Granted and credentials stroed.

- **Q-002 — Hosting target confirmed.** The deployment config assumes Railway with Nixpacks (with a Dockerfile fallback). The user has prior Railway experience, so this is the strong default. If the user wants to deploy somewhere else (Fly.io, Render, self-hosted), the build files change. Open — confirm Railway is correct.
Railway is good

## Medium priority — affect product shape

- **Q-003 — Doubles WTN scope.** Research suggests the Clubspark surface co-locates singles and doubles WTN in player payloads, but it's unconfirmed. If doubles WTN requires a separate authenticated call (or isn't available at all), the data-model and intelligence-layer designs adjust. Open — recon resolves.
Do what is most efficient and data complete

- **Q-004 — Multi-user vs single-user mode for v1.** The spec currently scopes v1 as single-user (one player's tournaments). The user mentioned wanting parents/coach to read the dashboard. Reading is fine without multi-user; *configuring whose tournaments to track* is what would require multi-user. Confirm: is v1 single-user (Janav's tournaments only), with parent/coach as read-only viewers? Open — leaning yes.
Single user for now

- **Q-005 — UI framework: FastAPI + Jinja2 vs Streamlit.** SPEC.md recommends FastAPI + Jinja2 (better Railway story, better mobile, cleaner URLs). Streamlit is faster to prototype but trickier to deploy, weaker on auth, and less mobile-friendly. Open — confirm before Phase 3 starts.
Make sure you do whatever makes it mobile and desktop friendly as a high priority

- **Q-006 — Junior vs adult age scope.** Janav is presumably a junior player. Should the dashboard support tracking him into adult tournaments as he ages, or is the v1 scope strictly junior tournaments? Affects how `age_category` is modeled and how cross-category matches roll up. Open.
Junior only scope

## Low priority — UX preferences worth confirming

- **Q-007 — Default scouting-card fields.** The spec lists ranking, WTN singles + doubles, last 8 results, h2h, common opponents, surface preference. Are there fields the user specifically wants featured (or de-emphasized)? Could be answered any time. Open.

- **Q-008 — Notifications.** Does the user want email/SMS/push notifications for sync failures, new draws posted, schedule changes? v1 currently has none — the dashboard `/health` page is the only signal. Open.
Yes use the usta email for notifications

- **Q-009 — Anonymization of own data in fixtures.** The default in TESTING.md is to anonymize even the primary user's data in committed fixtures. The user can opt in to keeping their own name/ID intact (everyone else stays anonymized). Open — pick one.
Do not anonomize

---

## Resolved

> _Empty. As questions are answered, they move here with the resolution and link to where the answer now lives._
