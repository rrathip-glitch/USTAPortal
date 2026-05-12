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
