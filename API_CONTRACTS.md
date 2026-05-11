# API_CONTRACTS.md — USTA endpoint inventory

A live table of the endpoints we depend on. Populated by recon and refreshed every time schema drift is detected.

## Status

**Primary data plane shipped 2026-05-11** against the anonymous AWS API Gateway at `https://prod-api-playtennis.usta.com`. See "USTA-API endpoints (anonymous)" below for the three confirmed endpoints. The Cloudflare-blocked Clubspark surface (`playtennis.usta.com`, `prod-us-kube.clubspark.io`, etc.) is **Deferred** — it remains a fallback for per-id detail and auth-walled queries but is no longer load-bearing. The TennisLink surface is **Secondary** — frozen historical archive, useful for pre-2019 records. Two anonymous third-party feeds (CoreTennis, UTR search) are documented under "Third-party feeds" below. Cell-by-cell evidence is in RECON.md "2026-05-11 breakthrough — prod-api-playtennis.usta.com" and the pre-breakthrough sections kept underneath it for posterity.

## USTA-API endpoints (anonymous)

Status: **Confirmed live (2026-05-11).** Base: `https://prod-api-playtennis.usta.com`. CORS allow-all. No Authorization header required for the three endpoints below. Per-player detail endpoints (`/playtennis/players/query`, per-id GETs) are auth-walled and return 403 / "Missing Authentication Token" — out of scope. Backing client: `src/fetch/usta_api_client.py`. Parser: `src/parse/usta_api.py` (ES envelope → Tournament / Draw).

| Method | Path | Purpose | Status |
| --- | --- | --- | --- |
| POST | `/playtennis/tournaments/query` | ES-style tournament search | ✅ Confirmed live |
| POST | `/playtennis/programs/query` | ES-style program search | ✅ Confirmed live |
| POST | `/product/api-courts/v1/courts/inventory` | Court inventory search | ✅ Confirmed live |

### Request shape (all three endpoints)

```json
{
  "selection": {
    "d": 50,
    "lat": <float>,
    "lon": <float>,
    "type": "Junior|Adult|Wheelchair",
    "q": "<keyword>",
    "registrationOpen": true,
    "startDateTime": "<ISO-8601>",
    "page": 1,
    "size": 50,
    "events.division.gender": "...",
    "events.surface": "..."
  },
  "sort": {"field": "distance|startDateTime", "order": "asc|desc"}
}
```

- **Required selection fields:** `d` (distance, miles), `lat`, `lon`.
- **Optional selection fields:** `type` (`Junior` / `Adult` / `Wheelchair`), `q` (free-text keyword), `registrationOpen` (bool), `startDateTime` (ISO-8601), `page` (1-indexed), `size` (max 50), plus any ES-style filter field (`events.division.gender`, `events.surface`, etc).
- **Pagination:** `selection.page` is 1-indexed; `selection.size` capped at 50. Walk pages by incrementing `selection.page` until `hits.total.value` is reached.
- **Sort:** `{"sort": {"field": "distance|startDateTime", "order": "asc|desc"}}`.

### Response shape (ES envelope)

```json
{
  "hits": {
    "total": {"value": <int>},
    "hits": [
      {"_id": "<id>", "_source": { ...entity fields... }},
      ...
    ]
  }
}
```

`hits.total.value` is the total result count; `hits.hits[]` carries one entry per result with `_id` and `_source`. The parser in `src/parse/usta_api.py` walks `hits.hits` and maps each `_source` to a `Tournament` (and any embedded Draws / events) Pydantic model.

### Anchor configuration

`usta sync` runs a USTA-API discovery walk for nearby tournaments anchored on the environment variables:

