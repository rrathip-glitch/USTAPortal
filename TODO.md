# TODO.md — outstanding work for the world-class final product

This list is what stands between today's branch (`0025e8e`, 283 tests passing, dashboard demoable on Janav-anchored seeded data) and a polished, daily-use tournament intelligence product. Items are roughly ordered by impact; the "Critical path" block is what materially changes whether the product is real or a demo.

For history of what's already shipped, see `CHANGELOG.md`. For why architectural choices are what they are, see `DECISIONS.md`.

---

## Critical path — real data plane

The product currently runs on a realistic seed anchored to Janav's real Clubspark USTA ID. Nothing else hits the live Clubspark surface because every Claude Code tool egress is Cloudflare-blocked at the IP/ASN layer (see RECON.md, ADR-001). Until one of the items below lands, the dashboard is faithful in shape but synthetic in substance.

- [ ] **Data-plane unblock — pick one.** The user has waived residential recon; alternative paths to consider, in increasing order of effort:
  - [ ] **Egress relay.** A tiny always-on process on the user's home network (Raspberry Pi, NAS, spare laptop) that the Railway / sandbox calls through over Tailscale or a signed token. Smallest possible surface — receives a GraphQL query, executes it against Clubspark from a residential IP, returns the JSON. ~150 LOC.
  - [ ] **Browser-driver-as-a-service.** Browserless.io / Browserbase / similar — pay-per-minute residential-IP Chrome. Wire into `src/fetch/clubspark_client.py` via a managed client. Cost ~$5-20/month for a daily sync cadence.
  - [ ] **Tailscale + headless browser on user's machine.** User installs a small daemon that joins a tailnet; the sandbox/Railway dyno can `tailscale ping <home>` and use it as an outbound proxy. Free, but requires the user to keep something running.
  - [ ] **Investigate Cloudflare bypass via a known-clean ASN.** Some VPS providers (low-cost EU hosts) are not on the Clubspark blocklist. One-off test: spin up a $5/month VPS, run the recon script, see if egress is allowed. If yes, that VPS becomes the relay. Cheapest route if it works.
- [ ] **Resolve Q-010 — notifications mechanism.** Currently leaning Resend (free tier, no card). Picking unblocks the alerting work below.
- [ ] **Resolve Q-011 sub-question — is Railway's egress Cloudflare-blocked too?** One-off test on a $5/month Railway service. Determines whether Railway is viable for the production deploy or whether the relay (above) is also load-bearing in production.

## Clubspark integration (lights up automatically once egress is solved)

The `FetchRouter` already dispatches to `clubspark_client.py`; methods raise `NotImplementedError` today. The TennisLink track works as a parallel demonstration of the parser → repo → sync orchestrator flow. Once the unblock lands:

- [ ] Capture real GraphQL request/response shapes for `EventList`, `TournamentData`, `Player`, `PlayerRankings`, `PlayerMatches`, and the WTN payload. Save anonymized fixtures.
- [ ] Implement `src/parse/clubspark_*.py` against captured fixtures. Mirror the TennisLink parser shape (one file per entity, fixture-driven tests).
- [ ] Implement Playwright-driven auth in `src/auth/session.py`. Today it's a skeleton that raises on `login()` — fill it in with the Auth0 Universal Login flow, storage-state save/load, and freshness check.
- [ ] Fill out `src/fetch/clubspark_client.py` to use `context.request.fetch` / `page.request.post` per ADR-001 Strategy C. Wire rate limit + cache.
- [ ] Wire Clubspark into the sync orchestrator alongside TennisLink. The router's source-preference order becomes `["clubspark", "tennislink"]` (Clubspark wins for current data; TennisLink remains the historical archive).
- [ ] Schema-drift canary test (`tests/integration/test_schema_drift.py`) — run nightly against one known endpoint and fail loudly when the response shape diverges.
- [ ] First green end-to-end run that overwrites the seeded opponents/draws/matches with real Clubspark data, keyed on Janav's real USTA ID.

