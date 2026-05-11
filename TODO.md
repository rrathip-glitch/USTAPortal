# TODO.md — outstanding work for the rankings-first wave

This list reflects the 2026-05-11 strategic pivot: the project's near-term goal is to land a clean, real-data view of the U12 boys national rankings (and U10 if reachable), with Janav Thasen highlighted, and to enrich every player ranked at or above him with their WTN profile. Everything else is paused until that pipeline is live end-to-end.

For history of what's already shipped, see `CHANGELOG.md`. For the architectural reasoning behind the pivot, see `DECISIONS.md` (ADR-006) and `STATE.md` (current wave snapshot).

---

## Critical path — rankings pipeline (v1.0)

These items must land before v1.0 is declared done. They are ordered to roughly match dispatch order; several can run in parallel once the data plane is settled.

- [ ] **Data plane decision.** TBD pending wave-1 results, see STATE.md. The Orchestrator picks the unblock path (egress relay, browser-driver-as-a-service, clean-ASN VPS, or successful bypass) once the recon and bypass sibling agents return.
- [ ] **U12 boys national rankings — fetch.** Resolve the canonical USTA ranking-list URL/endpoint for U12 boys national, capture the request/response shape, save an anonymized fixture in `tests/fixtures/`.
- [ ] **U12 boys national rankings — parse.** New module under `src/parse/` consuming the captured fixture. Output: a list of `Ranking` rows (rank, player_name, player_id, section, points, ties-breaks if present). Fixture-driven tests with 90%+ coverage on the parser itself.
- [ ] **U12 boys national rankings — persist.** Schema migration adding a `rankings` table (composite key: ranking_list_id + rank). `RankingRepository` with upsert semantics and a round-trip test. Idempotent re-runs.
- [ ] **U10 boys national rankings — fetch + parse + persist.** Same pipeline as U12 if the list is reachable; if USTA does not publish a U10 national list, mark the item closed with a one-line note linking to the evidence.
- [ ] **WTN profile crawl.** For every player at rank <= Janav's rank in the U12 boys national list, fetch their player profile page, parse out WTN singles and WTN doubles (with timestamp and confidence if present), and persist into the existing `Player` / WTN store. Honor a polite rate limit; cache raw payloads under `data/raw_cache/` per existing convention.
- [ ] **Rankings display page.** New route `/rankings/u12-boys-national` (and `/rankings/u10-boys-national` if U10 is reachable). Sortable table, columns: rank, name, section, points, WTN-singles, WTN-doubles. Janav's row is visually highlighted. Mobile-first CSS consistent with the rest of the UI.
- [ ] **Sync wiring.** A new `usta sync-rankings` CLI command. The sync orchestrator gains a `rankings` step; runs alongside the existing tournaments/draws/players/matches steps. Per-source health surfaces on `/sync`.
- [ ] **Tests.**
  - Parser fixture tests against the captured anonymized rankings list.
  - Repository round-trip test (write a `Ranking` set, read it back, assert ordering preserved).
  - UI integration test that hits `/rankings/u12-boys-national` against seeded ranking data and asserts Janav's row is rendered and highlighted.
  - End-to-end sync test against a saved fixture: run `usta sync-rankings` with the fetcher pointed at a local fixture server; assert the DB ends in the expected state.

## Critical path — supporting

- [ ] **Resend notification module.** Done in parallel this wave by the notify sibling agent. Strike when that agent confirms green on its slice (module shipped, tests passing, dependency wired through `src/notify/`).
- [ ] **Cloudflare bypass agent role formalized.** Charter at `.claude/agents/bypass.md`. Created in wave 2 after wave-1 recon results land.
- [ ] **Rankings agent role formalized.** Charter at `.claude/agents/rankings.md`. Created in wave 2; will be dispatched per (age category, scope) pair.

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
- **pytest** — currently 283 passing + the new Resend tests landing this wave. Every new module ships with tests; the pipeline above adds at minimum a parser test, a repository test, a UI integration test, and an end-to-end sync test.
- **Coverage** — unchanged targets: 90% on `src/parse/`, `src/enrich/`, `src/models/`; 70% on `src/fetch/`, `src/auth/`, `src/store/`.
- **Security notice from QUESTIONS.md still stands.** Credentials are committed in the working tree; rotation is pending. Do not assume the threat model has changed.

## Recently shipped (context only)

See `CHANGELOG.md` for the full history of what landed before this pivot — bootstrap, recon, TennisLink integration, all four enrichments, repositories, sync orchestrator, seeded UI, and 283 passing tests. Treat that work as the foundation the rankings pipeline now builds on; do not re-enumerate it here.
