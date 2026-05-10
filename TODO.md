# TODO.md — prioritized backlog

Live items. Completed items move to CHANGELOG.md and out of this file.

## Now blocking

- [ ] **Q-011 (top priority)** — user re-runs `scripts/live_recon.py` from a residential egress so that authenticated Clubspark / WTN GraphQL traffic can be captured. Until this happens, ADR-001's Strategy C is filed but unverified against real data-plane responses, and the Clubspark fetch layer cannot be exercised. Sub-question (b): confirm whether Railway's egress is also Cloudflare-blocked, tracked separately ahead of any Phase 4 deploy.
- [ ] **Q-010** — pick the notifications delivery mechanism (SMTP relay vs transactional API; current recommendation in QUESTIONS.md is Resend). Resolution unblocks the notification work referenced in SPEC.md.

## Phase 0 — Reconnaissance

Open items remaining after the 2026-05-10 live-recon attempt:

- [ ] Re-run live recon from a residential egress (gated on Q-011).
- [ ] Populate API_CONTRACTS.md with confirmed Clubspark GraphQL queries (variables, response shapes).
- [ ] Confirm WTN exposure pathway against a real captured payload (resolves Q-003 in full; the leading hypothesis is documented in RECON.md).
- [ ] Capture two anonymized fixtures per Clubspark entity into `tests/fixtures/`.

## Phase 1 — Core pipeline

Scaffolding can proceed against mocked GraphQL responses; live validation is gated on Phase 0 completion.

- [ ] Implement `src/auth/session.py` per ADR-001 (Playwright Universal Login flow capturing storage state).
- [ ] Implement `src/fetch/client.py` around `BrowserContext` as the IO primitive, with the rate limiter and raw-cache write.
- [ ] Implement Clubspark parsers in `src/parse/` per entity once contracts land — score parsing is done (see CHANGELOG 2026-05-10).
- [ ] Implement repositories in `src/store/repositories.py`.
- [ ] Implement sync orchestrator (the `usta sync` CLI command).
- [ ] Schema-drift canary test (`tests/integration/test_schema_drift.py`).

## Phase 1.5 — TennisLink track

The pragmatic v1 data plane while Clubspark is deferred. Owned by the TennisLink agent in the current wave.

- [ ] TennisLink parsers for the reachable surfaces: tournaments list, draws, match results.
- [ ] Sync wiring that runs against TennisLink instead of (or alongside) the Clubspark fetch layer.
- [ ] Janav profile sync sourced from TennisLink (account-bound view, with NTRP-era data where the new system exposes nothing yet).
- [ ] Anonymized TennisLink fixtures captured into `tests/fixtures/tennislink/`.

## Phase 2 — Intelligence

- [ ] `src/enrich/h2h.py` + tests.
- [ ] `src/enrich/form.py` + tests.
- [ ] `src/enrich/expected_outcome.py` (Elo from WTN) + tests.

Strength-of-draw is done — see CHANGELOG 2026-05-10.

## Phase 3 — UI

Routes to build out (templates and tests per route):

- [ ] `/` dashboard.
- [ ] `/tournaments` list.
- [ ] `/tournaments/{id}` detail.
- [ ] `/draws/{id}` bracket view with inline scouting cards.
- [ ] `/players/{id}` scouting card.
- [ ] `/h2h/{a}/{b}` head-to-head deep dive.
- [ ] `/sync` manual trigger + status.
- [ ] `/admin/raw/{hash}` raw cache inspector.

## Phase 4 — Hardening

- [ ] Anonymized fixture set covering every entity.
- [ ] Full unit + integration test pyramid green.
- [ ] Smoke test against captured "known draw".
- [ ] Railway deploy with persistent volume attached and egress posture verified against Cloudflare.
- [ ] Documented credential rotation procedure verified end-to-end.
- [ ] Logging level + structured fields tuned for production triage.

## Phase 5 — Optional

- [ ] UTR cross-reference (if obtainable for the user's account).
- [ ] Elo-style "expected outcome" tuning vs realized results.
- [ ] Mobile-friendly polish pass.
- [ ] Multi-user / shared dashboards for coach + parent.

## Cross-cutting (any phase)

- [ ] Address open QUESTIONS.md items as the user responds.
- [ ] Run `scripts/update_canonical_docs.py` at session boundaries.
- [ ] Keep SPEC.md aligned with reality; intentional drift is fine, accidental drift is not.

## Completed

The following high-water-mark items are done; consult CHANGELOG.md for the full history.

- Bootstrap: repo scaffold, canonical doc set, CI, Railway deploy config, dev-data seeder (2026-05-10).
- Passive recon: anti-bot posture characterized, Auth0 OIDC confirmed, Clubspark TLS/Cloudflare block diagnosed (2026-05-10).
- Live recon attempt: Cloudflare 403 reproduced from real Chromium, IP/ASN diagnosis confirmed, ADR-001 promoted to Accepted as Strategy C with residential-egress rider (2026-05-10).
- Score parser: `parse_score`, `format_score`, `infer_winner` covering all tennis-score shapes including tiebreaks, retirements, walkovers, defaults, pro-sets, 10-point match tiebreaks (2026-05-10).
- Strength-of-draw enrichment: pure-function aggregator with field and projected-path aggregates, ten passing tests (2026-05-10).
