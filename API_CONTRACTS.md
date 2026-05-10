# API_CONTRACTS.md — USTA endpoint inventory

A live table of the endpoints we depend on. Populated by recon and refreshed every time schema drift is detected.

## Status

**Passive recon complete (2026-05-10); authenticated recon still required.** The rows below have been graded against what the 2026-05-10 passive probes actually observed. Most data-surface rows remain unconfirmed because the Cloudflare WAF blocks anonymous probing entirely; the auth-surface rows are now anchored on the OIDC discovery document, which is anonymously fetchable. Cell-by-cell evidence is in RECON.md "Findings (passive recon, 2026-05-10)" and the artifacts under `data/recon/2026-05-10-passive/`.

## Endpoint inventory

| Surface | URL | Method | Auth | Purpose | Status (2026-05-10) |
| --- | --- | --- | --- | --- | --- |
| OIDC discovery | `https://account.usta.com/.well-known/openid-configuration` | GET | None | Lists the Auth0 endpoints below | **Confirmed** — 200 JSON, anonymous-readable (`oidc_config.json`) |
| Auth0 authorize | `https://account.usta.com/authorize` | GET (browser redirect) | None initially | Begin OIDC code flow / Universal Login | **Confirmed exists** via OIDC discovery; flow not yet exercised |
| Auth0 token | `https://account.usta.com/oauth/token` | POST | Auth code + (optionally) PKCE verifier; client_id required | Exchange code for `access_token` + `id_token` (+ refresh_token if `offline_access` requested) | **Confirmed exists** via OIDC discovery; client_id and audience TBD |
| Auth0 userinfo | `https://account.usta.com/userinfo` | GET | `Authorization: Bearer <access_token>` | Fetch the authenticated user's claims | **Confirmed exists** via OIDC discovery |
| Auth0 JWKS | `https://account.usta.com/.well-known/jwks.json` | GET | None | Public keys for verifying id_token signatures | **Confirmed exists** via OIDC discovery |
| Auth0 logout | `https://account.usta.com/oidc/logout` | GET (browser redirect) | Session cookie or `id_token_hint` | End session | **Confirmed exists** via OIDC discovery |
| Auth0 MFA challenge | `https://account.usta.com/mfa/challenge` | POST | Per Auth0 MFA flow | MFA step (likely OOB or OTP) | **Confirmed exists** via OIDC discovery; whether enforced TBD |
| Tournaments GraphQL | `https://prod-us-kube.clubspark.io/usta/tournaments/api/graphql` | POST | TBD — likely `Authorization: Bearer <Auth0 JWT>` plus `Origin: https://playtennis.usta.com` | Tournament / draw / player / match data | **Host confirmed exists** (Cloudflare-fronted, 403 with cf-ray on every anonymous probe); request/response shape **unconfirmed**. Introspection blocked at WAF before reaching app. |
| WTN GraphQL | `https://prd-itf-kube.clubspark.pro/tods-gw-api/graphql` | POST | TBD — bearer token with WTN audience scope | Singles + doubles WTN | **Host confirmed exists** (Cloudflare-fronted, 403); fields unconfirmed. May or may not be needed if WTN is embedded in the tournaments payload. |
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

**Strongly suggested by passive recon: `Authorization: Bearer <Auth0 access_token>`** on all Clubspark GraphQL calls. Reasoning: `account.usta.com` is an Auth0 tenant (confirmed via OIDC discovery — see RECON.md), Auth0 SPAs by convention store the access token in memory and attach it as a Bearer header to API calls, and the GraphQL host lives on a separate domain (`clubspark.io`) from the SPA (`playtennis.usta.com`), which makes cookie auth awkward without a third-party cookie story we have no evidence of. Final confirmation requires authenticated session capture.

CSRF likely **not** required on the GraphQL endpoint since bearer-token auth is not vulnerable to CSRF in the cookie sense; but `Origin` / `Referer` validation is plausible at the gateway level.

## Anti-bot posture

**Cloudflare WAF in front of every Clubspark host with TLS/JA3 fingerprint enforcement.** Confirmed empirically: stock curl 8.5.0 (OpenSSL) and Python urllib both receive HTTP 403 + Cloudflare interstitial on every probe to `playtennis.usta.com`, `prod-us-kube.clubspark.io`, `prd-itf-kube.clubspark.pro`, `worldtennisnumber.com`, and `docs.worldtennisnumber.com` — including for `robots.txt`. Two different stock TLS stacks failing identically is the diagnostic for fingerprint-level blocking. Practical implication: any direct httpx call (even with valid Bearer token) will be 403'd unless tunnelled through a real browser context (Playwright `page.request`) or a TLS-impersonating client (`curl_cffi` with Chrome impersonation).

`services.usta.com` is on **Akamai Bot Manager** instead (separate WAF, sets `_abck`/`bm_sz`), so different evasion pattern if/when we need that surface.

## Rate-limit posture

_TBD by recon._ Default until measured: one request every 2 seconds, single concurrent connection. We'll relax this if recon shows the SPA itself fans out faster during a normal page render — we should not look slower than a normal user, but also not faster.
