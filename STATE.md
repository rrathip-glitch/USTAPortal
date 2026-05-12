snapshot: 2026-05-12T00:30:00Z

# STATE.md — live project status

## Phase

**Phase 1.5 — Rankings pipeline LIVE on TennisLink historical data.** The end-to-end pipeline (fetch → parse → repo → UI) now works against the captured Boys' 12 Combined fixture (TennisLink list 2072448, 1,014 players). Real USTA data renders at `/rankings/u12-boys-national`, with Janav highlighted when his row is present and a "Source: TennisLink (historical)" footnote making the era explicit. This is the first real USTA data in the dashboard.

The same pipeline targeting **current 2025/2026 rankings** is gated on two pieces still in flight: (1) the Clubspark current-rankings recon agent's identification of the production URL/GraphQL query for live Boys' 12 national standings (probing `ParticipantRankings` and `RankingsAndRatings` GraphQL types now), and (2) wiring the existing Bright Data Web Unlocker proxy backend into the WTN crawler so per-player WTN fetches succeed at scale. Both depend on infrastructure that has been verified end-to-end this wave — Bright Data clears Cloudflare on `playtennis.usta.com` and reaches `prd-itf-kube.clubspark.pro/tods-gw-api/graphql` from this sandbox, with real production WTN data flowing (Rudy Quan: singles 6.1, doubles 11.74).

## Active workstreams

- **Orchestrator: deploying to Railway** — docs and tests cleaned, `.env.example` complete, schema v3 migration is additive-only.
- **Clubspark current-rankings recon (background)** — probing the production schema for `ParticipantRankings` + `RankingsAndRatings` types, hunting the public `playtennis.usta.com` URL pattern; the unified-search-api OpenAPI/Swagger surface has been discovered and is the strongest current lead.

## Recently completed

### Wave 2 (2026-05-12)

- **TennisLink rankings vertical slice end-to-end.** `src/parse/tennislink_rankings_list.py` + `usta sync-rankings --from-fixture` CLI + `/rankings/u12-boys-national` route render the 1,014-player Boys' 12 Combined list with Janav-highlight + "Source: TennisLink (historical)" footnote. +19 net new tests (317 total green). First real USTA data in the dashboard. — rankings-vertical-slice agent + Orchestrator
- **Bright Data Web Unlocker proven end-to-end through sandbox** (2026-05-11). Clears Cloudflare on `playtennis.usta.com`, reaches production ITF/WTN GraphQL at `prd-itf-kube.clubspark.pro/tods-gw-api/graphql`, real WTN data flows. Payload shape verified: POST `/request` with Bearer auth, body key (not data/payload), `zone="web_unlocker1"`. — Orchestrator probe series
- **`BrightDataWebUnlockerBackend` refactored** to the verified Bearer-auth + body-key + POST-support shape. 9/9 tests. — bright-data-refactor agent
- **Proxy-infra scaffolding landed.** `src/fetch/residential_proxy.py`, schema v3 (`ranking_lists` + `ranking_list_entries` tables), `RankingListRepository`, `/rankings/u12-boys-national` route, `usta sync-rankings` CLI, 12 new tests. — proxy-infra agent
- **Janav's production ITF record located.** `tennisID JAN9450835`, name fields swapped, `worldTennisNumbers: null` (he is in the system but has no WTN — likely too young / no ITF events). Sister **Vihana Thasen** (`THA5459427`) has full WTN: singles 27.97, doubles 31.55. — Orchestrator
- **notify-resend test isolation fixed.** Monkeypatched settings to clear `notify_to` and `resend_api_key` in the 2 `ConfigurationError` tests; full suite clean. — Orchestrator

### Wave 1 (2026-05-11)