## UI — bracket visualization and charts

The current UI renders cards, lists, and a horizontal "your path" strip. The biggest visible delta to a world-class product is real bracket visualization and time-series charts.

- [ ] **Interactive bracket on `/draws/{id}`.** SVG-rendered single-elimination bracket. Lines connect each match to the next round. Click a slot to inline-expand the scouting card. Highlight Janav's path. Adapt to draw size (4 / 8 / 16 / 32 / 64). Mobile: rotate to horizontal or collapse to a list with round headers.
- [ ] **WTN trajectory chart on `/players/{id}`.** Line chart of singles + doubles WTN over time. Pure SVG (no Chart.js dependency — keep the page light). Annotate major tournament dates.
- [ ] **Ranking trajectory chart on `/players/{id}`.** Same shape as WTN, for sectional / national position. Inverted axis (lower number = better).
- [ ] **Win-rate-by-month sparkline on the dashboard.** A 12-month strip of W-L pills, color-coded.
- [ ] **Tournament map.** A simple US map (or Florida-focused for Janav) showing upcoming tournament locations. SVG of state outlines, dots for tournaments.
- [ ] **Calendar view.** `/calendar` route — month grid with tournament events.

## UI — polish pass

- [ ] Empty-state illustrations (SVG, hand-drawn feel) replacing the current text-only empty states.
- [ ] Loading skeletons for slow routes (`/sync` while a background sync runs).
- [ ] Dark mode toggle via `prefers-color-scheme` + a manual override stored in localStorage.
- [ ] Print stylesheet for `/draws/{id}` — produces a single-page tournament briefing the player can stuff in their racket bag.
- [ ] Better typography hierarchy: more variance between page titles, section heads, and body. Currently the page is too flat.
- [ ] Color-contrast audit (WCAG AA minimum). The current green/white may fail on the rating chips.
- [ ] Player photo support. Optional `photo_url` on `Player`; the seeder populates a placeholder; if real photos appear in the Clubspark feed, the schema is already ready.
- [ ] Search across players and tournaments. A small input in the header that does a LIKE query against the local DB.
- [ ] Keyboard shortcuts: `g d` go to dashboard, `g t` tournaments, `/` focus search.

## Intelligence depth

The current enrichments (h2h, form, strength_of_draw, expected_outcome) are computed. What's missing is more inferences and the connective tissue that makes scouting feel real.

- [ ] **Surface preference inference.** From a player's match history, compute their win rate by court surface (hard vs clay). Show on scouting card.
- [ ] **Performance by round.** Does the player lose early or beat seeds? Quantify and visualize.
- [ ] **Common opponents finder.** For an upcoming opponent, list the players both have faced and compare scorelines. Often the most useful pre-match data point.
- [ ] **Streak / momentum indicator.** Current form module returns the streak; surface it as a glanceable chip on every player card.
- [ ] **Coaching notes.** A free-text field per player (`coach_notes` column) editable from the scouting card. Plain Markdown, persists locally.
- [ ] **Match journal.** Post-match form for Janav to record "how it felt," what worked, what didn't. Free text + a 1-5 self-rating. Drives a long-term retrospective.
- [ ] **Pre-match scouting brief generator.** Combines opponent stats, h2h, common opponents, and recent form into a one-page printable PDF or HTML.

## Sync robustness

- [ ] **Incremental sync.** Today `usta sync` re-fetches everything for the configured player. Track `last_fetched_at` per entity and skip recently-fetched rows unless `--force`.
- [ ] **Scheduler.** Either a Railway cron service or an in-process `apscheduler` job. Daily 6am sync is a reasonable default.
- [ ] **Notify on diff.** When sync detects a new opponent in an upcoming draw, or a schedule change, fire a notification. Hooks into the Resend / SMTP decision (Q-010).
- [ ] **Retry-from-checkpoint.** Long syncs that partially fail today restart from scratch. Persist the partial state and resume.
- [ ] **Sync log retention.** `sync_runs` grows unboundedly. Add a retention policy (keep 90 days of full logs, summary-only beyond that).
- [ ] **Per-source health.** The `/health` endpoint reports `db: connected, last_sync: <time>` — add `tennislink: ok|blocked|error` and `clubspark: ok|blocked|error` so the dashboard shows source-level status.