- `USTA_ANCHOR_LAT` / `USTA_ANCHOR_LON` — required floats; the search anchor (typically the user's home).
- `USTA_DISCOVER_DISTANCE_MILES` — `d` value (default per `src/config.py`).
- `USTA_DISCOVER_PLAYER_TYPE` — `type` value (default `Junior`).
- `USTA_DISCOVER_ENABLED` — gates the discovery walk on/off.

## Third-party feeds

Anonymous, non-USTA. Documented here because they are now in the v1 data plane.

### CoreTennis (per-player HTML history)

| Path | Method | Auth | Purpose |
| --- | --- | --- | --- |
| `https://www.coretennis.net/tennis-player/<slug>/<id>/profile.html` | GET | none | Per-player profile (identity, rating, country, age category) |
| `https://www.coretennis.net/tennis-player/<slug>/<id>/ranking.html` | GET | none | Per-player ranking history |
| `https://www.coretennis.net/tennis-player/<slug>/<id>/results.html` | GET | none | Per-player full match history |

- **`<id>`** is the CoreTennis player id (integer). Janav Thasen's id is `203938`.
- **`<slug>`** is the URL-friendly name slug; both work in practice when the id is correct.
- Response is HTML; parser is `src/parse/coretennis.py` (HTML → `Player` + `Match[]`).
- Client: `src/fetch/coretennis_client.py`.
- Schema-drift risk: HTML structure can change without notice — fixture-driven parser tests cover the current shape; a schema-drift canary is planned (TODO.md).

### UTR (Universal Tennis Rating) search

| Path | Method | Auth | Purpose |
| --- | --- | --- | --- |
| `https://api.utrsports.net/v2/search/players?query=<name>&top=<int>` | GET | none | Player search by name (anonymous) |
| `https://api.utrsports.net/v2/...<per-id detail>` | GET | **auth required** | Per-player detail — out of scope |

- Response: ES-style envelope (`hits.total.value`, `hits.hits[].{_id, _source}`).
- Janav Thasen's UTR id is `3059480` (Weston, FL).
- Client: `src/fetch/utr_client.py`. Parser: `src/parse/utr.py`. Model: `src/models/utr.py`.
- Schema-drift risk: UTR could close the search endpoint without notice — same canary plan applies.

## Endpoint inventory (Auth0 + Clubspark — Deferred fallback)

Status: **Deferred (2026-05-11).** No longer the primary data plane. Kept on record because the Auth0 plane is reachable from this environment (anonymously) and the Clubspark hosts remain the only source for per-id detail and auth-walled queries. The Cloudflare IP/ASN block on the Clubspark hosts is unchanged from the 2026-05-10 findings.

| Surface | URL | Method | Auth | Purpose | Status (2026-05-10) |
| --- | --- | --- | --- | --- | --- |
| OIDC discovery | `https://account.usta.com/.well-known/openid-configuration` | GET | None | Lists the Auth0 endpoints below | **Confirmed** — 200 JSON, anonymous-readable (`oidc_config.json`) |
| Auth0 authorize | `https://account.usta.com/authorize` | GET (browser redirect) | None initially | Begin OIDC code flow / Universal Login | **Confirmed exists** via OIDC discovery; flow not yet exercised |
| Auth0 token | `https://account.usta.com/oauth/token` | POST | Auth code + (optionally) PKCE verifier; client_id required | Exchange code for `access_token` + `id_token` (+ refresh_token if `offline_access` requested) | **Confirmed exists** via OIDC discovery; client_id and audience TBD |
| Auth0 userinfo | `https://account.usta.com/userinfo` | GET | `Authorization: Bearer <access_token>` | Fetch the authenticated user's claims | **Confirmed exists** via OIDC discovery |
| Auth0 JWKS | `https://account.usta.com/.well-known/jwks.json` | GET | None | Public keys for verifying id_token signatures | **Confirmed exists** via OIDC discovery |
| Auth0 logout | `https://account.usta.com/oidc/logout` | GET (browser redirect) | Session cookie or `id_token_hint` | End session | **Confirmed exists** via OIDC discovery |
| Auth0 MFA challenge | `https://account.usta.com/mfa/challenge` | POST | Per Auth0 MFA flow | MFA step (likely OOB or OTP) | **Confirmed exists** via OIDC discovery; whether enforced TBD |
| Tournaments GraphQL | `https://prod-us-kube.clubspark.io/usta/tournaments/api/graphql` | POST | TBD — likely `Authorization: Bearer <Auth0 JWT>` plus `Origin: https://playtennis.usta.com` | Tournament / draw / player / match data | **❌ Blocked from Claude Code egress** (Cloudflare WAF, IP/ASN block on GCP datacenter range; reachable from residential egress only). Host exists; request/response shape unconfirmed. |
| WTN GraphQL | `https://prd-itf-kube.clubspark.pro/tods-gw-api/graphql` | POST | TBD — bearer token with WTN audience scope | Singles + doubles WTN | **❌ Blocked from Claude Code egress** (same Cloudflare rule). May or may not be needed if WTN is embedded in the tournaments payload. |
| Legacy tennislink | `https://tennislink.usta.com/Dashboard/Main/default.aspx` | GET / form POST | `ASP.NET_SessionId` + `AntiCsrfTokenTL` cookies | Legacy NTRP rankings, legacy team-tennis data | **Confirmed reachable anonymously** (200, ASP.NET WebForms with Vue 2 overlay). Not the primary target; documented in case Phase 5 needs NTRP history. |
| USTA services API | `https://services.usta.com/v1/...` | TBD | TBD; Akamai BMP cookies (`_abck`, `bm_sz`) on every response | Unknown — possibly membership / NTRP / ranking surface called by AEM marketing site | **Host confirmed exists** (`awselb/2.0` returns 404 plain text on `/`, `/v1`, `/v1/players`, `/v1/tournaments` — the API exists but those paths don't). Behind Akamai Bot Manager. |
| WTN docs | `https://docs.worldtennisnumber.com/api-docs/` | GET | "USTA-issued credentials" per RESEARCH.md | API documentation site | Anonymously **403 Cloudflare**, consistent with prior research. |

### GraphQL endpoint detail (per the explicit ask)

| Property | Observed (2026-05-10) |
| --- | --- |
| URL | `https://prod-us-kube.clubspark.io/usta/tournaments/api/graphql` |
| Anonymous GET | HTTP 403, `text/html`, Cloudflare interstitial body, `cf-ray: 9f9b74bb5c46d8ab-ORD` |
| Anonymous POST `{ __schema { queryType { name } } }` (browser-like UA, `Origin: https://playtennis.usta.com`, `Referer: https://playtennis.usta.com/`) | HTTP 403, `text/html`, Cloudflare interstitial body, `cf-ray: 9f9b74fda916088a-ORD` |
| Same POST from Python `urllib` (different TLS stack) | HTTP 403, identical Cloudflare body, `cf-ray: 9f9b79d73fb3105c-ORD` |
| Auth requirement | **Unknown — cannot probe.** WAF blocks before app. Consensus from Auth flow + community gists is `Authorization: Bearer <Auth0 access_token>`. |
| Introspection availability | **Unknown — cannot probe.** May be enabled (typical Apollo default) or disabled in production (best practice). To be tested under authenticated session. |
| Response shape on success | **Unknown.** RESEARCH.md cites community-documented `EventList` and `TournamentData` queries returning JSON; we have not verified. |
| Cookies set | Cloudflare `__cf_bm` (Domain=`clubspark.io`, 30 min, HttpOnly+Secure). |

## GraphQL queries (hypothesized — currently blocked)

Per RESEARCH.md, community-documented queries on the Clubspark surface include `EventList` and `TournamentData`. We expect to need at minimum:

- `TournamentData(id)` — fetch one tournament's metadata + draws.
- `EventList(filters)` — list tournaments matching filters (date range, section, age group).
- `Draw(id)` — fetch one draw with entries and matches.
- `Player(id)` — player profile, including WTN if co-located.
- `PlayerRankings(id)` — ranking history.
- `PlayerMatches(id, window)` — recent match results.

Each row in the table below lands its actual query body (variables, response shape) once recon captures real traffic.

| Query | Variables | Response top-level keys | Pagination | Confirmed? |
| --- | --- | --- | --- | --- |
| TournamentData | TBD | TBD | TBD | ❌ Blocked from Claude Code egress |
| EventList | TBD | TBD | TBD | ❌ Blocked from Claude Code egress |
| Draw | TBD | TBD | TBD | ❌ Blocked from Claude Code egress |
| Player | TBD | TBD | TBD | ❌ Blocked from Claude Code egress |
| PlayerRankings | TBD | TBD | TBD | ❌ Blocked from Claude Code egress |
| PlayerMatches | TBD | TBD | TBD | ❌ Blocked from Claude Code egress |

## TennisLink endpoints (Secondary — historical archive, frozen post-2018)

Status: **Secondary (2026-05-11).** TennisLink (`tennislink.usta.com`) is no longer the primary live data source — that role moved to the anonymous USTA-API endpoints at the top of this document as of the 2026-05-11 breakthrough. TennisLink remains in the fetch layer as the **historical archive source** (pre-2019 tournament / draw / ranking records that the new API does not expose). It is the legacy ASP.NET WebForms surface; responses are HTML, server-rendered. All endpoints below were probed anonymously on 2026-05-10 with stock `curl` from this GCP egress — no Cloudflare in front, no JA3 sensitivity, no auth required for read access. Fixtures live in `tests/fixtures/tennislink/`.

| Endpoint | Method | Parameters | Auth | Key DOM selectors / response shape | Confirmed |
| --- | --- | --- | --- | --- | --- |
| `https://tennislink.usta.com/tournaments/schedule/search.aspx` | GET | none (renders form) | none | Form action posts back to itself; the page's JS rewrites `action` to `SearchResults.aspx?<all params>` and re-submits as GET. ASP.NET `__VIEWSTATE` + `__VIEWSTATEGENERATOR` hidden inputs present. Division options parsed from `<select name="ctl00$mainContent$ddlDivision">`. | ✅ 200 (fixture: `tournament_search_form.html`) |
| `https://tennislink.usta.com/tournaments/schedule/SearchResults.aspx` | GET | `typeofsubmit`, `Keywords`, `TournamentID`, `SectionDistrict`, `City`, `State`, `Zip`, `Month`, `Year`, `StartDate`, `EndDate`, `Day`, `Division`, `Category`, `Surface`, `OnlineEntry`, `DrawsSheets`, `UserTime`, `Sanctioned`, `Action` | none | Tournament rows live in `<table id="dgTournaments">`. Each row contains: date `<td>`, `<a href="javascript:Go(<id>)">` with the tournament name + dash-separated tournament number (e.g. `WINTER CHMPS. - 100000202`), location `<td>`, and a `<ul class="plain-list compact">` of divisions. Pagination links are `javascript:__doPostBack('dgTournaments:_ctl1:_ctl<N>','')` — **no GET-pageable URL**. | ✅ 200 (fixture: `tournament_search_results.html`) |
| `https://tennislink.usta.com/tournaments/TournamentHome/Tournament.aspx` | GET | `T=<int>` required; `E=<int>` optional; `tab=Draws\|Contacts\|Results\|Dates` optional | none | `<h1>` = tournament name. `<table class="tournament_info">` contains Tournament ID, Dates, Divisions (as `<ul>`). Second `tournament_info margin` table has Section, District, Surface Type, Draws Posted, Last Updated. Organization block has `<table id="organization">`. Sanction-body image at `<img src="../images/logos/<Section>Sect_2c.png">`. | ✅ 200 (fixture: `tournament_detail.html`, T=211365 TriTennis Holiday Series) |
| `https://tennislink.usta.com/tournaments/TournamentHome/Tournament.aspx?T=...&E=...&tab=Draws` | GET | `T`, `E` (event ID, e.g. `5`), `tab=Draws` | none | Event dropdown `<select id="ctl00_mainContent_ControlTabs3_ddlEvents">` with options like `<option value="#5">Boys' 14 Singles</option>`. Player slots: `<a href="/tournaments/Draws/PlayerTournamentHistory.aspx?MID=...">PLAYER NAME</a>` followed by city/state. Round headers `Finals`, `SF`, `QF` appear as text labels. Match scores in `<div>` siblings: format `6-3; 6-2` or `6-7(3); 6-3; 10-7` (semicolon-separated sets, parens for tiebreak in losing set's games count). | ✅ 200 (fixture: `draw_detail.html`, T=211365 E=5 Boys' 14 Singles) |
| `https://tennislink.usta.com/tournaments/Draws/PlayerTournamentHistory.aspx` | GET | `MID=<numeric>` required; `Years=-1\|-5\|YYYY` optional | none | `<div class="mtitle">Player Results</div>` header; year-by-year list of tournaments the player entered. Each entry links back to `Tournament.aspx?T=...`. **Player's name does not appear on this page** — only visible from referring context. If no matches: `<td>&nbsp;No match information is available.&nbsp;</td>`. | ✅ 200 (probed, not committed as fixture since the example MID page is empty) |
| `https://tennislink.usta.com/tournaments/Rankings/RankingHome.aspx` | GET (form) / POST (submit) | optional `RankingListID=<int>` for deep-link | none | Three search forms in one page: (1) ranking list (section/year/division/list-type → POST), (2) player record (USTA# or name → POST), (3) player ranking (USTA# or name → POST). Division dropdown values: `D1001` Boys 18 Singles, `D1003` Boys 16 Singles, `D1005` Boys 14 Singles, `D1101` Boys 18 Doubles. Section dropdown values: `15` Florida, `10` Eastern, `30` Southern, `40` Mid-Atlantic, `15XX` for sub-districts. POST submission requires `__VIEWSTATE` + `__VIEWSTATEGENERATOR` round-trip (server-validated MAC). | ✅ 200 (fixture: `rankings_home.html`) |
| `https://tennislink.usta.com/Tournaments/Rankings/RankingListsPrint.aspx` | GET | `id=<list_id>` required; `e=<0\|1>` (eligibles), `sortby=<rank\|name\|section\|district>` | none | Title row in `<td class="FieldData">` (e.g. `*B14 2019 GA Standings (Combined)`). Data table `<table id="grdMain">`. Header row labels: Rank, Name, City, State, Section, District, Points. Per-row spans `grdMain_ctl<NN>_lblRank`, `_lblFullName` (format `"Last, First "`), `_lblCity`, `_lblState`, `_lblSection`, `_lblDistrict`, `_lblPoints`. **Cleanest TennisLink endpoint — flat tabular HTML, no postback dance.** | ✅ 200 (fixture: `ranking_list.html`, id=2102615 B14 2019 GA Standings) |
| `https://tennislink.usta.com/tournaments/Rankings/RankingListNote.aspx` | GET | `id=<list_id>` | none | Popup-style methodology note for a ranking list (`<p>` text only). | ✅ 200 (probed; not fixtured since low value) |
| `https://tennislink.usta.com/tournaments/` | GET | none | none | Hub page with links to advanced search, rankings, registration, archived results. Redirects to `/Tournaments/Common/Default.aspx`. | ✅ 200 (fixture: `tournament_home.html`) |

### Identifier formats observed on TennisLink

- **Tournament ID** (`T=`): integer, 1-6 digits. Range observed 1 (a 1996 archived event) to 232435 (Nov 2018 TriTennis). Stable, monotonically increasing.
- **Event ID** (`E=`): single-digit integer (per tournament). E.g., `E=5` is Boys 14 Singles within tournament 211365.
- **Player Tournament ID** (`MID=`): ~30-digit numeric string per player. Example: `1180182182182183184177178177179`. Recon hypothesis: per-digit obfuscated USTA member number. v1 treats it opaquely.
- **Ranking List ID**: 7-digit integer (e.g. `2102615`, `1684711`). Discovered via RankingHome search; deep-linkable.
- **USTA Member Number** (the form's `txtPlayerUSTANo` field): plain integer up to 2^32 (4,294,967,296).
- **Division code** (`ddlDivision` value on search; `Division` field on rankings): short alphanumeric like `GB16` (search) or `D1003` (rankings).

### Anti-bot posture (TennisLink)

**No Cloudflare. No Akamai. No bot challenge.** TennisLink sets `ASP.NET_SessionId` (HttpOnly+Secure+SameSite=Strict), `AntiCsrfTokenTL` (HttpOnly+Secure+SameSite=Strict, validated only on state-changing POSTs), a `BIGipServer~usta~tennislink.usta.com_https_pool1` F5 cookie, and a TS01-prefixed cookie. All GET endpoints return 200 to stock `curl` from this environment's GCP datacenter egress (`34.58.203.104`). Rate-limit posture: not yet measured; default 2-second interval applies.

## Schema drift log

Append-only. Each entry: date, query, what changed, recovery action.

> _No drift recorded yet — schema baseline lands with first successful recon._

## Auth header pattern

**Strongly suggested by passive recon: `Authorization: Bearer <Auth0 access_token>`** on all Clubspark GraphQL calls. Reasoning: `account.usta.com` is an Auth0 tenant (confirmed via OIDC discovery — see RECON.md), Auth0 SPAs by convention store the access token in memory and attach it as a Bearer header to API calls, and the GraphQL host lives on a separate domain (`clubspark.io`) from the SPA (`playtennis.usta.com`), which makes cookie auth awkward without a third-party cookie story we have no evidence of. Final confirmation requires authenticated session capture.

CSRF likely **not** required on the GraphQL endpoint since bearer-token auth is not vulnerable to CSRF in the cookie sense; but `Origin` / `Referer` validation is plausible at the gateway level.

## Anti-bot posture

**Cloudflare WAF in front of every Clubspark host, with both TLS/JA3 fingerprint enforcement AND IP/ASN-level blocking of cloud-datacenter egress.** Confirmed empirically across two independent recon passes:

- Passive (2026-05-10, `data/recon/2026-05-10-passive/`): stock curl 8.5.0 and Python urllib both 403 on every probe — including `robots.txt`. Two stock TLS stacks failing identically is the fingerprint diagnostic.
- Live (2026-05-10, `data/recon/2026-05-10-live/`): real Chromium 141 driven via Playwright with `--disable-blink-features=AutomationControlled`, an init-script that hides `navigator.webdriver`, a Chrome-141-matching UA, and Xvfb-backed non-headless mode — STILL 403, with `cf-ray: 9f9b89cf9e96c0a8-ORD`. The browser's TLS handshake completes and Cloudflare returns its own HTML, which is the diagnostic for **application-layer WAF rejection on IP/ASN, not on TLS or browser fingerprint**. Outbound IP at the time was `34.58.203.104` (GCP datacenter range).

Practical implication, refined: a real Playwright browser is **not sufficient on its own** — the egress IP also has to be off Cloudflare's datacenter blocklist. Any httpx replay (stock or `curl_cffi`-impersonating) and any Playwright run from a known datacenter ASN will fail at the same WAF rule. **Recon and sync must run from a residential egress.** ADR-001 has been promoted to Accepted with this constraint as a hard operational rider.

`services.usta.com` is on **Akamai Bot Manager** instead (separate WAF, sets `_abck`/`bm_sz`), so different evasion pattern if/when we need that surface. From this environment Chromium reports `ERR_HTTP_RESPONSE_CODE_FAILURE` rather than a 403 page, which suggests Akamai is either dropping the request or returning a non-standard response shape — distinct failure mode from Cloudflare's HTML interstitial.

`account.usta.com` (Auth0) is **not** Cloudflare-fronted and is reachable from this environment (200 on OIDC discovery, JWKS, and `/authorize` endpoints — the latter returns a 400 with title `USTA-DIGITAL-PROD` confirming the Auth0 tenant is brand-customized for USTA). Auth0 hosts the entire login dance unimpeded by the egress block, so the login UI side of recon would work here — but every post-login data fetch hits Cloudflare and fails. Net: nothing useful is reachable from this environment for the data plane.

## Rate-limit posture

_TBD by recon._ Default until measured: one request every 2 seconds, single concurrent connection. We'll relax this if recon shows the SPA itself fans out faster during a normal page render — we should not look slower than a normal user, but also not faster.
