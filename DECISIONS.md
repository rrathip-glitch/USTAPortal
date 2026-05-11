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

## ADR-005 — Multi-source fetch with TennisLink primary, Clubspark deferred

**Status:** Accepted (2026-05-10).

**Context.** ADR-001 (Accepted, Strategy C) committed the project to Playwright-resident Clubspark fetches *if* an egress that Cloudflare doesn't block were available. Live recon on 2026-05-10 (`data/recon/2026-05-10-live/host_reachability.json`) confirmed that this environment's GCP egress and any datacenter-range egress we can reasonably reach from a CI agent or a Railway worker is uniformly Cloudflare-403'd on every Clubspark host (`playtennis.usta.com`, `prod-us-kube.clubspark.io`, `prd-itf-kube.clubspark.pro`, `worldtennisnumber.com`). The user re-running `scripts/live_recon.py` from a residential egress (Q-011) is the unblock for Clubspark, but that gate is not closed today and v1 cannot ship behind it. Simultaneously, the same recon found that **`tennislink.usta.com`** — the legacy ASP.NET WebForms surface — is reachable from this environment (200 OK, sets `ASP.NET_SessionId` + `AntiCsrfTokenTL`) and serves enough of the data model (tournaments, draws, matches, players) to power v1 in the meantime. The architectural question this ADR answers: how do we structure the fetch layer so that v1 ships on TennisLink today *and* lights up Clubspark automatically once Q-011 resolves, without a second rewrite?

**Options.**

- **TennisLink only.** Build the fetch layer around a single TennisLink driver, treat Clubspark as out of scope. Pro: simplest. Con: throws away the strategy C design and forces a second rewrite when Clubspark unblocks. Con: TennisLink is the *legacy* surface — fields that exist only on Clubspark (notably WTN in its full shape, doubles WTN, real-time draw updates) are lost.
- **Wait for residential egress.** Block all of Phase 1 on Q-011. Pro: ships against the higher-fidelity source first. Con: indefinite wait, no actual product output until the user runs recon from their laptop.
- **Dual-source via FetchRouter.** Build a router (`src/fetch/router.py`) that exposes the entity-level surface (`get_player`, `get_tournament`, `get_draw`) and dispatches to TennisLink or Clubspark based on a configurable preference order and the shape of the entity id. TennisLink lands today, Clubspark lands as a stub that raises `NotImplementedError`. Router catches the deferred error (and a new `BlockedEgressError` for Cloudflare-style refusals) and falls through to the next source.

**Decision.** Option 3 — dual-source via FetchRouter.

**Rationale.**

1. **Ships v1 today.** TennisLink is the primary surface, the orchestrator is wired end-to-end against the router, and parsers can land independently on each source. No work is gated on Q-011 except the Clubspark-specific entity coverage.
2. **No rewrite when Clubspark unblocks.** The router already prefers Clubspark for GUID-shaped ids and falls through cleanly when the stub fires. Replacing the stub with the real `BrowserContext`-driven client is a single-file swap; the orchestrator, parsers, and storage layer don't move.
3. **Graceful degradation.** If Clubspark works for some entities and not others (e.g., the live recon succeeds for tournaments but fails for the WTN sub-call), the router falls through per-call rather than per-source. The user always gets the best data the environment can produce.
4. **Honest about provenance.** Source attribution survives into the raw cache — every cache entry already carries the request URL, which encodes the source — so when both sources cover the same entity we can compare them and prefer the higher-fidelity one in the parse layer.

**Implementation surface.**

- `src/fetch/client.py` — unchanged. The generic httpx transport (rate limit, retry, cache, redaction). Used by `TennisLinkClient` and, in future, by any HTTP plane that doesn't need Playwright.
- `src/fetch/tennislink_client.py` — owned by the TennisLink subagent. Interface: `search_tournaments`, `get_tournament`, `get_draw`, `get_player`, `close`. Returns raw HTML/JSON bodies.
- `src/fetch/clubspark_client.py` — stub. Same interface, every method raises `NotImplementedError` pointing at ADR-001 and Q-011.
- `src/fetch/router.py` — `FetchRouter` with the dispatch logic above and a new `BlockedEgressError` for fallthrough.
- `src/fetch/__init__.py` — exports `FetchClient`, `FetchRouter`, `BlockedEgressError`, and the existing exception types.
- `src/cli/main.py` — `usta sync` and `usta sync-loop` instantiate the router, walk player → tournaments → draws → matches, and produce a coherent summary even when parsers are not yet wired.

**Consequences.**

