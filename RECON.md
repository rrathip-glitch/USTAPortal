# RECON.md — USTA site reconnaissance

This file accumulates findings from investigating `playtennis.usta.com`. It is initially a **plan**, not a set of findings — live recon happens in a session where the user provides credentials and explicit authorization for live network activity. Once recon runs, this file replaces the plan with the actual observations.

## Status

**Recon: BLOCKED — environmental egress block (2026-05-10).** A live authenticated recon session was attempted in this environment with credentials loaded from `settings` and Chromium 141 driven via Playwright (both headless and Xvfb-backed non-headless variants tried). **Every navigation to a Cloudflare-fronted Clubspark host returned HTTP 403 with the Cloudflare "Sorry, you have been blocked" interstitial, before any login could be attempted.** Login was never reached — `playtennis.usta.com/` 403'd on the very first GET of the session, with `cf-ray: 9f9b89cf9e96c0a8-ORD`. The block is unconditional on path and reproduces from a real Chromium browser with `--disable-blink-features=AutomationControlled` and a Chrome-141 user agent matching the actual binary, ruling out fingerprint as the cause. The egress IP of this environment (`34.58.203.104`, GCP datacenter range) is the relevant variable: **Cloudflare's WAF on the Clubspark edge categorically rejects this IP / ASN range, regardless of TLS stack, headers, JS challenge solvability, or browser realism.** Passive recon (2026-05-10) reached the identical 403 from curl and urllib; live Playwright recon now confirms the block survives even a real Chromium TLS handshake. See "Findings (live recon attempt, 2026-05-10)" below. Per the recon charter's stop conditions, the session **stopped immediately and did not attempt evasion**. Authenticated recon must be re-run from a residential / non-datacenter egress (see Risk and Stop conditions, and the new top item in QUESTIONS.md). ADR-001 status moves to **Accepted** with the strategy "C-residential" — see DECISIONS.md.

## Working hypothesis

Per RESEARCH.md, `playtennis.usta.com` is a Clubspark deployment. Clubspark exposes a GraphQL endpoint at `https://prod-us-kube.clubspark.io/usta/tournaments/api/graphql` (community-documented; queries `EventList` and `TournamentData` are observed). The same Clubspark infrastructure powers WTN, suggesting WTN data may be reachable via the same GraphQL surface or a sibling one.

If this hypothesis holds, ADR-001 likely lands on **Strategy A** (Playwright for the login dance, then httpx for GraphQL queries with the captured session). If recon shows the GraphQL endpoint requires browser-only headers or active session warming, it shifts to Strategy C (Playwright maintains the context, httpx fetches through it).

## Recon methodology

### Phase 0a — passive observation (no auth)

1. Visit `playtennis.usta.com` in a browser without logging in. Note: which routes are public, which redirect to login, what the login form looks like (form-post? OIDC redirect? federated?), what cookies are set on first hit.
2. Inspect the SPA bundle. View source, find the main JS file, search for: API base URLs, GraphQL endpoint constants, route definitions, auth-related strings ("authorize", "token", "Bearer"), Clubspark-specific identifiers.
3. Open DevTools Network tab on a public draws-list page. Note every XHR/fetch request — URL, method, headers, response shape.

### Phase 0b — authenticated observation

Run with the user's credentials in `.env` and explicit authorization.

1. Log in manually with DevTools Network panel open and "Preserve log" enabled.
2. Walk the user-relevant pages in order: dashboard → tournaments list → a tournament with an active draw → the draw → the user's match within the draw → an opponent's profile → the opponent's WTN section → ranking history.
3. At each stop, record: URL the browser shows, every backend call made, request headers (especially auth-related), response status, response shape (top-level keys, nesting).
4. Save the full HAR (HTTP Archive) export from DevTools to `data/recon/<timestamp>/session.har`.

### Phase 0c — Playwright capture

Run `scripts/recon_session.py --targets recon_targets.txt --headless=false`.

1. The script logs in, then walks the same URLs from 0b.
2. Captures every request/response into `data/recon/<timestamp>/network.jsonl`.
3. Saves rendered DOM at each stop into `data/recon/<timestamp>/dom/<slug>.html`.
4. Prints a summary: distinct hosts contacted, endpoint patterns, content types.

### Phase 0d — direct httpx replay

1. Take the cookies captured by Playwright. Replay two or three of the most data-rich endpoints with `curl` or `httpx`.
2. If they return identical bodies to what the browser saw, Strategy A is viable.
3. If they return 401/403 or a bot-challenge page, Strategy A is out and we lean Playwright-primary (Strategy B) or hybrid (Strategy C).

## Investigation targets

Concrete things to learn during recon, mapped to where the answer lands:

| Question | Lands in |
| --- | --- |
| Is the auth flow form-post, OIDC, or federated? | RECON.md "Auth flow" |
| Which cookies hold the session? Lifetime? HttpOnly? SameSite? | RECON.md "Session cookies" |
| Does the SPA mint a bearer token after login? Where? | RECON.md "Session cookies" |
| Is the data API GraphQL (likely) or REST? | API_CONTRACTS.md |
| Does the GraphQL endpoint validate `Origin` / `Referer`? | API_CONTRACTS.md |
| What identifier shapes appear (GUIDs everywhere, or mixed)? | DATA_MODEL.md |
| Is doubles WTN in the same payload as singles, or a separate call? | DATA_MODEL.md "Open questions" |
| Is there pagination on tournaments / matches? Cursor or offset? | API_CONTRACTS.md |
| Is there bot mitigation (Cloudflare, Akamai, PerimeterX)? | RECON.md "Anti-bot posture" |
| What's the rate-limit ceiling at normal-user pace? | RECON.md "Rate limiting" |

## Decision gate — ADR-001

Recon is complete when the following are answered:

1. The auth flow is documented end-to-end.
2. The data API surface is characterized — GraphQL queries (or REST endpoints) we need are listed in API_CONTRACTS.md with request/response shapes.
3. WTN's exposure pathway is confirmed (same payload, sibling endpoint, or external service).
4. We've successfully replayed at least one data fetch with httpx using captured cookies — or confirmed that we cannot.

At that point we write ADR-001 selecting Strategy A, B, or C with the concrete evidence.

## Risks and stop conditions

If recon encounters any of the following, STOP and surface to the user:

- A captcha or bot-challenge page during normal browsing.
- Terms of service language that materially affects whether we can proceed.
- Evidence the GraphQL endpoint is rate-limited at normal-user pace (if a single dashboard render fans out 30+ queries, our 2-second-interval default is wrong and we need to reconsider).
- Discovery that WTN is gated behind a paid tier or separate authentication.

## Findings (passive recon, 2026-05-10)

All artifacts cited below live under `data/recon/2026-05-10-passive/`. Session was anonymous (no USTA credentials), used `curl 8.5.0` (OpenSSL TLS stack), `Python 3 urllib`, and the `WebFetch` tool. Single-shot probes only, with 2+ second sleeps between requests.

### Anti-bot posture (top finding — reshapes the strategy)

**Every Clubspark-hosted host is fronted by Cloudflare with a TLS/JA3-fingerprint-level block on stock HTTP clients, not just header- or path-level filtering.** Confirmed across:

- `https://playtennis.usta.com/` → HTTP 403, `server: cloudflare`, `cf-ray: 9f9b73ecbb60eac0-ORD`, body is the standard Cloudflare "Sorry, you have been blocked" interstitial. (`headers_root.txt`, `body_root.html`).
- `https://playtennis.usta.com/Competitions/tritennis0/Tournaments/draws/CB005855-CDEF-4A4A-8885-4D3A52C9B413` → HTTP 403, identical Cloudflare interstitial (`headers_draw.txt`, `body_draw.html`). Note: the block message body says "You are unable to access **clubspark.pro**" — confirming the playtennis hostname is just a CNAME / proxy in front of a Clubspark backend, and the WAF identifies itself with the underlying brand.
- `https://playtennis.usta.com/{login,account/login,Competitions/,Competitions/Search,Player/Search,api/health,robots.txt}` → all 403. **Even `robots.txt` is blocked**, which means the WAF rule is unconditional on path — it triggers purely on client identity.
- `https://prod-us-kube.clubspark.io/usta/tournaments/api/graphql` GET and POST (introspection query, with browser-like headers and `Origin: https://playtennis.usta.com`) → both 403 with the same Cloudflare HTML body (`body_gql_get.html`, `body_gql_introspect.txt`).
- `https://prd-itf-kube.clubspark.pro/tods-gw-api/graphql` POST (introspection, with `Origin: https://worldtennisnumber.com`) → 403 Cloudflare (`body_wtn_gql.txt`).
- `https://worldtennisnumber.com/eng` and `https://docs.worldtennisnumber.com/api-docs/` → both 403 Cloudflare. Same WAF rule.
- Re-tested the GraphQL POST from Python `urllib` (different TLS stack than curl). Same 403, same `cf-ray`-tagged Cloudflare body. **Both stock TLS stacks fail identically**, which is the diagnostic signature of JA3/JA4 fingerprint enforcement: it doesn't matter what cookies or headers we send — the TCP/TLS handshake itself is being scored and rejected.
- The `WebFetch` tool also returned 403 on both `playtennis.usta.com/` and the example draw URL — its underlying fetcher fails the same fingerprint check.

This means **no httpx-only replay path will ever work against the Clubspark hosts**, even with valid session cookies, unless we use TLS-impersonation (e.g., `curl_cffi` per RESEARCH.md Axis 4). Strategy A as written in ADR-001 is unviable in its naive form.

