# RECON.md — USTA site reconnaissance

This file accumulates findings from investigating `playtennis.usta.com`. It is initially a **plan**, not a set of findings — live recon happens in a session where the user provides credentials and explicit authorization for live network activity. Once recon runs, this file replaces the plan with the actual observations.

## Status

**Recon: PARTIAL — passive only (2026-05-10).** Anonymous probes from this session were uniformly blocked at the edge (see Findings below); no authenticated traffic has been captured because this session has no credentials and no real browser. Authenticated recon is still required before ADR-001 is decided. Passive findings have, however, **materially shifted the leading hypothesis** away from Strategy A (pure httpx replay) toward Strategy C (browser-resident requests), and have surfaced an Auth0-OIDC auth fact that was previously unknown. ADR-001 status remains **Proposed** pending authenticated session evidence.

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

All of the following remain TBD until a real-browser session can be driven (via `scripts/recon_session.py` with credentials):

- The actual GraphQL queries the SPA fires (names, variables, response shapes) — `TournamentData`, `EventList`, etc. as currently hypothesized.
- Whether the access token is a JWT and what its `aud`/`scope`/`iss` claims look like.
- The exact auth header pattern on the GraphQL endpoint (Bearer JWT vs cookie vs both).
- Whether WTN is co-located in the tournament/player GraphQL payloads or a sibling call.
- Whether the GraphQL endpoint enforces `Origin` / `Referer` / CORS in addition to bearer auth.
- Pagination shape (cursor vs offset).
- Identifier formats (GUIDs everywhere vs mixed).
- Whether `curl_cffi` (Chrome JA3 impersonation) is sufficient to bypass the Cloudflare check once we hold a valid bearer token, or whether requests must always go through a live Playwright browser context.