- Pro: v1 ships against the TennisLink data model today. No infinite wait for residential recon.
- Pro: when the user runs recon from their laptop and Clubspark unblocks, lighting it up is one ADR (closing Q-011) and one client implementation — no orchestrator, parser, or storage churn.
- Pro: the same router handles the Railway egress question (SPEC §12). If Railway's egress is also Cloudflare-blocked on the Clubspark plane, the deploy still works — Clubspark falls through, TennisLink runs.
- Con: the parse layer has to be source-aware for any entity covered by both sources. Mitigated by the parsers being pure functions of the raw body — the source tag is just another input.
- Con: two sources means two surfaces of schema drift. The schema-drift canary (SPEC §9) needs to fire per source. Out of scope for this ADR but a documented follow-on.

---

## ADR-006 — Rankings-First Pivot and Sanctioned-Bypass Agent Role

**Status:** Accepted (2026-05-11).

**Context.** v1 as originally specified was end-to-end: pre-tournament briefing covering the user's projected path through every draw he is entered in, with opponent scouting cards backed by current rankings, WTN, recent results, and head-to-head. That target stands as the v1 ceiling but produces no visible value to the user until the full pipeline (auth, fetch, parse, store, enrich, render) lands. The user has redirected v1 to a narrower inaugural deliverable: U12 boys US national rankings on the dashboard with Janav highlighted, plus U10 boys if reachable, and per-player WTN crawled from individual profile pages. Simultaneously, the user has sanctioned aggressive Cloudflare-bypass attempts against the Clubspark edge for this legitimate single-user case — explicitly overriding the recon agent's "stop on bot wall" rule, but only for a new dedicated agent role; the recon charter itself is unchanged. ADR-001 (Strategy C) and ADR-005 (multi-source FetchRouter) both remain in force; this ADR layers a new agent role on top of them and resequences Phase 1.

**Options.**

- **(1) Keep current end-to-end plan, defer rankings.** Continue building toward the full pre-tournament briefing as the first user-visible artifact. Pro: no resequencing, no new agent role. Con: longer time to any visible value, indefinite if any single layer stalls.
- **(2) Rankings-first with no bypass.** Narrow scope to the rankings pipeline but accept whatever data plane is reachable today (TennisLink + archive snapshots only). Pro: tight scope, single agent role addition (rankings). Con: leaves Clubspark deferred indefinitely, accepts whatever data fidelity TennisLink happens to expose.
- **(3) Rankings-first plus sanctioned bypass agent.** Narrow scope to the rankings pipeline *and* spin up a parallel bypass agent role that pursues aggressive Cloudflare-evasion against the Clubspark edge under explicit per-session user authorization. Pro: parallel narrowing-of-scope and broadening-of-data-plane. Con: two new agent roles, additional risk surface from the bypass attempts.

**Decision.** Option 3.

**Rationale.** The rankings-first scope shortens time-to-real-data: a populated ranking list with WTN is something the user can read and react to without waiting for the rest of the briefing stack. Tighter scope means faster wave cycles — each wave produces a visible delta rather than a deep but invisible foundation slab. The bypass agent is a constrained role: it is only invoked with explicit per-session user authorization, and its charter is its own document separate from the recon charter, so the recon agent's safety properties ("stop on first bot wall") are preserved for all default work. The sibling-agent decomposition matches the multi-agent coordination protocol in AGENTS.md — new roles are added by filing a charter, not by widening an existing agent's scope. Bypass success or failure is logged, evaluated, and folded back into the data-plane decision via a follow-on ADR if a technique proves stable.

**Consequences.**

- Pro: faster delivery of visible value — the dashboard shows real U12 boys rankings and real WTN within one wave once a reachable data plane is identified.
- Pro: the bypass agent opens up the Clubspark egress decision space (currently frozen behind Q-011) without polluting the recon agent's charter; if any bypass technique succeeds, Q-011 collapses from "unblock data at all" to "choose the long-term egress path".
- Pro: well-scoped — one age category (U12), one country (US), one gender split (boys), one data type per pass (rankings, then WTN). Easy to test, easy to verify on the dashboard.
- Con: the full pre-tournament briefing slips to Phase 2; the original v1 ceiling is now v2's floor.
- Con: aggressive bypass increases the risk of USTA account flags or IP-level rate-limit responses; the user has accepted this risk per the pivot statement and is the only authorization point for each bypass session.
- Con: the per-player WTN profile crawl multiplies request volume by the rankings depth (a 256-name ladder is 256 extra profile fetches); the existing one-request-per-two-seconds default is preserved, but a deeper crawl needs an explicit rate-limit posture documented in the rankings agent's charter.

**Cross-references.** ADR-001 (Strategy C; still in force), ADR-005 (multi-source FetchRouter; still in force), Q-010 (resolved this wave — Resend for notifications), Q-011 (partially obsoleted — if any bypass technique succeeds the question collapses to long-term egress choice rather than data-plane unblock).

---

> _Future ADRs land below as they're filed._