## Notifications

- [ ] Decide Q-010 (Resend vs SMTP).
- [ ] `src/notify/` module with a single `send(subject, body, to)` interface; backends swap behind it.
- [ ] Email templates: tournament reminder day-before, new draw posted, schedule change, sync failure, weekly digest.
- [ ] Notification preferences page at `/settings/notifications`.
- [ ] Tests with the backend mocked.

## Reports and exports

- [ ] **PDF scouting brief** per draw via WeasyPrint (Python, pure HTML/CSS → PDF, mature). Endpoint `/draws/{id}/brief.pdf`.
- [ ] **Calendar export** `/calendar.ics` — every tournament Janav's entered in, plus match schedules once known.
- [ ] **CSV export per draw** for parents who want to drop into a spreadsheet.
- [ ] **Season summary email** — fire monthly with W-L, ranking change, tournaments played, notable wins.

## Production readiness

- [ ] **Actually deploy to Railway** and resolve egress (see Critical path). Verify `/health` returns 200 from the deployed instance.
- [ ] Persistent volume attached at `/data`. Verify it survives a redeploy.
- [ ] Secrets in Railway env (`USTA_USERNAME`, `USTA_PASSWORD`, `RESEND_API_KEY`).
- [ ] Custom domain.
- [ ] Backup strategy. SQLite is one file; nightly backup of `usta.db` to S3 / R2 / a Railway volume snapshot.
- [ ] **Observability.** Loguru is configured; add a Sentry (or BetterStack) sink for prod-only error reporting.
- [ ] Performance: page-load profile. Most routes should render < 100ms with the seeded data; anything slower needs an index.

## Sharing and multi-user

