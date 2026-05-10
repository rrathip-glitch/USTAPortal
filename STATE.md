snapshot: 2026-05-10T00:00:00Z

# STATE.md — live project status

## Phase

**Phase 0 (Reconnaissance) — partially complete; data-plane capture BLOCKED on environmental egress.** ADR-001 is filed (Accepted, Strategy C). Phase 1 can begin scaffolding the Strategy C fetch shape, but cannot validate against real GraphQL contracts until the user re-runs `scripts/live_recon.py` from a residential egress (Q-011).

## Active workstreams

_None._

## Recently completed

- **Live recon attempt (recon agent, 2026-05-10).** Ran `scripts/live_recon.py` against `playtennis.usta.com` with credentials from `settings`, Chromium 141 via Playwright in both legacy headless and Xvfb-backed non-headless modes, with full anti-detection flags (`--disable-blink-features=AutomationControlled`, `navigator.webdriver` hider, Chrome-141 UA, US locale + ET timezone). **Cloudflare 403'd the very first GET on `playtennis.usta.com/`** (cf-ray `9f9b89cf9e96c0a8-ORD`). Login was never reached. Side-by-side host-reachability probe (`data/recon/2026-05-10-live/host_reachability.json`) confirms Auth0 (`account.usta.com`) is reachable from this environment but every Cloudflare-fronted Clubspark host returns 403. Diagnostic: outbound IP `34.58.203.104` (GCP) is on Cloudflare's datacenter blocklist for the Clubspark edge — reproduces from passive curl/urllib too. Per the recon charter, the script halted on bot-wall and did not attempt evasion. **ADR-001 was filed Accepted as Strategy C** (Playwright-resident requests) with the operational rider that recon and sync must run from a residential egress; rationale anchored on Strategy C being strictly more general than A-prime (testable later as a perf optimization once a residential capture proves it). Updated: RECON.md (Status flipped to BLOCKED, new "Findings (live recon attempt, 2026-05-10)" section, host reachability matrix), API_CONTRACTS.md (Anti-bot posture section refined to distinguish IP/ASN vs TLS-fingerprint blocking), DECISIONS.md (ADR-001 → Accepted with full live-recon evidence and consequences), QUESTIONS.md (new Q-011 top-priority: user must re-run recon from a residential egress), CHANGELOG.md.
- **Score parser (parser agent, 2026-05-10).** Implemented `parse_score`, `format_score`, and `infer_winner` in `src/parse/matches.py` covering standard sets, tiebreaks, retirements, walkovers, defaults, unfinished, pro-sets, and 10-point match tiebreaks (both bracket and `1-0(L)` shapes). Added 16 concrete + 4 property tests in `tests/unit/test_score_parser.py` plus a `valid_score_string` Hypothesis strategy in `tests/strategies.py`. ruff and mypy clean; 25 tests passing.
- **Bootstrap (this session, 2026-05-10).** Repository scaffolded: directory structure, Python source stubs, Railway deployment config (Procfile, railway.json, nixpacks.toml, Dockerfile), test scaffolding, CI workflow, `.claude/` subagent charters and slash commands, self-improvement script (`scripts/update_canonical_docs.py`), and the canonical doc set (SPEC, AGENTS, DATA_MODEL, RECON, API_CONTRACTS, RUNBOOK, TESTING, RESEARCH). Two parallel subagents authored SPEC.md (~6,800 words across 16 sections) and RESEARCH.md (~2,500 words across 5 axes). RESEARCH.md surfaced the leading hypothesis — `playtennis.usta.com` is a Clubspark deployment with a documented GraphQL endpoint, suggesting we target GraphQL rather than HTML scraping.

## Next up

1. **Q-011 — User to re-run `scripts/live_recon.py` from a residential egress** (their own laptop, or a tunnel through their home network). Without this we cannot capture real GraphQL contracts. The script is ready as-is; it loads credentials from `.env` and writes to `data/recon/2026-05-10-live/` (or whatever timestamped subdir the next run picks). Top-priority blocker for any further data-plane work.
2. Phase 1 scaffolding (no live data needed). Build the Strategy C fetch shape — `BrowserContextPool`, `fetch_via_context`, raw-cache write — using mocked GraphQL responses based on community-documented `EventList` / `TournamentData` query names. Keep the parser API stable so swapping in real captured queries later is one-line per entity.
3. After residential recon completes: lock the GraphQL contracts in API_CONTRACTS.md, write parsers, bind to the existing repositories.

## Open blockers

- **Q-011 (top priority): live data-plane recon blocked on residential egress.** This environment's GCP egress is Cloudflare-blocked at IP/ASN level. ADR-001 is filed Accepted (Strategy C) on the strength of consistent live + passive blocking evidence, but no real GraphQL captures exist yet. See QUESTIONS.md Q-011.
- **Need to confirm WTN exposure pathway.** Tracked as Q-003. The leading hypothesis (research-backed) is that WTN is in the same Clubspark GraphQL surface as tournament data; residential recon validates.

## Recent decisions awaiting closure

- ADR-001 (Extraction Strategy) — **Accepted (2026-05-10) — Strategy C** with residential-egress rider. Filed.
- ADR-002 (Storage layer: SQLite raw vs. SQLAlchemy ORM) — **Accepted** as raw SQLite for v1.
- ADR-004 (future): `curl_cffi` bulk-fetch optimization on top of Strategy C. To be filed once residential recon captures a bearer token whose lifetime, audience, and scope can be inspected.

## Doc snapshot health

- SPEC.md: current as of bootstrap. Will need refresh after ADR-001 lands.
- RECON.md: a plan, not findings. Replace with findings once Phase 0 runs.
- API_CONTRACTS.md: all rows hypothesized. Replace with confirmed entries after recon.
- DATA_MODEL.md: aligned with Pydantic models in `src/models/`.
- DECISIONS.md: one Accepted ADR (storage), one Proposed (extraction).
- TODO.md: bootstrap items archived; Phase 0/1 items listed.
