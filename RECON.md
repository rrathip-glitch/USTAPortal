# RECON.md — USTA site reconnaissance

This file accumulates findings from investigating `playtennis.usta.com`. It is initially a **plan**, not a set of findings — live recon happens in a session where the user provides credentials and explicit authorization for live network activity. Once recon runs, this file replaces the plan with the actual observations.

## Status

**Recon: NOT STARTED.** No authenticated traffic has been captured. All claims below are hypotheses to be validated. ADR-001 (Extraction Strategy) is **Pending**.

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

## Findings (populated after recon)

> _Empty. To be filled by the recon subagent. Each finding cites the network.jsonl entry or HAR snapshot it came from._

### Auth flow

_TBD_

### Session cookies

_TBD_

### API surface

_TBD; see API_CONTRACTS.md for the endpoint table_

### WTN exposure pathway

_TBD_

### Anti-bot posture

_TBD_

### Rate limiting

_TBD_
