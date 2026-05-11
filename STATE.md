snapshot: 2026-05-11T00:00:00Z

# STATE.md — live project status

## Phase

**Phase 1 (Core pipeline) — live on real USTA Play Tennis data.** The portal is no longer a seeded demo: the fetch layer now reaches the AWS API Gateway at `prod-api-playtennis.usta.com` anonymously and pulls real tournament + draw data from the same surface the AEM frontend at `playerapp.usta.com` calls at JS-runtime. The dashboard renders Janav's profile, tournaments list, draw detail (with expected-outcome probability bars), and scouting cards against a mix of API-Gateway, CoreTennis, and UTR sources. Sync runs are persisted in a v2-schema `sync_runs` table; the `/sync` UI shows recent runs and the latest log. **357+ tests passing**, 1 skipped (Playwright manual).

**Phase 0 (Reconnaissance) — closed by the 2026-05-11 breakthrough.** The Cloudflare 403 against `playtennis.usta.com` from this environment's GCP egress is no longer a release blocker: a brute-force recon discovered that the AEM-rendered National Search frontend talks to a **separate, unauthenticated AWS API Gateway** at `https://prod-api-playtennis.usta.com` that is *not* behind Cloudflare and IS reachable from this sandbox. Three endpoints answer 200 without an Authorization token (tournaments query, programs query, courts inventory). In parallel, two anonymous third-party feeds — **CoreTennis.net** (per-player HTML history) and **UTR Sports API** (anonymous player search) — close the rest of the gap. Janav's CoreTennis id is `203938`, his UTR id is `3059480`, his real Clubspark GUID remains `971BA48D-A2EA-4FB7-8305-F42EA466F6DF`, and his four real Boys 12s USTA Level 3 match results are now in the system as ground truth for the parsers and enrichments.

**Net data-source reality.** Current-season tournament discovery, draws, and per-player history all live on reachable, anonymous surfaces. The Cloudflare-fronted Clubspark plane is no longer load-bearing — it remains a fallback for per-id detail and auth-walled queries (see ADR-006). TennisLink stays as the frozen historical archive (post-2018 records absent). The seeded dataset's role is downgraded from "primary substance" to "scaffold while the real-data orchestrator catches up."

## Active workstreams

_Parallel-agent state is not visible from this snapshot; if a recon, parser, or seeder agent is in flight it will land in CHANGELOG.md as it completes._

## Recently completed

- **2026-05-11 data-plane breakthrough (orchestrator).** Discovered that `https://playerapp.usta.com` is an AEM-rendered SPA whose inline JS exposes `playtennis.externalApiConfig.apiBasePath = "https://prod-api-playtennis.usta.com"` — an AWS API Gateway sitting on a different host from `playtennis.usta.com` and *not* on Cloudflare. Confirmed three endpoints return 200 anonymously to this sandbox's GCP egress (the same egress Cloudflare 403s on the original host): `POST /playtennis/tournaments/query`, `POST /playtennis/programs/query`, `POST /product/api-courts/v1/courts/inventory`. Required selection fields: `d` (distance, miles), `lat`, `lon`. Optional: `type`, `q`, `registrationOpen`, `startDateTime`, `page`, `size`, plus ES-style filter fields. Pagination is `selection.page` (1-indexed) + `selection.size` (max 50); sort is `{"sort":{"field":"distance|startDateTime","order":"asc|desc"}}`. Per-player detail endpoints (`/playtennis/players/query`, per-id GETs) remain auth-walled and are out of scope. Shipped in code: `src/fetch/usta_api_client.py`, `src/parse/usta_api.py`, `src/fetch/router.py` (`DEFAULT_SOURCE_PREFERENCE` is now `("usta_api", "tennislink", "clubspark")`; GUID-aware sources lead for GUID-shaped ids; `usta_api` source built lazily), `src/cli/main.py` (`usta sync` runs a USTA-API discovery walk for nearby tournaments anchored on `USTA_ANCHOR_LAT/LON/DISTANCE_MILES/PLAYER_TYPE`, gated by `USTA_DISCOVER_ENABLED`), `src/models/sync_run.py` (`SyncRunSource` taxonomy adds `"usta_api"`). Filed ADR-006 Accepted.
- **2026-05-11 CoreTennis + UTR third-party feeds (orchestrator).** Two additional anonymous sources confirmed reachable. CoreTennis: `https://www.coretennis.net/tennis-player/<slug>/<id>/{profile,ranking,results}.html` — third-party HTML aggregator with full per-player match history (Janav's id is `203938`, surfacing his four real USTA Level 3 Boys 12s results from Jan 2025 through Jan 2026, all R1/32 losses on hard). UTR search: `GET https://api.utrsports.net/v2/search/players?query=<name>&top=<int>` — ES envelope, anonymous (Janav's UTR id is `3059480`, Weston FL). UTR per-id detail remains auth-walled. Shipped in code: `src/fetch/coretennis_client.py` + `src/parse/coretennis.py`, `src/fetch/utr_client.py` + `src/parse/utr.py` + `src/models/utr.py`. Filed ADR-007 Accepted.
- **2026-05-10 — TennisLink + multi-source FetchRouter + sync wiring (prior wave).** Full details in CHANGELOG. Carried forward as the secondary historical-archive source; superseded by ADR-006 as the primary surface.

