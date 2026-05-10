# DECISIONS.md — Architecture Decision Records

Append-only. New ADRs go at the bottom. Status changes happen in place but the original entry is never deleted — to supersede an ADR, file a new one and set the old one's status to "Superseded by ADR-NNN".

## ADR-001 — Extraction Strategy

**Status:** Accepted (2026-05-10) — Strategy C (Playwright-resident requests), with the operational rider that **all recon and sync must run from a residential / non-datacenter egress IP**.

**Context.** USTA's `playtennis.usta.com` is the data source. We need to know whether to fetch via httpx (with replayed session cookies), via Playwright (browser-driving the SPA), or a hybrid. The choice affects the entire fetch layer, error handling, rate-limit behavior, and what kinds of CI tests are even possible.

**Options.**

- **A — httpx with replayed auth.** Playwright drives the login dance once to acquire cookies; bulk fetches go through httpx. Fast, scriptable, easy to test. Viable only if the API endpoints accept replayed cookies without browser-only headers.
- **B — Playwright primary.** Every fetch goes through a Playwright browser context. Slower, heavier, but bypasses any browser-fingerprinting check. Hard to mock in tests.
- **C — Hybrid.** Playwright maintains a long-lived browser context that warms the session; httpx fetches go through the context's network (or alongside it, sharing cookies). More complex but flexible.

**Decision.** Pending recon. Research strongly suggests Strategy A is viable because the underlying surface is Clubspark GraphQL, which is a well-behaved JSON API and not an HTML SPA. Recon validates by attempting a direct httpx call with captured cookies.

**Pre-recon evidence (2026-05-10, passive only — not sufficient to flip status).** Anonymous probes against the relevant hosts (see RECON.md "Findings (passive recon, 2026-05-10)") produced two facts that materially shift the leaning:

1. **The Clubspark hosts (`playtennis.usta.com`, `prod-us-kube.clubspark.io`, `prd-itf-kube.clubspark.pro`, `worldtennisnumber.com`) are uniformly fronted by Cloudflare with TLS/JA3 fingerprint enforcement.** Both curl (OpenSSL) and Python `urllib` receive HTTP 403 + Cloudflare interstitials on every probe — including `robots.txt`, which proves the rule is unconditional on path. This is fingerprint-level blocking, not header- or cookie-level. Implication: **naive Strategy A (stock httpx with replayed cookies) will not work** — even with a valid Auth0 bearer token in hand, the TLS handshake itself will be rejected. Strategy A is only viable if augmented with `curl_cffi` (Chrome JA3 impersonation), making it effectively "Strategy A-prime: TLS-impersonating httpx."

2. **The auth surface is OIDC via Auth0** (issuer `https://account.usta.com/`, confirmed by `account.usta.com/.well-known/openid-configuration` returning a JSON document containing the unmistakable `http://auth0.com/oauth/grant-type/...` vendor URIs). Implication: login is browser-driven Universal Login, not a form POST we can replicate. Playwright is required for the login dance regardless of which fetch strategy we pick — meaning Strategy A and Strategy C both rely on Playwright for auth and differ only in whether bulk fetches go through the browser context (C) or through a TLS-impersonating httpx client warmed with the Playwright-captured token (A-prime).

The leading post-passive-recon expectation is therefore **either Strategy A-prime (Playwright login → `curl_cffi` httpx with bearer token) or Strategy C (Playwright everywhere)**, with the choice between them gated on whether `curl_cffi` actually clears the Cloudflare check once it carries a real bearer token. We will not know until authenticated recon runs. Strategy A in its naive httpx form is effectively eliminated. Strategy B (Playwright-only without any httpx) remains a fallback if `curl_cffi` also fails.

**Live-recon evidence (2026-05-10) — strategy decision filed.** `scripts/live_recon.py` was executed in this development environment with credentials loaded from `settings`, Chromium 141 driven via Playwright in both legacy headless and Xvfb-backed non-headless modes, with `--disable-blink-features=AutomationControlled`, a Chrome-141-matching user agent, an `init_script` that hides `navigator.webdriver`, plus realistic locale/timezone/viewport. **Every navigation to `playtennis.usta.com` returned HTTP 403 with the standard Cloudflare "Sorry, you have been blocked" interstitial (`cf-ray: 9f9b89cf9e96c0a8-ORD`).** Login was never reached. A side-by-side reachability probe from the same browser confirmed `account.usta.com` (Auth0, not Cloudflare-fronted) returns 200 while all four Clubspark-edge hosts (`playtennis.usta.com`, `prod-us-kube.clubspark.io`, `prd-itf-kube.clubspark.pro`, `worldtennisnumber.com`) return 403 — see `data/recon/2026-05-10-live/host_reachability.json`. The environment's egress IP is `34.58.203.104` (GCP datacenter range), and the consistency between this live result and the prior passive curl/urllib results is the diagnostic for **IP/ASN-level blocking**, not TLS-fingerprint or browser-realism blocking. Per the recon charter's stop conditions, the script halted on the first bot-wall and did not attempt evasion.

**Decision.** Adopt **Strategy C — Playwright maintains a long-lived browser context, all data fetches go through that context (`page.request.fetch` or `context.request.post`)**. Rationale, anchored on the evidence:

1. **Strategy A-prime (TLS-impersonating httpx via `curl_cffi`) cannot be tested in this environment** because the Cloudflare block fires regardless of TLS fingerprint. We do not have a captured bearer token to replay, and we cannot acquire one here. Filing it as the chosen strategy would be guessing. Strategy C, by contrast, is the *strictly more general* option — it will work in any environment where login succeeds in a real browser, because every request leaves the browser context and inherits the same TLS handshake, cookies, and warmed session as the SPA itself. Strategy A-prime, if later viable, is a perf optimization on top of C, filable as a separate ADR (likely ADR-004) once a residential capture proves it.
2. **Auth is unambiguously Auth0 Universal Login** (passive-recon OIDC discovery + live-recon authorize-endpoint title `USTA-DIGITAL-PROD`). Playwright is mandatory for the auth dance regardless. The Strategy A-prime case was always "Playwright for login + httpx for bulk" — it shares half its surface with Strategy C anyway, so the marginal complexity of choosing C is small.
3. **Strategy B (Playwright with no httpx anywhere)** was never seriously in play because the OIDC discovery, JWKS, and other public Auth0 endpoints can be hit with httpx safely. Strategy C is effectively "B for the data plane, httpx for the public-Auth0 plane" — a strict subset of B's shape, slightly more efficient.
4. The choice is also the **lowest-risk-to-flip** option: if Cloudflare ever rejects a Playwright-resident request (e.g., behind a JS challenge that requires explicit human interaction), we know immediately and have all the same browser state to debug from. There is no "did we get the impersonation right?" black-box failure mode the way `curl_cffi` introduces.

**Operational riders (mandatory for Strategy C as filed).**

- **Sync and recon must run from a residential egress.** This environment cannot reach the data plane, full stop. The runbook documents this constraint; the Railway deploy plan in SPEC.md §12 needs a corresponding note on whether Railway's egress IPs are also Cloudflare-blocked (this is **a new TODO and a new question** — see QUESTIONS.md). If Railway's egress is blocked, we either need a residential proxy (e.g., a small egress relay on the user's home network) or a different host entirely.
- **The fetch layer in `src/fetch/` is built around `playwright.async_api.BrowserContext` as the primary IO primitive.** A long-lived context is opened at sync start, login is driven once, then per-entity fetches call `context.request.post(url, data=..., headers=...)` or navigate via `page.goto` and read responses with `page.on('response', ...)`. The two-second default rate limit in SPEC.md applies as a sleep between fetches.
- **The raw cache is unchanged** (per SPEC §5): every fetch writes the unparsed response to `data/raw/<endpoint>/<hash>.<ext>`. Strategy C only changes who *makes* the request, not what we *do with it*.
- **Strategy A-prime remains a future optimization.** Once a residential recon session captures a bearer token and confirms its lifetime + audience + scopes, we file ADR-004 to test whether `curl_cffi` with that bearer can clear Cloudflare and provide a faster bulk path.

**Consequences.**

- Pro: works on any host where login succeeds. No TLS-impersonation black box.
- Pro: lowest cognitive load — one IO primitive, one debugger (Playwright Inspector), one set of headers to reason about.
- Pro: graceful failure — if Cloudflare ever requires interactive challenge solving, we already have the browser instance to surface the page to the user.
- Con: heavier than httpx. Each request carries the cost of a Playwright round-trip (~tens of ms vs ~ms for httpx). For our scale (~hundreds of requests per nightly sync) this is irrelevant; for batch backfills it may matter and is the trigger for ADR-004.
- Con: harder to mock in tests. Mitigated by the raw-cache-as-source-of-truth design — unit and integration tests run against fixture raw responses, not the live fetch layer.
- Con: depends on the egress not being Cloudflare-blocked. Hard environmental dependency, surfaced in the runbook and as a top-priority QUESTIONS.md item for the user to confirm Railway's posture before Phase 4 deploy.

---

## ADR-002 — Storage layer: raw SQLite vs SQLAlchemy ORM

**Status:** Accepted

**Context.** v1's data model is small (eight tables, ~40 columns total). We can either hand-roll SQL via the stdlib `sqlite3` module or pull in SQLAlchemy 2.x (with or without an ORM layer).

**Decision.** Hand-roll. Schema lives in `src/store/db.py` as a single `SCHEMA_SQL` string, applied via `executescript` on init. Repositories take an `sqlite3.Connection` and return Pydantic models via plain queries.

**Rationale.** The model is too small to amortize SQLAlchemy's complexity. Raw SQL keeps us close to the data, which helps when debugging schema-drift fallout (you read the SQL, you know exactly what's stored). Migrations are a YAGNI for v1 — when we need them, we'll switch to SQLAlchemy + Alembic and that becomes ADR-003. SQLAlchemy is a non-negligible dependency to install and configure correctly for async usage with SQLite.

**Consequences.**

- Pro: simpler, smaller install, no ORM impedance mismatch.
- Pro: any future maintainer reads SQL, not class hierarchies.
- Con: when we need migrations, we'll do work to switch.
- Con: ad-hoc SQL is slightly more error-prone than ORM-validated queries — mitigated by the test suite covering repository round-trips.

---

> _Future ADRs land below as they're filed._
