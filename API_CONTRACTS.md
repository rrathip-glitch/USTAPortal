# API_CONTRACTS.md — USTA endpoint inventory

A live table of the endpoints we depend on. Populated by recon and refreshed every time schema drift is detected.

## Status

**Initial state: hypothesized only.** Nothing in this file has been verified against authenticated traffic yet. Treat every row as "research-suggested" until ADR-001 is filed.

## Hypothesized endpoints

Based on RESEARCH.md and community-documented Clubspark surfaces:

| Surface | URL | Method | Auth | Purpose | Confirmed? |
| --- | --- | --- | --- | --- | --- |
| Login | `https://playtennis.usta.com/...` (recon to find) | POST | None → cookies | Establish session | ❌ |
| GraphQL | `https://prod-us-kube.clubspark.io/usta/tournaments/api/graphql` | POST | Cookies + likely Origin/Referer | Tournament/draw/player/match data | ❌ (research-only) |
| WTN | TBD — possibly same GraphQL endpoint, possibly worldtennisnumber.com | TBD | TBD | Singles + doubles WTN | ❌ |
| Player profile | TBD | TBD | TBD | Player metadata, ranking history | ❌ |

## GraphQL queries (hypothesized)

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
| TournamentData | TBD | TBD | TBD | ❌ |
| EventList | TBD | TBD | TBD | ❌ |
| Draw | TBD | TBD | TBD | ❌ |
| Player | TBD | TBD | TBD | ❌ |
| PlayerRankings | TBD | TBD | TBD | ❌ |
| PlayerMatches | TBD | TBD | TBD | ❌ |

## Schema drift log

Append-only. Each entry: date, query, what changed, recovery action.

> _No drift recorded yet — schema baseline lands with first successful recon._

## Auth header pattern

_TBD by recon._ Likely candidates:

- Pure cookie auth (`Cookie: <session_cookie>=...`).
- Cookie + CSRF token in a custom header on mutating requests.
- Bearer token minted post-login, passed as `Authorization: Bearer <token>`.

## Rate-limit posture

_TBD by recon._ Default until measured: one request every 2 seconds, single concurrent connection. We'll relax this if recon shows the SPA itself fans out faster during a normal page render — we should not look slower than a normal user, but also not faster.
