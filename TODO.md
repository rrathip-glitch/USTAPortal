# TODO.md — outstanding work for the rankings-first wave

This list reflects the 2026-05-11 strategic pivot and the 2026-05-12 vertical-slice landing: the project's near-term goal is to land a clean, real-data view of the U12 boys national rankings (and U10 if reachable), with Janav Thasen highlighted, and to enrich every player ranked at or above him with their WTN profile. The TennisLink historical pipeline is live end-to-end; the current Clubspark data path is the last remaining gap.

For history of what's already shipped, see `CHANGELOG.md`. For the architectural reasoning behind the pivot, see `DECISIONS.md` (ADR-006) and `STATE.md` (current wave snapshot).

---

## Recently shipped (2026-05-11 + 2026-05-12)

- **TennisLink rankings vertical slice live.** `src/parse/tennislink_rankings_list.py` + `usta sync-rankings` CLI + `/rankings/u12-boys-national` route render the 1,014-player Boys' 12 fixture with Janav highlight and historical-source footnote. First real USTA data in the dashboard.
- **Bright Data Web Unlocker proven end-to-end** through this sandbox: Cloudflare bypass on `playtennis.usta.com`, production ITF/WTN GraphQL reachable, real WTN data flows. Backend refactored to the verified Bearer-auth + body-key shape (9/9 tests).
- **Wave-2 proxy-infra landed.** `src/fetch/residential_proxy.py`, schema v3 (`ranking_lists` + `ranking_list_entries`), `RankingListRepository`, sync-rankings CLI step, UI route.
- **Resend notification module shipped** (Q-010 resolved). FROM-domain decision tracked as Q-012.
- **Two-session harvest verdicts.** TennisLink is historical-only across every age group and every year; Clubspark current-rankings recon is in flight against `ParticipantRankings` / `RankingsAndRatings` GraphQL types.

---

## Critical path — rankings pipeline (v1.0)

These items must land before v1.0 is declared done. Items marked done are kept for visibility; items still open are ordered roughly by dispatch order.

- [x] **Data plane decision.** Bright Data Web Unlocker — verified end-to-end through the sandbox.
- [x] **U12 boys national rankings — fetch (TennisLink, historical).** `src/parse/tennislink_rankings_list.py` against the captured 2072448 fixture.
- [x] **U12 boys national rankings — parse.** New module under `src/parse/`; fixture-driven tests landed.
- [x] **U12 boys national rankings — persist.** Schema v3: `ranking_lists` + `ranking_list_entries`. `RankingListRepository` with upsert + round-trip tests. Idempotent re-runs.
- [x] **Rankings display page.** `/rankings/u12-boys-national`. Sortable, Janav-highlight, mobile-first CSS, historical-source footnote.
- [x] **Sync wiring.** `usta sync-rankings [--list-id N] [--from-fixture path]`. Per-source health surfaces on `/sync`.
- [x] **Tests (TennisLink path).** Parser fixture tests, repository round-trip, UI integration, end-to-end CLI sync against fixture. +19 net new tests this wave.
- [ ] **Clubspark current-rankings wire-up.** Recon agent (in flight) returns the production URL + GraphQL query for live Boys' 12 national standings; plug it into `usta sync-rankings` via the Bright Data backend; swap the historical-source footnote for a live label.
- [ ] **WTN profile crawl for the displayed list.** For every player at rank ≤ Janav's rank, fetch their player profile page via the refactored Bright Data backend, parse WTN singles/doubles, persist into the existing `Player` / WTN store. Honor a polite rate limit; cache raw payloads under `data/raw/`.
- [ ] **Janav scouting card UI.** "Unranked + no WTN" treatment with TR rank 146 + sister Vihana's WTN (singles 27.97, doubles 31.55) as context. Renders gracefully when Janav is not in the displayed list (the realistic case for early-2021 historical data).
- [ ] **Name-match enrichment.** Resolve the synthetic `tl-rank:` USTA ids assigned during TennisLink ingest to real Clubspark GUIDs once the production identity surface is reachable.
- [ ] **U10 boys national rankings.** If USTA publishes a U10 national list via Clubspark, run the same pipeline; if not, close with a one-line note linking to the recon evidence (TennisLink already confirmed never-published).

## Critical path — supporting

All items here are now complete; preserved as a record of what landed this wave.

- [x] **Resend notification module.** Shipped under `src/notify/` with retry + config + 7 tests (5 original + 2 fixed for env isolation).
- [x] **Bright Data Web Unlocker backend.** Refactored to the verified Bearer-auth + body-key + POST-support shape. 9/9 tests.
- [x] **Cloudflare bypass agent role formalized.** Charter at `.claude/agents/bypass.md`.
- [x] **Rankings agent role formalized.** Charter at `.claude/agents/rankings.md`.

## Deferred — post-rankings (was previously in flight, paused pending rankings v1.0)

Everything below was active or queued before the 2026-05-11 pivot. Each item remains valuable and will resume after v1.0 of the rankings pipeline ships. Detail intentionally elided; consult `CHANGELOG.md` and pre-pivot commits if more context is needed.

- Interactive bracket SVG on `/draws/{id}`.
- WTN trajectory chart on `/players/{id}`.
- Ranking trajectory chart on `/players/{id}`.
- Win-rate-by-month sparkline on the dashboard.
- Tournament map.
- Calendar view (`/calendar`).
- Incremental sync (`last_fetched_at` per entity, `--force` flag).
- PDF scouting brief generator via WeasyPrint.
- Magic-link auth for parents / coach via Resend.
- Scheduler (daily 6am sync).
- Mobile PWA (manifest, service worker, offline mode, web push).
- Accessibility audit pass (WCAG AA — keyboard nav, semantic HTML, contrast, reduced-motion).
- Multi-user / shared read-only views, per-match comment threads, coach annotations.
- Calendar export (`/calendar.ics`).
- CSV exports per draw.
- Common-opponents finder, surface-preference inference, performance-by-round, match journal, coaching notes.
- Empty-state illustrations, loading skeletons, dark mode, print stylesheet, typography polish, photo support, header search, keyboard shortcuts.
- Pre-commit hooks, Makefile recipes, component preview route, faster local seed.
- Architecture diagram, demo video, usage guide, RESEARCH.md cleanup.

## Quality bars (still apply)

The rankings pipeline ships under the same quality bars as the rest of the codebase. No regressions on:

- **mypy strict** — clean across the tree.
- **ruff** — clean across the tree.
- **pytest** — 319 passing as of the 2026-05-12 wave-2 landing (was 283 + Resend tests pre-pivot; +19 net new from the rankings vertical slice plus the bright-data refactor and the two notify env-isolation fixes). Every new module ships with tests.
- **Coverage** — unchanged targets: 90% on `src/parse/`, `src/enrich/`, `src/models/`; 70% on `src/fetch/`, `src/auth/`, `src/store/`.
- **Security notice from QUESTIONS.md still stands.** Credentials are committed in the working tree; rotation is pending. Do not assume the threat model has changed.

## Recently shipped (context only)

See `CHANGELOG.md` for the full history of what landed before this pivot — bootstrap, recon, TennisLink integration, all four enrichments, repositories, sync orchestrator, seeded UI. Treat that work as the foundation the rankings pipeline now builds on; do not re-enumerate it here.
