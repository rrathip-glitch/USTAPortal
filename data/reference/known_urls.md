# Known canonical URLs and identifiers

User-supplied URLs and recon-discovered endpoints that are confirmed real,
indexed, or otherwise documented. Stored here so parser, fetch, and recon
agents can pivot from ground truth rather than guessing.

Last updated: 2026-05-11. Owner: Orchestrator (Rankings-First wave).

---

## User-supplied draw URL (2026-05-11)

```
https://playtennis.usta.com/Competitions/tritennis0/Tournaments/draws/CB005855-CDEF-4A4A-8885-4D3A52C9B413
```

Provenance: user-provided during the Rankings-First pivot wave. Per user, this
draw includes Janav Thasen and was showing live results as recently as a couple
of hours before 2026-05-11T12:00Z. This is the anchor URL for the first
real-data extraction attempt.

URL anatomy:
- Host: `playtennis.usta.com` (Clubspark surface, Cloudflare-fronted from
  datacenter IPs — see DECISIONS.md ADR-001).
- Path: `/Competitions/{org-slug}/Tournaments/draws/{draw-guid}`
- Org slug: `tritennis0` (TriTennis tournament organizer, Florida section).
- Draw GUID: `CB005855-CDEF-4A4A-8885-4D3A52C9B413`.

Intended uses:
- Recon anchor: confirm reachability via every available technique.
- Janav extraction: locate his entry in the draw, capture his player-profile URL.
- WTN-crawl seed: from this draw, traverse every player to their profile and
  extract singles/doubles WTN.
- Parser fixture: capture raw HTML/JSON for the Clubspark draw parser.

---

## TennisLink rankings — confirmed reachable surface

The legacy ASP.NET surface at `tennislink.usta.com` is NOT Cloudflare-fronted
and IS reachable from this development environment. It hosts current USTA
junior ranking lists. URL pattern:

```
https://tennislink.usta.com/tournaments/rankings/rankinghome.aspx?rankinglistid={LIST_ID}
```

Confirmed list IDs (corrected 2026-05-11 by the browse-Janav agent):

| LIST_ID  | Description                                                  | Player count | Freshness |
| -------- | ------------------------------------------------------------ | -----------: | --------- |
| **2072448** | **Boys' 12 (Combined) — CURRENT**                         | **1,014**    | **Current 2025/2026** — use this for v1 |
| 1684711  | Boys' 14 Singles — Seeding (current)                         | 1,156        | Current   |
| 1752987  | STA Boys' 16 (Combined) — Standings (current)                | 1,655        | Current   |
| 1234828  | Boys' 12 Singles — National Championship Seeding (STALE)     | 1,298        | Pre-2021 archive — Brandon Nakashima (ATP pro) appears in the top 3 |
| 1241792  | Boys' 12 — Combined (STALE)                                  | 1,299        | Pre-2021 archive |
| 1703790  | STA Boys' 14 — Combined                                      | —            | Unverified  |
| 1682454  | STA Boys' 16 — Combined                                      | —            | Unverified  |
| 1558027  | 12-Month Rolling — Men's 40                                  | —            | Unverified  |