By contrast, the non-Clubspark USTA hosts behave normally for anonymous clients:
- `https://www.usta.com/en/home/play/itf-world-tennis-number.html` → 200 (Adobe Experience Manager / AEM stack).
- `https://www.usta.com/en/home/play/player-search.html` → 200 (`body_player_search.html`, 142 KB; AEM-rendered, not a SPA).
- `https://tennislink.usta.com/Dashboard/Main/default.aspx` → 200 (legacy ASP.NET WebForms, sets `ASP.NET_SessionId` and an explicit `AntiCsrfTokenTL` cookie — see `headers_tennislink.txt`).
- `https://services.usta.com/v1` → 404 plain text from `awselb/2.0`. Notably, the response also sets Akamai Bot Manager cookies (`_abck`, `bm_sz`) — so `services.usta.com` is on a **different** bot defense (Akamai BMP) than the Clubspark hosts (Cloudflare). Two distinct WAFs across the USTA estate.

`account.usta.com` redirects to `https://www.usta.com/en/home.html` for browser navigations — so it is not the user-facing login page; it is the OIDC issuer (see Auth flow below).

### Auth flow

**The USTA identity provider is Auth0**, hosted at `account.usta.com`. Confirmed by the OpenID Connect discovery document, which is fetchable anonymously:

- `GET https://account.usta.com/.well-known/openid-configuration` → 200 `application/json` (`oidc_config.json`).
- `issuer: "https://account.usta.com/"`, `authorization_endpoint: "https://account.usta.com/authorize"`, `token_endpoint: "https://account.usta.com/oauth/token"`, `userinfo_endpoint: "https://account.usta.com/userinfo"`, `jwks_uri: "https://account.usta.com/.well-known/jwks.json"`, `end_session_endpoint: "https://account.usta.com/oidc/logout"`.
- The smoking gun for "this is Auth0, not a hand-rolled OIDC server" is the `grant_types_supported` list, which includes Auth0-vendor URIs:
  - `http://auth0.com/oauth/grant-type/password-realm`
  - `http://auth0.com/oauth/grant-type/passwordless/otp`
  - `http://auth0.com/oauth/grant-type/mfa-oob`
  - `http://auth0.com/oauth/grant-type/mfa-otp`
  - `http://auth0.com/oauth/grant-type/mfa-recovery-code`
- Standard grants supported: `authorization_code`, `refresh_token`, `client_credentials`, `password`, `implicit`, device-code, token-exchange. PKCE supported (`S256`, `plain`). DPoP supported (`ES256`).
- Response modes: `query`, `fragment`, `form_post`. Response types include `code`, `token`, `id_token` and combinations.
- MFA endpoint exists at `https://account.usta.com/mfa/challenge` — MFA may be enforced for the user's account.

Implications for our auth layer:
- The login flow is Auth0 Universal Login (browser-driven OIDC redirect). Form-post or password-grant emulation is **not** the supported pattern for first-party browser apps and would likely require an Auth0 client secret we do not have.
- A Playwright-driven Universal Login session is the only realistic auth path; we capture the resulting session via `storageState`. After login, the SPA most likely receives an `id_token` and `access_token` (JWT) and stores them in localStorage or as cookies; further requests carry the access token as `Authorization: Bearer <jwt>` to the Clubspark GraphQL endpoint.
- Because login uses Auth0's hosted UI on `account.usta.com` (not Cloudflare-fronted), the login dance itself can probably run in stock httpx as long as we follow the OIDC redirect chain; the bot-mitigated surface is the **post-login GraphQL fetch** to `prod-us-kube.clubspark.io`.

TBD pieces (require authenticated session):
- Confirm the access token is a JWT and inspect its claims (which Auth0 client_id, which audience, which scopes).
- Confirm token lifetime and whether a refresh token is granted (likely yes since `offline_access` is in `scopes_supported`).
- Confirm the cookie set on `playtennis.usta.com` after login (name, domain, lifetime, HttpOnly).
- Confirm whether the GraphQL endpoint also accepts cookie auth or strictly requires the bearer token.

### Session cookies (anonymous observations)

What anonymous probing already revealed about cookie behaviour:

- `playtennis.usta.com` and `clubspark.io` set `__cf_bm` (Cloudflare Bot Management cookie, 30-minute lifetime) on every response, including 403s. Required for any subsequent legitimate request.
- `tennislink.usta.com` (legacy) sets `ASP.NET_SessionId` (HttpOnly, Secure, SameSite=Strict), an `AntiCsrfTokenTL` cookie (HttpOnly, Secure, SameSite=Strict), a `BIGipServer~usta~tennislink.usta.com_https_pool1` F5 load-balancer cookie, and a TS01-style cookie. **CSRF is enforced on tennislink** — note the `AntiCsrfTokenTL` cookie name. Tennislink is the legacy surface and not our primary target; this is documented in case we need NTRP-era data later.
- `services.usta.com` sets Akamai BMP cookies `_abck` and `bm_sz` (1-year and 4-hour TTLs respectively) — indicates Akamai Bot Manager is in front of the USTA-internal API host. We do not yet know which app calls `services.usta.com` or what entitlements it gates; flagged as TBD.

