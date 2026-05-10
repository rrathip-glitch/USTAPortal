# CHANGELOG.md

Append-only. Most recent at the top.

---

## 2026-05-10 — Janav-hunt harvest + realistic dev seeder

Janav-Hunt + Mock-Seed agent ran a 7-query open-web harvest on Janav Thasen and replaced the stub `scripts/seed_dev_data.py` with a realistic Boys' 12s Florida-section dev dataset. Confirmed (HIGH confidence) across two independent public sources (Tennis Recruiting Network player 1065914 and CoreTennis profile 203938): Janav is from **Weston, FL**, class of **2032 (5th grade)**, competing in the **Boys' 12s** age category — the spec's hypothesised Boys' 16s was wrong, corrected in the seeder. Probable (single-source): TRN national rank ~146 in class, year W-L 31-36, played a USTA National L3 in Wesley Chapel FL on 2026-01-17. USTA TennisLink ID could not be recovered — playtennis.usta.com pages 403'd per the Cloudflare block already documented in ADR-001. TriTennis (Delray Beach, FL) tournament series identified with three real events surfaced: Broward Turkey Bowl Singles Classic (L6), TriTennis Turkey Bowl National Open (L7, TRN Showcase), and Broward Prize Money Open & NTRP Classic (L5) — names and approximate dates kept; GUIDs synthetic because we couldn't read the live draws. The seeder produces 9 players (Janav + 8 synthetic Florida opponents with `OPP-SYNTHETIC-` prefix and `Player_<hash>` names), 5 tournaments (4 completed + 1 upcoming), 20 draws (Boys 10s/12s singles + 12s doubles + 14s singles per tournament), 20 draw entries, 11 matches (6 Janav wins + 4 losses + 1 upcoming = .600 record), 12 WTN snapshots (Janav 18.0 singles / 19.5 doubles, opponents spread 15-25), 2 ranking snapshots (Florida sectional Boys 12 Singles, trending #128 → #94). Every entity carries a `synthetic://janav-portal/...` marker URL and an `*-SYNTHETIC-*` or `*-SYNTH-*` ID so it can never be confused with real USTA data. The seeder is idempotent (composite-key INSERT OR REPLACE) and consumes the discovery doc for grounded facts. Smoke-tested end-to-end: `pytest tests/unit/test_seed_dev_data.py -q` is 10/10 green; the FastAPI dashboard at `/` and `/tournaments` renders Janav and TriTennis content against the seeded DB. Single biggest remaining gap: residential-egress recon (Q-011) is needed to fetch the actual Cloudflare-fronted TriTennis draws so opponent names, real USTA GUIDs, and Janav's seeded position can replace the synthetic placeholders.

**Created.** `data/research/janav-discovery.md` (HIGH/MEDIUM/LOW-confidence findings with source URLs and the 403 audit trail), `tests/unit/test_seed_dev_data.py` (10 tests covering counts, Janav profile, match history, upcoming-tournament visibility, WTN/ranking trajectories, draw→tournament linkage, idempotence, and a temp-file end-to-end run).

**Replaced.** `scripts/seed_dev_data.py` (was a 4-line stub inserting two stub players + one stub tournament; now an 11-table coherent dataset with score_parser-validated scores and `last_fetched_at=utcnow()` stamping on every primary entity).

**Did not do.** Did not attempt to bypass Cloudflare to read live TriTennis draws (out of scope, blocked by ADR-001). Did not use real opponent names (none were surfaced from public sources; recon will fill those in). Did not modify SPEC.md, DECISIONS.md, RECON.md, API_CONTRACTS.md, STATE.md, or any `src/` files per charter constraints.

— janav-hunt+mock-seed (Claude Code)

---

## 2026-05-10 — Docs cleanup pass

Aligned README, RUNBOOK, TESTING, TODO, AGENTS, DATA_MODEL, and QUESTIONS to current reality: TennisLink is the primary live data source for v1; the Clubspark / `playtennis.usta.com` plane is deferred behind a Cloudflare IP/ASN block until residential recon resolves Q-011; ADR-001 is filed Accepted as Strategy C with a residential-egress operational rider; `scripts/seed_dev_data.py` is documented as the canonical demo-data path and powers UI integration tests with synthetic WTN values. AGENTS.md gained registry rows for the emerging tennislink, rearchitect, and docs-clean roles (formal charter files deferred). DATA_MODEL.md gained a HeadToHead walkover/default clarification (counts toward win/loss only when `winner_id` is set) and a WTN demo-dataset note (synthetic placeholders). QUESTIONS.md resolved entries now cross-reference the doc that owns each answer. TODO.md was restructured around current blockers (Q-011, Q-010), an explicit Phase 1.5 TennisLink track, and a Completed section recapping the high-water-mark items in CHANGELOG. RUNBOOK.md gained a "If a sync hits Cloudflare 403" top-of-tree triage block and an updated WTN section reflecting the residential-recon deferral. Did not modify SPEC.md or DECISIONS.md — those are owned by the Rearchitect agent in this wave.

— docs-clean (Claude Code, docs-cleanup session)

---

## 2026-05-10 — Live recon attempt blocked at Cloudflare edge; ADR-001 filed Accepted as Strategy C

Recon subagent ran `scripts/live_recon.py` with credentials from `settings`, Chromium 141 driven via Playwright in both legacy headless and Xvfb-backed non-headless modes, with anti-detection flags (`--disable-blink-features=AutomationControlled`, `navigator.webdriver` hider init script, Chrome-141-matching UA, US locale + ET timezone, realistic viewport). **Cloudflare 403'd the very first GET on `https://playtennis.usta.com/`** with the standard "Sorry, you have been blocked" interstitial (`cf-ray: 9f9b89cf9e96c0a8-ORD`). Login was never reached. Per the recon charter's stop conditions, the script halted on bot-wall and did not attempt evasion. Side-by-side host-reachability probe (`data/recon/2026-05-10-live/host_reachability.json`) confirms `account.usta.com` (Auth0, not Cloudflare-fronted) returns 200, while every Cloudflare-fronted Clubspark host (`playtennis.usta.com`, `prod-us-kube.clubspark.io`, `prd-itf-kube.clubspark.pro`, `worldtennisnumber.com`) returns 403. Outbound IP at the time was `34.58.203.104` (GCP datacenter range). The block is **IP/ASN-level on Cloudflare's Clubspark edge**, not TLS-fingerprint or browser-realism — the diagnostic is that real Chromium 141 with stripped automation tells reproduces the same 403 that anonymous curl/urllib hit during passive recon.

**ADR-001 promoted to Accepted as Strategy C** (Playwright maintains a long-lived browser context, all data fetches go through it via `context.request.post` / `page.goto`), with the operational rider that **all recon and sync must run from a residential / non-datacenter egress IP**. Rationale: Strategy C is strictly more general than A-prime (`curl_cffi` httpx with bearer token) — it works in any environment where login succeeds in a real browser, because every request inherits the browser's TLS handshake and warmed session. Strategy A-prime cannot be tested from this environment (no captured bearer token; no way to acquire one), and filing it would be guessing. A-prime, if later viable, is a perf optimization on top of C, filable as ADR-004 once a residential capture proves it.

**Updated.** RECON.md (Status flipped from PARTIAL to BLOCKED, full new "Findings (live recon attempt, 2026-05-10)" section with host-reachability matrix and Cloudflare interstitial evidence). API_CONTRACTS.md (Anti-bot posture section refined to distinguish IP/ASN-layer from TLS-fingerprint blocking; clarified that Auth0 plane is reachable but data plane is not from this environment). DECISIONS.md (ADR-001: Status → Accepted, full live-recon evidence section, Strategy C decision rationale, residential-egress operational rider, consequences). QUESTIONS.md (new top-priority Q-011: user must re-run `scripts/live_recon.py` from a residential egress to capture real GraphQL contracts before Phase 1 fetch implementation can be validated against real responses; sub-question on whether Railway's egress is also Cloudflare-blocked, to track before Phase 4 deploy). STATE.md (Phase 0 partial; ADR-001 filed; Q-011 is the top blocker; Phase 1 can scaffold but not validate). `scripts/live_recon.py` (added `--disable-blink-features=AutomationControlled` and friends, Chrome-141 UA matching the actual binary version, `navigator.webdriver` init-script hider, locale/timezone, auto-detected headless flag based on `DISPLAY`).

**Did not do.** Did not attempt any IP-level evasion (proxy, VPN, residential routing, header spoofing beyond UA). Did not capture any authenticated traffic, GraphQL operations, or bearer tokens. Did not run the httpx replay test (no captured request to replay). Did not commit storage_state.json (the Cloudflare 403 prevented even an unauthenticated session from forming; no tokens were ever in scope). The `.gitignore` rule `data/recon/*/storage_state.json` was already present and did not need updating.

— recon (Claude Code, live-recon-attempt session)

---

## 2026-05-10 — Passive recon (no credentials, no browser)

Recon subagent ran an anonymous-only probe sweep against the USTA / Clubspark / WTN surfaces because this session lacks both USTA credentials and a real browser to drive Playwright. Single-shot probes via curl, Python urllib, and WebFetch, with 2+ second sleeps between requests; artifacts under `data/recon/2026-05-10-passive/`.

**Top findings.**

1. **All Clubspark-hosted hosts are Cloudflare-fronted with TLS/JA3 fingerprint enforcement.** `playtennis.usta.com`, `prod-us-kube.clubspark.io`, `prd-itf-kube.clubspark.pro`, `worldtennisnumber.com`, and `docs.worldtennisnumber.com` all return HTTP 403 + Cloudflare interstitial to every anonymous probe — including `robots.txt`. Both curl (OpenSSL) and Python urllib fail identically, which is the diagnostic for fingerprint-level blocking. **Naive Strategy A (stock httpx with replayed cookies) is eliminated**; viable strategies narrow to A-prime (`curl_cffi` Chrome impersonation) or C (Playwright-resident requests).
2. **Auth is OIDC via Auth0**, issuer `https://account.usta.com/`. Confirmed by an anonymous fetch of `account.usta.com/.well-known/openid-configuration` which returns a JSON document containing `http://auth0.com/oauth/grant-type/...` vendor URIs — unmistakably an Auth0 tenant. Login flow is browser-driven Universal Login; Playwright is mandatory for the auth dance regardless of fetch strategy.
3. **The USTA estate has at least two distinct WAFs.** Clubspark hosts are on Cloudflare; `services.usta.com` is on Akamai Bot Manager (sets `_abck` and `bm_sz` cookies). `www.usta.com` (Adobe Experience Manager marketing site) and `tennislink.usta.com` (legacy ASP.NET WebForms with `AntiCsrfTokenTL` CSRF cookie) are anonymously reachable. Different evasion patterns required per surface if we ever need them.

**Updated.** RECON.md (Status promoted to "PARTIAL"; full Findings section replacing the empty TBD scaffold). API_CONTRACTS.md (endpoint table replaced with status-graded rows; OIDC endpoints promoted to Confirmed; GraphQL endpoint detail subtable added; Anti-bot posture section added). DECISIONS.md (ADR-001 gains a "Pre-recon evidence (2026-05-10, passive only)" block — status remains Proposed because no authenticated session evidence exists yet).

**Did not do.** Authenticated session capture, GraphQL query exercise, JWT inspection, WTN payload verification, rate-limit measurement — all gated on `scripts/recon_session.py` running with credentials in a real browser. Tracked as ongoing in RECON.md "Still gated on authenticated recon".

— recon (Claude Code, passive-recon session)

---

## 2026-05-10 — Strength-of-draw enrichment

Implemented `strength_of_draw(draw, entries, ratings, focal_player_id, projected_path=None) -> StrengthOfDrawResult` in `src/enrich/strength_of_draw.py` as a pure function. Field aggregates (size, mean/median/min/max opponent rating, unrated count) and projected-path aggregates (mean, hardest, easiest) computed on a single rating axis where lower = stronger; the WTN-vs-ranking fallback decision is the caller's. Withdrawn entries are excluded from field and rating aggregates. Missing ratings are never imputed as zero — they increment `unrated_count` and skip aggregation. When `projected_path` is omitted the path is reconstructed from standard single-elim pairing on `position`, with each post-round-1 opponent picked as the lowest-rated entry in the focal player's bracket block (ties broken by smaller position; unrated treated as worst). Round-robin and other non-single-elim formats yield an empty path and `None` path aggregates. Added `tests/unit/test_strength_of_draw.py` with ten cases covering field aggregates, unrated handling, withdrawals, the path heuristic, round-robin, focal-not-in-entries, unrated path opponents, empty fields, explicit-path override, and round-2 tiebreak. ruff-clean, mypy-strict, pytest passes.

— enrich agent

---

## 2026-05-10 — Bootstrap

Project scaffolded from an empty repo. Established the canonical doc set and the multi-agent coordination protocol that drives ongoing work.

**Created.** Directory structure (`src/`, `tests/`, `scripts/`, `data/`, `.github/`, `.claude/`). Root config (`.gitignore`, `pyproject.toml`, `.python-version`, `LICENSE`, `.env.example`). Railway deployment config (`Procfile`, `railway.json`, `nixpacks.toml`, `Dockerfile` fallback based on `mcr.microsoft.com/playwright/python:v1.48.0-jammy`). Python source skeleton: `src/config.py`, `src/main.py` (FastAPI app with `/health`), stub modules under `src/auth/`, `src/fetch/`, `src/parse/`, `src/enrich/`, `src/ui/`, `src/cli/`. Pydantic models for Player, Tournament, Draw, DrawEntry, Match, RankingSnapshot, WTNSnapshot. SQLite schema in `src/store/db.py` with eight tables and WAL mode. Test scaffolding: `tests/conftest.py`, `tests/unit/test_health.py`, `tests/unit/test_schema.py`. CI workflow (`.github/workflows/ci.yml`) running ruff + mypy + pytest. PR template. Self-improvement script `scripts/update_canonical_docs.py` (drift report + `--apply` for mechanical refresh). Recon-runner skeleton `scripts/recon_session.py`. Dev-data seeder `scripts/seed_dev_data.py`. `.claude/` subagent charters (recon, parser, enrich, ui), slash commands (`/sync`, `/recon`, `/update-docs`), and project settings.

**Authored canonical docs.** SPEC.md (~6,800 words across 16 sections, written by Agent-Spec). RESEARCH.md (~2,500 words across 5 axes, written by Agent-Research). AGENTS.md (multi-agent coordination charter). DATA_MODEL.md (canonical entity definitions). RECON.md (reconnaissance plan, findings TBD). API_CONTRACTS.md (hypothesized endpoints, all rows unconfirmed). RUNBOOK.md (operations + troubleshooting tree). TESTING.md (pyramid, schema-drift detection, anonymization). README.md, STATE.md, DECISIONS.md (ADR-001 Proposed, ADR-002 Accepted), QUESTIONS.md (nine open items), TODO.md.

**Key research finding.** `playtennis.usta.com` is a Clubspark deployment with a documented GraphQL endpoint at `https://prod-us-kube.clubspark.io/usta/tournaments/api/graphql`. Community gists catalogue queries like `EventList` and `TournamentData`. The same Clubspark infrastructure powers WTN, suggesting WTN data may be reachable via the same surface. This collapses what looked like two scraping problems (tournament data + WTN data) into one and shifts the leading extraction strategy from HTML scraping to GraphQL queries. Validation lands in Phase 0 recon.

**Decisions.** ADR-001 (Extraction Strategy) filed as Proposed, gated on recon. ADR-002 (raw SQLite over SQLAlchemy ORM for v1) filed as Accepted.

**Did not do.** Live recon — credentials and explicit user authorization required. RECON.md is a plan, not findings; API_CONTRACTS.md is hypothesized, not verified. Tracked as Q-001.

— Orchestrator (Claude Code, bootstrap session)