Top-3 sanity check for list 2072448 (current Boys' 12 Combined): Quan Rudy
(Sacramento CA, No. California, 19,304 pts) / Razeghi Alexander (Humble TX,
Texas, 14,563 pts) / Woestendick Cooper (Olathe KS, Missouri Valley, 8,869 pts).
All real current 2025/2026 top juniors.

Parser column structure (table id `grdMain`, print view): 7 columns —
Rank, Name, City, State, Section, District, Points. Cell selector pattern:
`<span id="grdMain_ctl{NN}_lbl{Field}" class="FieldLabel">{value}</span>`
where `NN` is the 2-digit row index starting at `ctl02`. Field names:
`lblRank, lblFullName, lblCity, lblState, lblSection, lblDistrict, lblPoints`.

NOTE: the print endpoint has NO USTA member-ID column and NO anchor tags
wrapping names. To get player IDs for the WTN crawl, parse the non-print
`RankingHome.aspx?rankinglistid=<id>` form view where names link to
`?page=PlayerRecordInTournament&Usta=<id>`.

NOTE: Florida (or any other section) filtering via the print URL is NOT
supported — section filtering requires the ASP.NET form POST against
`RankingHome.aspx` carrying a fresh `__VIEWSTATE`. Of the 1,014 rows on
list 2072448, 87 are Florida-section; Janav is NOT among them, consistent
with him sitting below the 1,014-deep national cut.

Filters (ASP.NET form fields on the same page):
- Scope: National / Section (17 sections; Florida is Janav's) / District
- Year: 2001-2026
- List type: "12 Month Rolling Standings List", "Calendar Year Standings List",
  "Final Ranking", "Seeding List", and ~20 other variants

Player record links from the rankings table:
- `https://tennislink.usta.com/tournaments/.../?page=PlayerRecordInTournament&Usta={PlayerID}`
- Player ID format: numeric (e.g., `2010184411`) OR encrypted (e.g., `fVCPj1u967TGyJIKCs4IXA%3d%3d`)

Mobile alias (302-redirects to desktop):
- `https://m.tennislink.usta.com/rankinghome?RankingListID={LIST_ID}`

FRESHNESS VERDICT (resolved 2026-05-11): TennisLink rankings are
**historical-only**. Concrete reachability:

| Year       | Boys' 12 (D1007) National | Boys' 10 (D1009) National |
| ---------- | ------------------------- | ------------------------- |
| 2017-2020  | data present              | "No ranking information"  |
| 2021-2026  | "No ranking information"  | "No ranking information"  |

The B12 rankings plane froze in **early 2021** (last Final list published
2021-01-03). B10 was **never** nationally published on TennisLink. So
`rankinglistid=1234828` (1,298 players, indexed as "B12 Singles National
Championship Seeding") is a historical seeding snapshot, not current
standings.

Form-POST flow (the actual usable surface — already wired in
`src/fetch/tennislink_client.py:get_ranking_list`):

```
POST https://tennislink.usta.com/tournaments/Rankings/RankingHome.aspx
ctl00$mainContent$SectionDistrict=00   # 00 = National
ctl00$mainContent$Year=2018            # 2017-2020 inclusive for B12
ctl00$mainContent$Division=D1007       # B12=D1007, B10=D1009, B14=D1005,
                                       # B16=D1003, B18=D1001
ctl00$mainContent$ListType=-1          # -1=All, 0=Standing, 2=Final
ctl00$mainContent$btnSearch_Ranking=FIND IT!
```

Terminal print URL after locating a list-id: `RankingListsPrint.aspx?id=<list_id>&e=1&sortby=rank`.

Top of B12 2018 National Final (list_id=2082185) for sanity:
1. Quan, Rudy (CA) — 16,534 pts
2. Razeghi, Alexander (TX)
3. Charlap, Dylan (CA)
4. Woestendick, Cooper (KS)
5. Exsted, Maxwell (MN)

(2006-born; ~20 years old in 2026. Confirms historical not current.)

WTN exposure on TennisLink: **none**. The `WTN Rating Level:` strings in
`RankingHome.aspx` HTML are template stubs for the logged-in-user navbar
widget, not bound to looked-up player data. Player profile pages
(`PlayerRecordsPrint.aspx?listid=...&playerid=...`) surface tournament/match
results only, no WTN. WTN must come from the Clubspark surface.

Implication for Rankings-First: TennisLink can serve historical trajectory
context for older players (useful for the "12-month ranking trend" sparkline
on opponent scouting cards, when the opponent is old enough to have
2017-2020 records). It **cannot** answer "what is Janav's current Boys' 12
national ranking?" — that comes from Clubspark only.

Saved recon artifacts (2026-05-11 wave): see
`data/recon/2026-05-11-tennislink-rankings/` for the full set of probe
results that established this verdict.

---

## Clubspark GraphQL endpoints (reachability matrix, 2026-05-11)

Most are Cloudflare-fronted and require residential egress. The **stg-itf**
endpoint is the exception — it clears Cloudflare from this sandbox when the
client TLS-impersonates Chrome via `curl_cffi(impersonate="chrome131")`.

| Endpoint                                                        | Purpose                                | Reachable from sandbox |
| --------------------------------------------------------------- | -------------------------------------- | ---------------------- |
| `https://prod-us-kube.clubspark.io/usta/tournaments/api/graphql` | USTA tournament data (events, draws)   | NO — 403               |
| `https://prd-usta-kube.clubspark.pro/tournamentdesk-api/graphql` | USTA tournament-desk (organizer-side)  | NO — 403               |
| `https://prd-itat-kube.clubspark.pro/tournamentdesk-api/graphql` | Generic tournament-desk (ITAT-fronted) | NO — 403               |
| `https://prd-itf-kube.clubspark.pro/tods-gw-api/graphql`        | ITF/WTN production                     | NO — 403 (residential needed for real Janav WTN) |
| **`https://stg-itf-kube.clubspark.io/tods-gw-api/graphql`**     | **ITF/WTN staging — REACHABLE via curl_cffi chrome131** | **YES** — schema + WTN data for fully-registered persons |

Known queries (introspection-confirmed on stg-itf 2026-05-11):

Tournaments:
- `publishedEvents(tournamentId, previewMode)` → returns events list
- `publishedTournament(id, previewMode)` → returns `id, level, formatConfiguration, division { ageCategory { minimumAge, maximumAge, todsCode, type }, gender, ratingCategory }, timings, pricing`
- `tournament(id)` → returns tournament metadata; UNAUTHENTICATED for non-public fields (the tournament's existence in Clubspark is itself confirmable)

People / WTN:
- `person(id: { identifier, type })` → single person record. `type` is from `PersonIDEnum`: `ID | ClubsparkID | TennisID | NationalID | ExternalID | PersonID`
- `persons(pageArgs, filter, sort)` → paged list of people
- `publicPersons(...)` → public-visibility persons (unauthenticated)
- `worldTennisNumber(tennisID)` → returns a SINGLE `WorldTennisNumber` (not a singles/doubles bundle). Schema: `confidence, ratingDate, tennisNumber, prevTennisNumber, type (SINGLE | DOUBLE), gameZoneUpper, gameZoneLower, source, isRanked`
- A Person object carries `worldTennisNumbers: [WorldTennisNumber!]` — iterate to find SINGLE vs DOUBLE
- `worldTennisNumberHistory(...)` / `wtnLastYear` / `wtnPast(tennisID, startDate, endDate)` → trajectory queries
- `matchUpStatistics` / `matchUpAggregatedCount` → match-level stats (auth required)

ID-shape correction: Janav's Clubspark GUID `971BA48D-A2EA-4FB7-8305-F42EA466F6DF`
is most likely a `ClubsparkID` (not a `TennisID` — TennisIDs follow the
`AAANNNNNNN` format, e.g., `USA1234567`). Stg lookup by ClubsparkID returns
null for Janav; a stub record exists under the auto-generated tennisID
`JAN9450835` with placeholder birthDate `1970-01-01` and null
`worldTennisNumbers`. **His real WTN is only in production** —
`prd-itf-kube.clubspark.pro` which is Cloudflare-blocked. Residential
proxy (Bright Data Web Unlocker) or a residential-captured Bearer token
is required to fetch it.

Working query templates (validated 2026-05-11 against PRODUCTION
`prd-itf-kube.clubspark.pro` via Bright Data Web Unlocker, and against
STAGING `stg-itf-kube.clubspark.io` via `curl_cffi(impersonate="chrome131")`):

Lookup by TennisID:
```graphql
{ person(id: { identifier: "<tennisID>", type: TennisID }) {
    id tennisID nativeGivenName nativeFamilyName birthYear
    worldTennisNumbers { tennisNumber type confidence isRanked ratingDate }
} }
```

Search by name (use this when you only have first+last from a TennisLink
ranking row):
```graphql
{ publicPersons(filter: { search: { term: "<first last>" } }) {
    items {
      id tennisID nativeGivenName nativeFamilyName birthYear
      worldTennisNumbers { tennisNumber type confidence isRanked ratingDate }
    }
} }
```

`SearchFilterOptions` schema (introspected 2026-05-11):
- `term: String!` (required)
- `fuzzy: Boolean`
- `exactMatch: Boolean`
- `autocomplete: Boolean`

Note: the previous attempt with `searchTerm` was wrong — that field doesn't
exist. The field is just `term`. Likewise `country` is NOT a field on
`Person` — drop it from selection sets.

Janav's production record (queried 2026-05-11):
- tennisID: `JAN9450835`
- nativeGivenName: `"Thasen"`, nativeFamilyName: `"Janav"` (note: first/last
  appear swapped in the database; respect this in any string-match code)
- birthYear: `0` (placeholder; minor whose DOB is suppressed)
- `worldTennisNumbers: null` — Janav has NO WTN yet. He is in the system
  but unrated. Likely because he's young (~11-12) and has not entered enough
  ITF-affiliated events to be assigned a WTN.
- His sister Vihana Thasen (tennisID `THA5459427`) does have a WTN:
  singles 27.97 / doubles 31.55.

His Clubspark GUID `971BA48D-A2EA-4FB7-8305-F42EA466F6DF` returns
`person: null` for all six `PersonIDEnum` types — that GUID does not
appear in this production ITF dataset under any indexed identifier.

Auth: USTA Connect (Clubspark SSO) at `https://login-playtennis.usta.com/`.
Developer-portal contact: `ustaconnect@usta.com`.

Canonical playtennis tournament/draw URL shape (corrected 2026-05-11):
`https://playtennis.usta.com/<orgslug>/Tournaments/overview/<guid>` — no
`/Competitions/` prefix. The user-supplied form with `/Competitions/` appears
to be a redirect/alias. Google indexes the `/overview/` path.

---

## Janav Thasen — cross-platform identifiers

Confirmed from OSINT during the Rankings-First wave. The Clubspark USTA ID is
the canonical primary key in our data model.

| Platform                  | Identifier                                | Notes                                       |
| ------------------------- | ----------------------------------------- | ------------------------------------------- |
| USTA / Clubspark          | `971BA48D-A2EA-4FB7-8305-F42EA466F6DF`    | Primary key. Already seeded in the dev DB.  |
| TennisRecruiting.net      | `1065914`                                 | TR national rank: 146 (TR composite, not USTA). 5th grader, class of 2032. |
| UTR (Universal Tennis)    | `3059480`                                 | `https://app.utrsports.net/profiles/3059480` (rating gated). |
| CoreTennis                | `203938`                                  | `https://www.coretennis.net/tennis-player/janav-thasen/203938/profile.html`. 2026 YTD: 1 USTA National Level 3 played (Wesley Chapel FL, R32 exit). |

Location: Weston, FL (Broward County) → USTA **Florida section**.
Sister (also in junior tennis): Vihana Thasen — TR `1020714`, CoreTennis `192850`, Girls 12s.

USTA national rank: NOT publicly indexed for Janav. With 1 USTA national
tournament played in 2026 YTD and a 31-36 past-year W-L, his USTA national
position (if any) needs the TennisLink form-submission to recover. The
TennisRecruiting rank 146 is the strongest *public* proxy until then.

---

## Bright Data Web Unlocker — verified API shape (2026-05-11)

Endpoint: `POST https://api.brightdata.com/request`
Auth: `Authorization: Bearer <BRIGHT_DATA_API_KEY>` (NOT HTTP Basic — the
previous design used customer_id+zone+password Basic auth, which is the
*proxy-mode* style; we're using REST-mode with a single API token).
Content-Type: `application/json`

Payload schema (verified by trial against the live API; the API rejects
unknown keys with `"error":"Request validation failed","error_code":"validation"`):

```json
{
  "zone": "<zone_name>",        // required; e.g. "web_unlocker1"
  "url": "<target_url>",        // required
  "format": "raw",              // "raw" returns upstream body verbatim; default returns JSON envelope
  "country": "us",              // ISO-2 country for the residential exit IP
  "method": "POST",             // optional; defaults to GET
  "body": "<raw post body>",    // optional; only valid for POST. KEY IS "body", NOT "data"/"payload"
  "headers": {                  // optional; passed through to the target
    "Content-Type": "application/json"
  }
}
```

Verdicts from probe (2026-05-11):
- `playtennis.usta.com/` static homepage: 200, 53,648 bytes — Cloudflare cleared
- `playtennis.usta.com/Competitions/.../draws/<guid>` (SPA shell): 200, 53,551 bytes — Cloudflare cleared but bracket data is hydrated client-side; need GraphQL for the data
- `prd-itf-kube.clubspark.pro/tods-gw-api/graphql` (production WTN GraphQL): 200 — schema fully responsive; real WTN data returns for searches like `publicPersons(filter: { search: { term: "Rudy Quan" } })` -> `tennisNumber: 6.1` etc.

Account state at point of test: `customer: hl_7bae0245`, zone `web_unlocker1`
active. Response time ~4-5 seconds per call. Trial credit ~$5 / ~1,500 requests.

Zone listing: `GET https://api.brightdata.com/zone/get_active_zones` with
Bearer auth returns `[{"name":"web_unlocker1","type":"unblocker"}]`.

Account status: `GET /status` returns `{"status":"active","customer":"...",
"can_make_requests":false,"auth_fail_reason":"zone_not_found",...}` — the
"can_make_requests:false" + "zone_not_found" is a misleading default; once
the zone is supplied in the request payload, calls work.

Implementation note for `src/fetch/residential_proxy.py`: the
`BrightDataWebUnlockerBackend` class was scaffolded assuming Basic auth +
customer_id/zone/password env vars. Adjust to Bearer auth + a single
`BRIGHT_DATA_API_KEY` + `BRIGHT_DATA_ZONE` (default "web_unlocker1") env
var. The payload shape above is the verified one — replace any `data`,
`payload`, `postdata` key with `body`.

## How to use this file

When dispatching a new agent that needs to talk to USTA infrastructure or
that needs Janav's identifiers, point the agent at this file in their prompt:

> Read `/home/user/USTAPortal/data/reference/known_urls.md` for the canonical
> URL and identifier table.

When a new URL, endpoint, or identifier is confirmed, append it here.
Don't delete entries — annotate them as deprecated if they stop working,
since a deprecated entry is itself useful intelligence (it tells the next
agent not to retry that path).
# Recommended addition to `data/reference/known_urls.md`

Append this section below the existing Clubspark GraphQL section. All facts here are confirmed via Bright Data Web Unlocker probes on 2026-05-11/2026-05-12 (recon session 2026-05-11-clubspark-rankings).

---

## USTA current-rankings API surface (2026-05-12)

The modern "Tournament Rankings" tab on USTA player profiles is served by
the AEM-fronted **prod-api-playtennis.usta.com** REST API (NOT the
Clubspark GraphQL endpoints, NOT TennisLink). The Vue/AEM page configures
itself via:

```js
playtennis.externalApiConfig = {
  googleMapsApiKey: "...",
  apiBasePath: "https://prod-api-playtennis.usta.com"
};
```

(captured from `https://playerapp.usta.com/` and any
`https://www.usta.com/en/home/play/player-search/profile.html` page).

### Confirmed endpoints (from AEM `<v-api-container endpoint="...">` declarations)

All bodies are JSON; method is POST unless noted. The
`endpoint-security-type` attribute is documented per route below.

| Endpoint                                                          | Method | Security    | Purpose                                                  |
| ----------------------------------------------------------------- | ------ | ----------- | -------------------------------------------------------- |
| `/usta/api?type=playerInfo`                                       | POST   | public      | Player bio + ratings + WTN by UAID                       |
| `/usta/api?type=playerRankings`                                   | POST   | **public**  | **Current rankings list per UAID (the rankings tab data)** |
| `/usta/api?type=playerRanklists&uaid={uaid}`                      | GET    | public      | List of available rank lists for player (catalog IDs)    |
| `/usta/api?type=playerBiography&uaid={uaid}`                      | GET    | public      | Public biography                                         |
| `/usta/api?type=playerPicture&uaid={uaid}`                        | GET    | public      | Profile photo                                            |
| `/dataexchange/profile/search/public`                             | POST   | public      | Public player search (name or USTA ID)                   |
| `/dataexchange/playhistory`                                       | POST   | **private** | Results / play history grid                              |
| `/dataexchange/playhistory/year`                                  | POST   | private     | Filter: years dropdown                                   |
| `/dataexchange/{uaid}/playhistory/category`                       | GET    | private     | Filter: event-category dropdown                          |
| `/dataexchange/{uaid}/playhistory/ranklists?year={year}`          | GET    | private     | Filter: rank-list dropdown per year                      |
| `/dataexchange/{uaid}/playhistory/ranklists/publishDates?...`     | GET    | private     | Filter: publish-date dropdown                            |

### POST body shapes (captured from `:post-body-map`)

```jsonc
// /usta/api?type=playerRankings
{ "selection": { "uaid": "<UAID-GUID>" } }

// /usta/api?type=playerInfo
{
  "selection":   { "uaid": "<UAID-GUID>" },
  "output":      { "ratings": true, "extendedProfile": true, "wtn": true }
}

// /dataexchange/profile/search/public
{
  "pagination": { "pageSize": 51, "currentPage": 1 },
  "selection":  { "searchTerm": "<name or USTA ID>" }
}
```

### UAID identifier shape

The `selection.uaid` field is the same Clubspark GUID we already track for
Janav: `971BA48D-A2EA-4FB7-8305-F42EA466F6DF`. Confirmed by hash-routing
in the player-profile URL — clicking from search lands at
`https://www.usta.com/en/home/play/player-search/profile.html#?uaid=<UAID>`
and the Vue page forwards that hash param into the request body's
`selection.uaid` (mapped via `"source": "hashUrlParam"`).

### Reachability from this sandbox (2026-05-12)

| Path                                          | Direct curl | Bright Data Web Unlocker | Status |
| --------------------------------------------- | ----------- | ------------------------ | ------ |
| `prod-api-playtennis.usta.com/` (root)        | (untested)  | 200 / 3-byte body ("api") | reachable headers, body suppressed |
| `prod-api-playtennis.usta.com/usta/api?...`   | (untested)  | upstream 403 (Akamai/CSRF) | requires session cookies |
| `prod-api-playtennis.usta.com/dataexchange/profile/search/public` | (untested) | upstream 403            | requires session cookies |

The upstream `403 Forbidden` is **not** Cloudflare — Bright Data clears
Cloudflare. It is the application's own auth/CSRF layer (OneTrust /
Akamai bot-detection / first-party session cookie). Even routes flagged
`endpoint-security-type="public"` enforce session validation.

`data_format: "markdown"` (which engages Bright Data's headless Chrome
renderer) DOES execute the Vue JS but the resulting page shows:
- "Sign in to view player results" on the Results tab
- "Whoops, something went wrong." on the Rankings tab

So even server-side browser rendering through a residential IP doesn't
bypass it — the API enforces an authenticated user-agent + session token
that only the real login flow produces.

### What works without auth (verified)

| GraphQL endpoint                                                  | Reachable | Useful for current rankings?                                          |
| ----------------------------------------------------------------- | --------- | --------------------------------------------------------------------- |
| `prd-itf-kube.clubspark.pro/tods-gw-api/graphql`                  | YES via Bright Data | WTN only (no USTA ranking points); no `rankings`/`standings` queries |
| `prd-usta-kube.clubspark.pro/tournamentdesk-api/graphql`          | YES via Bright Data | Has `rankingsAndRatings(csTournamentEventId)` but UNAUTHENTICATED returns `{"code":"UNAUTHENTICATED"}`. Per-event seeding only — not section/national lists. |
| `prod-us-kube.clubspark.io/usta/tournaments/api/graphql`          | NO — nginx 404 | (endpoint does not exist at this path) |
| `prd-usta-kube.clubspark.pro/unified-search-api`                  | nginx 404 on root + every probed path | (path discovery needed; reference appears in comp-main.js but actual paths unknown) |

### `tournamentdesk-api` queries (full list, 30 queries)

competitionFormat, draftTournaments, tournamentUrls, dualMatch, dualMatches,
dualMatchesPaginated, personEventEligibility, eventCost,
combineParticipantsEligibility, person, **tournamentPublic** (UNAUTH OK),
tournamentEvent, matchScorecard, **rankingsAndRatings** (AUTH REQUIRED),
settings, orgConfig, orgConfigForTournament, tournamentPolicies,
fullTournament, tournamentIdList, tournamentInfo, linkableTournaments,
tournamentFeatures, tournamentLevelConfig, tournamentsForTeam,
personByUaidOrEmail, tournamentStaffList, tournamentMatchUpsByDay,
tournamentRoles, worldTennisNumber

Schema confirmed by introspection POST to that endpoint with
`{"query":"{ __schema { queryType { fields { name } } } }"}`. Saved to
`data/recon/2026-05-11-clubspark-rankings/schema-prd-usta-kube.clubspark.pro_tournamentdesk-api_graphql.json`.

### `RankingsAndRatings` type shape

```graphql
type RankingsAndRatings {
  eventId: UUID
  data: [ParticipantRankingsAndRatings]
}
type ParticipantRankingsAndRatings {
  participantId: ID
  ranking: JSON
  rating: JSON
}
```

`csTournamentEventId` arg is required `UUID!`. Returns null payload until
authenticated. This is the per-event seeding view (the in-tournament view
the organizer sees when seeding a draw), not the global standings list.

### Path-forward options for current rankings

1. **USTA OAuth (preferred).** The page's session-cookie/CSRF gate is
   produced by `auth-playtennis.usta.com` (OAuth2 implicit flow,
   client_id `clubspark-ui`). Requires the user to log in with their
   USTA Connect account and capture the bearer token + Akamai
   `_abck` / `bm_sz` cookies. With those headers the
   `prod-api-playtennis.usta.com` REST endpoints should return data.

2. **Bright Data Scraping Browser** (different product from Web
   Unlocker — supports sticky sessions and full real-browser fingerprint).
   Would establish a session cookie automatically and let the API call
   succeed. Higher cost per request.

3. **Per-event `rankingsAndRatings` via authenticated tournamentdesk-api.**
   Useful for seed-rank-at-tournament context but doesn't give national
   /sectional ranking lists. Would also need an organizer token.

4. **Continue using TennisLink historical data** for any pre-2021 picture
   (already documented above) and accept that current USTA national/section
   rankings are not retrievable from a datacenter IP without
   authenticated session cookies.

### Janav-specific data recovered this session

- UAID confirmed identical to Clubspark GUID:
  `971BA48D-A2EA-4FB7-8305-F42EA466F6DF`
- Profile URL: `https://www.usta.com/en/home/play/player-search/profile.html#?uaid=971BA48D-A2EA-4FB7-8305-F42EA466F6DF`
- The profile page is reachable through Bright Data (200, 309,530 bytes
  static SPA shell). After Bright Data's headless Chrome renders it, the
  Rankings tab shows "Whoops, something went wrong" — proof the rankings
  API call fired and 403'd. Confirms Janav's player record exists in the
  prod-api dataset, just not retrievable without auth.

### Reference URLs that point users to USTA rankings (indexed by Google)

These are the published help articles — they all funnel users back to the
login-gated profile/rankings page:

- `https://customercare.usta.com/hc/en-us/articles/10063729808020-How-to-Check-Tournament-Rankings`
- `https://customercare.usta.com/hc/en-us/articles/34182368259220-How-to-Search-for-a-Player-and-View-their-Tournament-Rankings`
- `https://customercare.usta.com/hc/en-us/articles/360051797471-Junior-National-Standings-List-FAQs`
- `https://www.usta.com/en/home/play/rankings.html`
- `https://playerapp.usta.com/`

### Section/organizer-slug rankings pages — all stale punts to TennisLink

The `playtennis.usta.com/{slug}/Adults/Rankings` pages exist for several
sections but they ARE all 1-line static pages that just link out to
`tennislink.usta.com/tournaments/rankings/rankinghome.aspx?Section=<id>&Division=<code>`.
Verified for `ustasouthern` (98KB page, body content = single link).
Other section/junior variants probed:

| URL                                                                  | Status                |
| -------------------------------------------------------------------- | --------------------- |
| `/ustaflorida`                                                       | 200 — section home, no rankings link in static HTML |
| `/florida`                                                           | 200 — programming page, no rankings link |
| `/USTA/Juniors/Rankings`                                             | 200 — 404 page        |
| `/usta/Juniors/Rankings`                                             | 200 — 404 page        |
| `/Florida/Juniors/Rankings`                                          | 200 — 404 page        |
| `/usta-florida`                                                      | 200 — empty stub      |
| `/ustasouthern/Adults/Rankings`                                      | 200 — punts to TennisLink |

Conclusion: the `/Rankings` URL pattern on Clubspark org slugs is **not** the
modern path. The modern path is the `usta.com/...player-search/profile.html`
flow described above.