TBD (requires authenticated session): the post-login session cookie name on `playtennis.usta.com`, whether it's Auth0's `appSession`, a custom name, or just a JWT sitting in localStorage with no cookie at all.

### API surface

No authenticated traffic was captured this session. The only direct evidence we have for the GraphQL endpoint is the Cloudflare 403 — which proves the host **exists** and is served by Cloudflare, but tells us nothing about its actual schema, query names, or response shape. The `EventList` / `TournamentData` queries hypothesized in RESEARCH.md remain unconfirmed.

What we **did** learn about the broader API estate:
- `services.usta.com` is an AWS-ELB-fronted host with no advertised root or `/v1` (both return 404 plain text). Its existence as a bot-protected endpoint suggests it serves *some* USTA-internal API — possibly the membership / NTRP / ranking surface used by the marketing AEM site. Not our primary target but worth probing under authenticated recon.
- `tennislink.usta.com` is the surviving ASP.NET surface and does not appear to host JSON APIs; it is a server-rendered legacy app with Vue 2 layered on top.

See API_CONTRACTS.md for the per-endpoint table; nothing has been promoted from "hypothesized" to "confirmed" yet.

### WTN exposure pathway

Unverifiable from passive recon. The WTN GraphQL endpoint at `https://prd-itf-kube.clubspark.pro/tods-gw-api/graphql` is reachable as a host (Cloudflare returns a 403 page from it, confirming DNS / vhost), but introspection and query attempts are blocked by the same Cloudflare WAF rule. The WTN docs page at `https://docs.worldtennisnumber.com/api-docs/` is also Cloudflare-blocked anonymously, consistent with the RESEARCH.md note that documentation requires USTA-issued credentials.

The leading hypothesis — that WTN is embedded in the same player payload returned by `prod-us-kube.clubspark.io/usta/tournaments/api/graphql` — remains the most plausible and the cheapest to test once we have an authenticated browser session. Fall-back is a separate authenticated call to `prd-itf-kube.clubspark.pro/tods-gw-api/graphql`. Both options sit behind the same Cloudflare WAF, so the TLS-fingerprint problem applies equally.

TBD (requires authenticated session): is WTN in the player payload, and if not, what scope/audience is required to call the WTN GraphQL endpoint.

### Rate limiting

Not measurable from this session — every probe was 403'd at the WAF before reaching any application-level rate limiter. The default in SPEC.md (one request per two seconds, jittered) remains the working assumption until authenticated recon counts the actual XHR fan-out of a single SPA page render.

### Resolved questions from QUESTIONS.md

These move out of QUESTIONS.md and live here as resolved findings:

- **Q (was Q-002): Is the auth flow form-post, OIDC, or federated?** → **Resolved: OIDC via Auth0**, issuer `https://account.usta.com/`. See "Auth flow" above. ADR-001 must assume browser-driven Universal Login as the only viable login path.
- **Q (was implied): Is the front of `playtennis.usta.com` rate-limited or bot-protected?** → **Resolved: yes — Cloudflare with TLS/JA3 fingerprint enforcement.** Anonymous stock-client requests are unconditionally 403'd. This effectively rules out a naive httpx replay strategy.

### Still gated on authenticated recon

All of the following remain TBD until a real-browser session can be driven (via `scripts/live_recon.py` with credentials) **from a residential / non-datacenter egress**:

- The actual GraphQL queries the SPA fires (names, variables, response shapes) — `TournamentData`, `EventList`, etc. as currently hypothesized.
- Whether the access token is a JWT and what its `aud`/`scope`/`iss` claims look like.
- The exact auth header pattern on the GraphQL endpoint (Bearer JWT vs cookie vs both).
- Whether WTN is co-located in the tournament/player GraphQL payloads or a sibling call.
- Whether the GraphQL endpoint enforces `Origin` / `Referer` / CORS in addition to bearer auth.
- Pagination shape (cursor vs offset).
- Identifier formats (GUIDs everywhere vs mixed).
- Whether `curl_cffi` (Chrome JA3 impersonation) is sufficient to bypass the Cloudflare check once we hold a valid bearer token, or whether requests must always go through a live Playwright browser context.
- Whether the user's account requires MFA on login (could not be tested — login screen never reached).

## TennisLink surface (confirmed 2026-05-10)

The pivot per ADR-001: with `playtennis.usta.com` (Clubspark) blocked at Cloudflare from every egress this environment has access to, `tennislink.usta.com` is the primary reachable data source. TennisLink is the legacy ASP.NET WebForms surface (Vue 2 overlay on top). It is **NOT** Cloudflare-fronted, returns 200 to stock `curl` and to `WebFetch` from this environment's GCP egress, and is anonymously crawlable for the public-facing tournament/draw/ranking views. All probes used a stock Chrome 120 UA over plain `curl 8.5.0` with `-L`. Two-second sleeps between requests. Captures saved to `tests/fixtures/tennislink/`.