- [ ] **Magic-link auth** for parents / coach. Resend sends a signed link, the link sets a session cookie. No passwords.
- [ ] Read-only mode for shared viewers (coach can't trigger `/sync` or edit notes).
- [ ] Per-match comment thread (coach adds a note Janav reads).
- [ ] Coach annotations on opponent cards.
- [ ] Signed share-link per draw (e.g., to send to a parent at the courtside) that doesn't require login.

## Mobile experience

- [ ] **PWA manifest** + service worker. Install to home screen on iOS/Android.
- [ ] **Offline mode.** Service worker caches the last-synced data; the dashboard renders offline.
- [ ] Mobile-specific UX: swipe between opponents on the draw detail page, pull-to-refresh on the dashboard.
- [ ] Push notifications via Web Push (requires HTTPS, in scope for the Railway deploy).

## Quality and testing

- [ ] **Coverage targets per SPEC.** 90% on `src/parse/`, `src/enrich/`, `src/models/`; 70% on `src/fetch/`, `src/auth/`, `src/store/`. Add `pytest --cov` and fail CI below thresholds.
- [ ] **Mypy strict in CI gating.** Already configured; ensure the workflow fails on any new mypy errors.
- [ ] **Anonymized fixture set covering every entity** (per Phase 4 of the original SPEC). For TennisLink the fixtures are committed; for Clubspark they wait on real captures.
- [ ] Smoke test against a captured "known draw" — end-to-end pipeline assertion that DB hashes match a committed snapshot.
- [ ] Property tests on TennisLink parsers (currently fixture-driven only). Generate plausible bracket HTML and confirm the parser never crashes.
- [ ] CSRF token on POST `/sync` (currently anyone hitting the deployed instance can trigger a sync).
- [ ] Security audit: HTML escaping in Jinja (auto), SQL parameterization (already), input validation on path params (mostly there — sweep for gaps).
- [ ] Run pytest in parallel (`pytest-xdist`). Currently 283 tests in ~9s; could halve.

## Accessibility (WCAG AA target)

- [ ] Keyboard navigation: every interactive element reachable with Tab, visible focus rings everywhere.
- [ ] Semantic HTML audit: ensure cards use the right elements (`<article>`, `<section>`), tables have `<th>` headers, lists are real `<ul>`/`<ol>`.
- [ ] Screen reader labels on chips and icons.
- [ ] Color contrast audit — `npm install` of `pa11y` and run it against `localhost:8000`.
- [ ] Respect `prefers-reduced-motion`.

## Documentation maintenance

- [ ] **Realign SPEC.md.** Sections 4 (Reconnaissance) and 13 (Roadmap) still describe Strategy A / Phase boundaries that the pivot has obsoleted. Surgical edit, not a rewrite — the spec's substance is mostly right.
- [ ] **Architecture diagram** in `docs/architecture.svg` (or PNG). One page, source-to-database flow, included in README.
- [ ] **Demo video / GIF.** 60 seconds of the seeded dashboard in action. Embedded in README. Useful for sharing the project state.
- [ ] **"How I use this" guide** — `docs/usage.md`, the user's own playbook for tournament prep with the portal.
- [ ] Migrate `RESEARCH.md` findings that are now obsolete (community-suggested Strategy A) into a "Historical" subsection.

## Developer experience

- [ ] **Pre-commit hooks** (`pre-commit` framework): ruff, mypy, pytest -k smoke, no-secret-detection. Run on staged files only.
- [ ] **Makefile or `just` recipes** for common ops (`make dev`, `make test`, `make seed`, `make deploy`).
- [ ] **Storybook-like component preview**. A `/__components` route in development that renders every Jinja partial with sample data. Speeds up UI iteration.
- [ ] **Faster local seed**. The current seeder runs in ~1s; that's fine. But add `--reset` flag to drop the DB first instead of upserting.

## Cross-cutting

- [ ] Address QUESTIONS.md items as the user responds (Q-010, Q-011, Q-016).
- [ ] Run `scripts/update_canonical_docs.py` at session boundaries to catch doc drift.
- [ ] Keep `STATE.md` snapshot timestamp current per session.
- [ ] Bump version on each meaningful release (currently `0.1.0` in `pyproject.toml`); cut a git tag.

---

## Recently shipped (for context — full history in CHANGELOG.md)

- Bootstrap (repo scaffold, canonical doc set, Railway config, CI, dev seeder).
- Passive + live recon. Cloudflare IP/ASN block diagnosed; ADR-001 filed Accepted as Strategy C.
- Multi-source FetchRouter: TennisLink httpx client (real) + Clubspark stub (deferred).
- TennisLink: 4 parsers, 7 captured fixtures, 45 tests, sync orchestrator wiring, integration tests. Frozen-post-2018 finding documented.
- All four enrichments: head-to-head, recent form, strength-of-draw, expected outcome (Elo-from-WTN with confidence tiers).
- Score parser with hypothesis property tests; handles tiebreaks, retirements, walkovers, defaults, pro-sets, match tiebreaks.
- Seven repositories with full CRUD + tests against in-memory DB. Schema v2 with idempotent migration.
- Sync-run persistence: `sync_runs` table, `SyncRunRepository`, `usta sync-log` CLI, `/sync` UI surfacing status + recent runs + captured log.
- UI: dashboard, tournaments list/detail, draw detail with bracket-path + expected-outcome bars, player card, h2h, sync. Mobile-first CSS. htmx-powered sync button.
- Seeder anchored to Janav's real Clubspark USTA ID (`971BA48D-A2EA-4FB7-8305-F42EA466F6DF`) so the row aligns with real data once egress is solved.
- Anonymizer for fixtures, CLI commands, raw cache writer with header redaction.
- 283 tests passing, 1 skipped (Playwright manual).
