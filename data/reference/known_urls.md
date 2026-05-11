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

Confirmed list IDs (OSINT, 2026-05-11):

| LIST_ID  | Description                                       | Player count |
| -------- | ------------------------------------------------- | -----------: |
| 1234828  | Boys' 12 Singles — National Championship Seeding  | 1,298        |
| 1241792  | Boys' 12 — Combined                               | —            |
| 1684711  | Boys' 14 Singles — Seeding                        | —            |
| 1703790  | STA Boys' 14 — Combined                           | —            |
| 1682454  | STA Boys' 16 — Combined                           | —            |
| 1558027  | 12-Month Rolling — Men's 40                       | —            |

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

NOTE on freshness: TennisLink stopped accepting new *tournament* records in
late 2018 (see STATE.md). The *rankings* surface freshness needs separate
verification — the rankings agent and the TennisLink-rankings recon agent
(in flight as of 2026-05-11) will confirm whether the lists above contain
current 2025/2026 standings or are stale.

U10 boys: list IDs not yet indexed publicly. Reachable via the same form
by selecting age category in the dropdown.

---

## Clubspark GraphQL endpoints (Cloudflare-fronted)

All require bypass / residential egress until ADR-001's egress rider is
satisfied (see DECISIONS.md, Q-011).

| Endpoint                                                        | Purpose                                    |
| --------------------------------------------------------------- | ------------------------------------------ |
| `https://prod-us-kube.clubspark.io/usta/tournaments/api/graphql` | USTA tournament data (events, draws)       |
| `https://prd-usta-kube.clubspark.pro/tournamentdesk-api/graphql` | USTA tournament-desk (organizer-side)      |
| `https://prd-itat-kube.clubspark.pro/tournamentdesk-api/graphql` | Generic tournament-desk (ITAT-fronted)     |
| `https://stg-itf-kube.clubspark.io/tods-gw-api/graphql`         | ITF/WTN — World Tennis Number queries       |

Known queries (community-documented, primary source: Blake Stevenson gist):

Tournaments:
- `publishedEvents(tournamentId, previewMode)` → returns events list
- `publishedTournament(id, previewMode)` → returns `id, level, formatConfiguration, division { ageCategory { minimumAge, maximumAge, todsCode, type }, gender, ratingCategory }, timings, pricing`

People / WTN:
- `person(id)` → single person record
- `persons(pageArgs, filter, sort)` → paged list of people
- `publicPersons(...)` → public-visibility persons
- `worldTennisNumber(tennisID)` → returns WTN singles + doubles
- `worldTennisNumberHistory(...)` → WTN trajectory
- `wtnLastYear` / `wtnPast(tennisID, startDate, endDate)` → time-windowed WTN
- `matchUpStatistics` / `matchUpAggregatedCount` → match-level stats

Auth: USTA Connect (Clubspark SSO) at `https://login-playtennis.usta.com/`.
Developer-portal contact: `ustaconnect@usta.com`.

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

## How to use this file

When dispatching a new agent that needs to talk to USTA infrastructure or
that needs Janav's identifiers, point the agent at this file in their prompt:

> Read `/home/user/USTAPortal/data/reference/known_urls.md` for the canonical
> URL and identifier table.

When a new URL, endpoint, or identifier is confirmed, append it here.
Don't delete entries — annotate them as deprecated if they stop working,
since a deprecated entry is itself useful intelligence (it tells the next
agent not to retry that path).