## Next up

1. **Integrate CoreTennis + UTR into the sync orchestrator.** Today the new clients exist but the `usta sync` walk only exercises the USTA API discovery surface. Wire CoreTennis as the per-player history enricher and UTR as the identity/rating bridge, threading both through `FetchRouter` and the existing repositories.
2. **Refresh the seeder.** `scripts/seed_dev_data.py` still anchors on synthetic Florida opponents. Replace with a real-data hydrator that calls the USTA API + CoreTennis + UTR clients and writes through the same repositories sync uses. Synthetic placeholders go away.
3. **UI bracket visualization and time-series charts.** Per TODO.md the largest visible delta to a polished product is real bracket SVG and WTN/ranking trajectory charts on the player detail pages. The data is in scope for the first time now.
4. **Reverse-engineer Janav's USTA player GUID from the new commingled tournament index (Q-017).** We have his Clubspark guid (`971BA48D-A2EA-4FB7-8305-F42EA466F6DF`), CoreTennis id (`203938`), and UTR id (`3059480`), but no GUID that the new `prod-api-playtennis.usta.com` tournament hits correlate against. Search the hits for the four real events he played and read his id out of a draw response (this step is gated on auth — surfaced as Q-017).

## Open blockers

- **None at the data-plane layer.** Q-011 (residential-egress recon) is **resolved** as of 2026-05-11 — the alternate-host discovery obviates the need to escape Cloudflare from this egress. The auth-walled detail endpoints remain gated, tracked under Q-017.
- **Q-003 (WTN exposure pathway) — partially closed.** The UTR search endpoint partly fills the rating gap (it returns UTR ratings, not WTN, but UTR is the rating axis the broader junior community now uses). True WTN remains behind the auth-walled Clubspark surface; deferred but no longer a release blocker.

## Recent decisions awaiting closure

- **ADR-006 (Anonymous USTA Play Tennis API as primary data plane)** — Accepted (2026-05-11). Filed.
- **ADR-007 (CoreTennis + UTR as third-party enrichment feeds)** — Accepted (2026-05-11). Filed.
- ADR-001 (Extraction Strategy) — Accepted (2026-05-10) as Strategy C, **superseded by ADR-006 for the discovery + search surfaces; remains in place for per-id detail behind auth.**
- ADR-002 (Storage layer: SQLite raw vs. SQLAlchemy ORM) — Accepted.
- ADR-005 (Multi-source FetchRouter, TennisLink primary, Clubspark deferred) — Accepted (2026-05-10); the router shape stands but source preference has shifted (`usta_api` now leads).

## Doc snapshot health

- SPEC.md: pre-breakthrough phrasing in §4 (Reconnaissance) and §13 (Roadmap) is now stale — the strategy section still describes Strategy A / Strategy C as the pivot, not the ADR-006 alternate-host story. Surgical edit needed (flagged for the next docs-clean pass; not done in this realignment).
- RECON.md: refreshed 2026-05-11; status flipped to REACHED with the breakthrough section pinned at the top.
- API_CONTRACTS.md: refreshed 2026-05-11; the three USTA-API anonymous endpoints are now the primary section. Clubspark / TennisLink demoted to Secondary / Deferred.
- DECISIONS.md: ADR-006 + ADR-007 filed; ADR-001 status updated to "Accepted but superseded by ADR-006 for discovery + search."
- DATA_MODEL.md: aligned with Pydantic models; UTR model added (`src/models/utr.py`).
- QUESTIONS.md: Q-011 resolved; new Q-017 opened.
- TODO.md: critical-path items rewritten to reflect post-breakthrough state.