- **Rankings-First pivot landed (ADR-006 Accepted).** All prior TODOs paused; v1 refocused on rankings + WTN crawl. — Orchestrator + doc-rewrite agents
- **TennisLink rankings recon verdict: historical-only.** B12 froze early 2021 (last Final 2021-01-03), B10 never published, no WTN exposed anywhere on TennisLink. Every junior list is historical, every age group, every year. — tennislink-rankings agent
- **Cloudflare bypass: structurally impossible from this sandbox.** Anthropic MITM proxy + Cloudflare ASN block on egress IPs + hostname allowlist — no in-sandbox technique can unblock the Clubspark edge. User opted for paid residential proxy (Bright Data Web Unlocker). — bypass agent + Orchestrator
- **Browse-Janav recon.** Confirmed CURRENT B12 list id (2072448, later proved to be an early-2021 cohort), stg WTN GraphQL reachable via `curl_cffi chrome131`, stg ITF record for Janav is stub-only with no WTN. — browse-janav agent
- **Resend notification module shipped.** `src/notify/` with retry + config + 5 tests; Q-010 resolved, Q-012 opened on FROM-domain. — notify-build agent
- **Data-pull harvest.** 906 files, 67 historical TennisLink ranking lists, WTN crawl 94% success rate; Florida section code = 15, district codes 1531-1538. — data-pull agent
- **`data/reference/known_urls.md` created.** Canonical URL/identifier reference: user-supplied draw URL, TennisLink ranking-list-id table with freshness verdict, Clubspark GraphQL endpoints, Janav cross-platform identifiers. — Orchestrator

## Next up

1. **Wire Clubspark current-rankings into the existing pipeline.** When the recon agent returns with the production URL + GraphQL query for live Boys' 12 national standings, plug it into `usta sync-rankings` via the Bright Data backend; swap the historical-fixture footnote for a live source label.
2. **WTN crawler for the displayed list.** For every player at rank ≤ Janav's rank, fetch their profile via the refactored Bright Data backend, parse WTN singles/doubles, persist into the existing `Player` / WTN store. Honor rate limits; cache raw payloads under `data/raw/`.
3. **Janav scouting card UI.** "Unranked + no WTN" treatment with TR rank ~146 + sister Vihana's WTN as context. Renders even when Janav is not in the displayed list (the realistic case for early-2021 historical data).
4. **Name-match enrichment.** Resolve the synthetic `tl-rank:` USTA ids assigned during TennisLink ingest to real Clubspark GUIDs once the production identity surface is reachable.
5. **(Done by Orchestrator)** The two notify-resend env-isolation test fixes — landed alongside the wave 2 cleanup.

## Open blockers

- **Awaiting Clubspark recon agent's URL/query identification** to swap historical TennisLink data for current Clubspark data. Infrastructure (Bright Data Web Unlocker) is verified working; only the canonical query surface is unknown.

## Recent decisions awaiting closure

- ADR-006 (Rankings-First Pivot) — **Accepted (2026-05-11).** Filed.
- ADR-005 (Multi-source fetch with TennisLink primary, Clubspark deferred) — **Accepted.** Filed.
- ADR-002 (Storage layer: raw SQLite over SQLAlchemy ORM) — **Accepted.** Filed.
- ADR-001 (Extraction Strategy — Strategy C, Playwright-resident requests with residential-egress rider) — **Accepted (2026-05-10).** Filed.

## Doc snapshot health

- SPEC.md: aligned with the rankings-first pivot; minor refresh due once Clubspark current-data path lands.
- TODO.md: refreshed for wave 2; critical-path rankings items mostly complete, Clubspark + WTN crawler open.
- CHANGELOG.md: current through 2026-05-12.
- DECISIONS.md: ADR-001/002/005/006 all Accepted and filed.
- QUESTIONS.md: Q-010 resolved (Resend), Q-012 open (Resend FROM-domain), Q-011 partially obsoleted by the Bright Data path.
- DATA_MODEL.md: aligned with schema v3 (`ranking_lists` + `ranking_list_entries`).
- RECON.md / API_CONTRACTS.md: TennisLink rows confirmed; Clubspark current-rankings rows pending the in-flight recon.
- `data/reference/known_urls.md`: current.