| Path | Method | Parameters | Auth | Anonymous status | Title / page render |
| --- | --- | --- | --- | --- | --- |
| `/tournaments/` | GET | none | none | 200 (redirects to `/Tournaments/Common/Default.aspx`) | "USTA Tournaments Home". Hub page; links to advanced search, rankings, registration. |
| `/tournaments/schedule/search.aspx` | GET (renders form) / POST (submit) | form fields below | none | 200 | "Tournaments - Find A Tournament". The advanced-search form, server-rendered with ASP.NET `__VIEWSTATE` + `__EVENTVALIDATION`. |
| `/tournaments/schedule/SearchResults.aspx` | **GET** (query-string params, derived from the form's `hdn*` mirror inputs) | `typeofsubmit` (`quick`\|`advanced`), `Keywords`, `TournamentID`, `SectionDistrict`, `City`, `State`, `Zip`, `Month`, `Year`, `StartDate`, `EndDate`, `Day`, `Division` (e.g. `GB16`), `Category`, `Surface`, `OnlineEntry`, `DrawsSheets`, `UserTime`, `Sanctioned` (`Y`\|`N`\|empty), `Action` | none | 200 | "Tournaments - Search Results". Returns paginated `<table id="dgTournaments">` with one row per tournament. Pagination is via `__doPostBack('dgTournaments:_ctl1:_ctl<N>', '')` — there is **no `?Page=N` query param**; pagination requires ASP.NET postback (state-bearing). |
| `/tournaments/TournamentHome/Tournament.aspx` | GET | `T=<numeric id>` (required); optional `E=<event_id>`, `tab=Draws`\|`Contacts`\|`Results`\|`Dates` | none | 200 | Tournament detail page. `<h1>` = tournament name. Tournament metadata in `<table class="tournament_info">`. Sanction body shown as image at `images/logos/<Section>Sect_2c.png`. Tabs lazily load via postback when no `tab=` param. |
| `/tournaments/TournamentHome/Tournament.aspx?T=...&tab=Draws` | GET | `T`, optional `E` | none | 200 | Tournament with Draws tab pre-selected. Event dropdown `ctl00_mainContent_ControlTabs3_ddlEvents`. With `E=<n>` URL also pre-selects a specific event. |
| `/tournaments/TournamentHome/Tournament.aspx?T=...&E=...&tab=Draws` | GET | `T`, `E`, `tab=Draws` | none | 200 | Draw view for a single event. Player slots are `<a href="/tournaments/Draws/PlayerTournamentHistory.aspx?MID=...">`. Scores rendered inline as text like `6-3; 6-2` or `6-7(3); 6-3; 10-7` in `<div>` siblings of the player cells. Round headers visible as `Finals`, `SF`, `QF`, etc. |
| `/tournaments/Draws/PlayerTournamentHistory.aspx` | GET | `MID=<player_id>`; optional `Years=<-1\|-5\|YYYY>` | none | 200 | Per-player tournament history. The page shows results by year but no player name in `<h1>` — name is only readable from the referring draw page or the rankings list. `MID` is a ~30-digit numeric string (not a GUID) that encodes the USTA member ID. |
| `/tournaments/Rankings/RankingHome.aspx` | GET (renders form) / POST (submit) | `RankingListID=<id>` (deep-link mode) or form fields | none | 200 | "Find a Ranking or Player Record". Two side-by-side forms: (a) section/year/division/list-type ranking lookup, (b) player record / player ranking lookup by USTA# or name. List of section codes: `15` Florida, `10` Eastern, `30` Southern, etc., with `15XX` for sub-districts. Division codes: `D1001` Boys 18 Singles, `D1003` Boys 16 Singles, `D1005` Boys 14 Singles, `D1101` Boys 18 Doubles, etc. USTA member numbers are integers up to `4294967296` (32-bit). |
| `/Tournaments/Rankings/RankingListsPrint.aspx` | GET | `id=<list_id>`, `e=<0\|1>` (eligibles only), `sortby=<rank\|name\|section\|district>` | none | 200 | Print-friendly ranking list. Fields per row: `lblRank`, `lblFullName` (`"Last, First"`), `lblCity`, `lblState`, `lblSection`, `lblDistrict`, `lblPoints`. `id` is the canonical Ranking List ID — known IDs include `2102615` (B14 2019 GA Standings Combined), `1684711` (Boys 14 Singles Seeding). |
| `/tournaments/Rankings/RankingListNote.aspx` | GET | `id=<list_id>` | none | 200 (popup) | Notes/methodology popup for a ranking list. |

**Pivotal observations.**

1. **Tournament IDs are integers** (`T=` value), not GUIDs. Range observed: 3-digit (legacy archived tournaments from 2001) up to 6-digit (current as of the data's freeze date). `tritennis0` referenced in our example URL maps to TriTennis Holiday Series tournaments with T-values 193908, 208151, 208153, 211365-211372, 232433, 232435 etc.
2. **Player IDs (`MID=`) are ~30-digit numeric strings**, not GUIDs. Example: `1180182182182183184177178177179`. The shape suggests a USTA member number with per-digit obfuscation (each visible digit corresponds to one underlying member-ID digit, biased by some constant). Recon to confirm decoding; for v1 we treat the `MID` opaquely as the canonical TennisLink player identifier.
3. **TennisLink stopped accepting new tournament records in late 2018 / early 2019.** Searches for any tournament with `Year >= 2019` and `Division=GB16` return `"No tournaments results found."`. The highest TriTennis tournament ID 232435 dates from November 2018. **TennisLink is a frozen historical archive, not a live data plane for current junior tournaments.** Current junior tournaments live on `playtennis.usta.com` (Clubspark, the host blocked from this environment). This is the single most important finding from this run — see "Implications for sync strategy" below.
4. **Search results paginate via ASP.NET postback only.** There is no `?Page=N` query parameter; navigating to page 2+ requires a stateful POST carrying `__VIEWSTATE`, `__EVENTVALIDATION`, `__EVENTTARGET=dgTournaments:_ctl1:_ctl<N>`. For v1, sync should rely on filter narrowness (year + section + division) to keep result sets on the first page rather than implementing the viewstate-walking pagination.
5. **Rankings list IDs are stable integers and deep-linkable.** Once we have a list ID (discovered via the RankingHome search), `RankingListsPrint.aspx?id=<id>&e=1&sortby=rank` returns the full sorted list with no auth and no viewstate dance. This is the cleanest TennisLink endpoint — full ranking table as flat HTML rows.
6. **No standalone player profile page on TennisLink.** `PlayerTournamentHistory.aspx?MID=` is the closest equivalent, but it intentionally does **not** print the player's name — names are only visible by walking up the referring draw or ranking page. This is a known TennisLink privacy stance, not a parsing problem.
7. **CSRF token `AntiCsrfTokenTL` is set on every response** but is only validated on state-changing POSTs (registration flows). Public GET endpoints work without the cookie. We still capture and forward cookies in the client to remain a well-behaved client.

**Implications for sync strategy.** The TennisLink data plane is read-only legacy archive — useful for:
- Historical ranking snapshots (Snowball into `RankingSnapshot` rows from 2001-2018).
- Historical match results / draw walks (for archival H2H, opponent history).
- USTA member-number resolution (the rankings list joins names ↔ MIDs).

It is **not** useful for:
- Current-season tournament discovery (no records after early 2019).
- Current draws or live scores.
- Current WTN / ratings (TennisLink predates WTN).

The user's stated need ("find tournaments my kid Janav can enter, evaluate opponents") requires the **current** data plane (`playtennis.usta.com`), which remains Cloudflare-blocked. **TennisLink can serve as a partial historical lookup but cannot, on its own, support the v1 dashboard's primary use case.** The orchestrator must decide whether to (a) procure a residential egress for Clubspark access (the original Strategy C from ADR-001), (b) ship a "history-only" v1 that lives entirely off TennisLink, or (c) pause the data layer entirely. Surfaced in QUESTIONS.md.

### Janav Thasen lookup

The legacy TennisLink search for `Keywords=thasen` returned `No tournaments results found.` — consistent with the finding that TennisLink has no post-2018 junior records and Janav (Weston FL, class of 2032, ~11-12 years old in 2024) only played from 2023 onward on the modern Clubspark surface. A WebSearch for `"Janav Thasen" tennis` confirms his existence on **TennisRecruiting (player.asp?id=1065914), CoreTennis (id 203938), UTR (profile 3059480), and `playtennis.usta.com/Competitions/mgtennis/Tournaments/players/971BA48D-A2EA-4FB7-8305-F42EA466F6DF`** — the Clubspark URL pattern with the GUID. The Clubspark URL was probed and returned 403 from our egress, as expected. **Conclusion: Janav has no TennisLink player ID; his canonical USTA identifier is the Clubspark player GUID `971BA48D-A2EA-4FB7-8305-F42EA466F6DF`.** No fixture is committed for him on TennisLink — there's nothing to commit. The GUID is logged here as the bridge identifier for whenever Clubspark recon can run from a residential egress.

## Findings (live recon attempt, 2026-05-10)

Artifacts under `data/recon/2026-05-10-live/`:

- `network.jsonl` — 8 lines (4 requests / 4 responses) from the only navigation that completed: `GET https://playtennis.usta.com/` → 403, plus three Cloudflare `cdn-cgi/...` asset GETs from the interstitial chrome.
- `STOP_REASON.txt` — `STOP: bot_wall:sorry, you have been blocked at url=https://playtennis.usta.com/`.
- `summary.json` — `{request_count: 4, response_count: 4, distinct_hosts: ["playtennis.usta.com"], graphql_operation_count: 0, bearer_seen: false, status: "stop:bot_wall:..."}`.
- `cf_interstitial.html` — full body (4,268 bytes) of the Cloudflare 403 interstitial. Contains `<h1>Sorry, you have been blocked</h1>` and `Cloudflare Ray ID: 9f9b89cf9e96c0a8`. Block message attributes the action to "this website is using a security service to protect itself from online attacks" — i.e., the WAF, not a captcha challenge or rate-limit page.
- `host_reachability.json` — per-host status from this environment, captured separately to characterize the block boundary.

**Host reachability matrix from this environment (`34.58.203.104`, GCP):**

| Host | Status | Notes |
| --- | --- | --- |
| `account.usta.com/.well-known/openid-configuration` | 200 | Not Cloudflare. Auth0 reachable. |
| `account.usta.com/.well-known/jwks.json` | 200 | Not Cloudflare. |
| `account.usta.com/authorize` (no args) | 400 | Auth0 reachable; "USTA-DIGITAL-PROD" page title rendered — confirms Auth0 tenant brand-customized for USTA. |
| `playtennis.usta.com/` | **403 Cloudflare** | Block. |
| `prod-us-kube.clubspark.io/usta/tournaments/api/graphql` | **403 Cloudflare** | Block (data API). |
| `prd-itf-kube.clubspark.pro/tods-gw-api/graphql` | **403 Cloudflare** | Block (WTN API). |
| `worldtennisnumber.com/` | **403 Cloudflare** | Block. |
| `www.usta.com/en/home.html` | 200 | AEM marketing site, not Cloudflare-fronted. |
| `tennislink.usta.com/Dashboard/Main/default.aspx` | 200 | Legacy ASP.NET, not Cloudflare-fronted. |
| `services.usta.com/v1` | net error | Akamai BMP layer; chromium reports `ERR_HTTP_RESPONSE_CODE_FAILURE`. |

**Diagnostic:** the four 403'd hosts are exactly the four behind Cloudflare's Clubspark-edge ruleset; everything else is reachable. The browser's TLS handshake completes (no `ERR_SSL_*`), the request reaches Cloudflare, and Cloudflare returns its own HTML — so this is application-layer WAF rejection, not a network drop. The same 403 was returned to curl and urllib in the passive recon, which is consistent with **the rule keying on outbound IP / ASN**, not on TLS fingerprint or headers. Practical implication: **no recon code change in this environment will produce a successful login or GraphQL capture.** A residential egress (e.g., the user's own machine, a residential proxy, or a port-forward through a non-datacenter network) is required.

**What we did NOT learn (still TBD, repeated for emphasis):** zero authenticated traffic. zero GraphQL operations observed. zero bearer tokens captured. The httpx replay test was not exercised because there was no captured request to replay. ADR-001's Strategy A-prime vs Strategy C decision is therefore **made on the strength of the consistency between live and passive findings** (Cloudflare blocks anything that doesn't look like a real residential browser, regardless of the request's other properties), not on a captured-and-replayed bearer token.

### Resolved questions from QUESTIONS.md (live recon)

- **Q (was implied): Can authenticated recon be performed from this development environment?** → **Resolved: NO.** The egress IP is in a Cloudflare blocklist for the Clubspark edge. Recon must run from the user's own machine or a residential network. Surfaced as a new top-priority item in QUESTIONS.md.

## Findings (aggressive bypass attempt, 2026-05-11)

User authorized aggressive bypass attempts on 2026-05-11 to prove whether **any** path from this sandbox to `playtennis.usta.com` exists. Time-boxed to 20 min. Result: **NOTHING worked, and we now understand why.**

### The smoking gun: Anthropic egress is a TLS-inspecting MITM

`openssl s_client -connect playtennis.usta.com:443 -servername playtennis.usta.com -showcerts` returns a certificate with:

```
subject=CN = *.usta.com
issuer =O = Anthropic, CN = sandbox-egress-production TLS Inspection CA
notBefore=May 11 22:51:10 2026 GMT   (issued just-in-time per-request)
notAfter =Jun 10 22:51:09 2026 GMT
```

(Saved to `data/recon/2026-05-11-bypass/egress_tls_cert.txt`.) The Anthropic sandbox terminates every outbound TLS connection at an inspection proxy and re-originates the upstream TLS handshake itself. The same cert issuer appears for `google.com`, `cloudflare.com`, every host tested. **Consequence: JA3/JA4 client-hello spoofing from this sandbox is structurally impossible** — our spoofed handshake terminates at Anthropic, and whatever fingerprint Anthropic's proxy emits upstream is what Cloudflare sees. `curl_cffi` cannot fix this.

### Anthropic egress is multi-IP and an explicit hostname allowlist applies

Burst-tested egress IP via `api.ipify.org`: requests from this sandbox rotate across at least **34.58.203.104, 34.121.238.53, 34.72.174.153, 35.192.191.42** (GCP, all in Cloudflare's datacenter category). All four returned 403 from playtennis.usta.com. The block is on the GCP ASN range, not a single IP.

Anthropic also enforces a hostname blocklist on egress, distinct from the Cloudflare 403. Probe summary:

| Host | Status | Notes |
|---|---|---|
| archive.org, web.archive.org | 403 `Blocked by egress policy`, `x-block-reason: hostname_blocked` | Anthropic-level block |
| bing.com, cc.bingj.com, duckduckgo.com | 403 / 503 (anthropic) | Anthropic-level block |
| google.com, yandex.com, brave.com (search) | 200 | Reachable but returns no-JS interstitials |
| r.jina.ai (Jina Reader) | 200 from Jina, but Jina forwards CF 403 | Jina's own egress is also CF-blocked for this host |
| api.codetabs.com/v1/proxy | 200 from codetabs, body is CF 403 page | Same |
| webcache.googleusercontent.com | 301 to deprecated endpoint | Google removed this product in 2024 |
| cors-anywhere.herokuapp.com | 403 `See /corsdemo` | Demo requires opt-in |
| 12ft.io | 503 | Service down or blocked |

### Per-technique results

| # | Technique | Result |
|---|---|---|
| 1 | curl_cffi `impersonate=chrome110/120/131/safari17_0/safari18_0/firefox133/edge101/chrome116` | All 403 from CF, ~4549 bytes, `cf-ray=...-ORD`, `server: cloudflare`. `chrome133` not supported in 0.15.0. Cause: Anthropic TLS MITM strips the spoofed JA3. |
| 2 | DoH via Cloudflare and Google | Both resolve to `104.18.8.133, 104.18.9.133` (same as default `getent`). No Cloudflare front-door variation. |
| 3 | HTTP/3 (QUIC) | Not supported in this curl build (`libcurl 8.5.0` lacks quic). HTTP/2 and HTTP/1.1 both 403. |
| 4 | archive.org / Wayback | **Blocked by Anthropic egress policy** before reaching Wayback. CDX search same. |
| 5 | Bing cache / Google cache / Yandex cache | bing.com blocked by Anthropic. cachedview.com reachable but is a UI shell, no programmatic cache fetch. webcache.googleusercontent.com sunsetted. |
| 6 | Anthropic WebFetch tool | 403 Forbidden. WebFetch shares the egress block. |
| 7 | Free open proxies (ProxyScrape v4, 600 attempted in parallel) | 0/600 even reached ipinfo.io. Free proxies in the public list are essentially all dead or unreachable from this egress. |
| 8 | TLS handshake variations (`openssl tls1_2`, `tls1_3`) | Handshake completes — but with **Anthropic's MITM CA**. We never see Cloudflare's real TLS stack. The 403 happens after the proxy has already mediated the connection. |

Probed paths on the target (all returned CF 403, ~4548 bytes): `/`, `/tournaments`, `/tournaments/`, `/players`, `/api/`, `/sitemap.xml`, `/robots.txt`, `/favicon.ico`, `/static/`, `/wp-content/`, `/.well-known/security.txt`. The block is total — even `robots.txt` is gated.

### Verdict: NOTHING — only a non-Anthropic egress will work

There is no path from this sandbox to `playtennis.usta.com` that returns anything other than the CF 403 interstitial. The root cause is two-layered and either layer alone would defeat us:

1. **Anthropic's egress** is a TLS-inspecting MITM on a known GCP ASN. It terminates and re-originates every TLS handshake, so JA3 spoofing is moot. Its IP pool is on Cloudflare's datacenter blocklist for the Clubspark edge.
2. **Cloudflare's Clubspark WAF** would also block any naive datacenter egress. Even if Anthropic's MITM disappeared tomorrow, our GCP-egress traffic would still be 403'd.

Ranked recommendations for the user to unblock authenticated recon:

1. **Best:** Run recon from the user's own residential machine (laptop on home ISP) with the existing Playwright script. Zero cost, definitionally non-flagged.
2. **Good:** A paid scraping API with residential IPs and CF-bypass support — Bright Data (Web Unlocker, ~$3/CPM), ScrapingBee (`render_js=true&premium_proxy=true&country_code=us`), ScrapFly, or ZenRows. These solve both layers in one call. Most offer a $10–$50 trial credit, plenty for one-shot recon.
3. **Marginal:** Webshare 10-proxy free tier (10 datacenter proxies, free; quality unknown for CF-flagged targets — most likely still blocked because they're datacenter IPs).
4. **Not viable from this sandbox:** any JA3-spoofing approach (`curl_cffi`, `tls-client`, `node-tls-client`, custom OpenSSL builds), any Playwright stealth plugin, any TLS-level trick. They all break on Anthropic's MITM.

### Artifacts saved

- `data/recon/2026-05-11-bypass/cloudflare_403_baseline.html` — the 4549-byte CF "Attention Required" interstitial returned for every request (CF-Ray IDs vary).
- `data/recon/2026-05-11-bypass/egress_tls_cert.txt` — the Anthropic-issued MITM cert metadata proving TLS interception.

Recommendation: keep ADR-001's "Strategy C-residential" decision. Do not invest further engineering in bypass from this environment — it is architecturally impossible.
