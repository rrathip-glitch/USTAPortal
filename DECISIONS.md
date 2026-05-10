# DECISIONS.md — Architecture Decision Records

Append-only. New ADRs go at the bottom. Status changes happen in place but the original entry is never deleted — to supersede an ADR, file a new one and set the old one's status to "Superseded by ADR-NNN".

## ADR-001 — Extraction Strategy

**Status:** Proposed (pending Phase 0 recon)

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

**Status remains Proposed**; this entry documents the strengthened expectation only. The decision is filed once `scripts/recon_session.py` produces evidence of an actual bearer-replay attempt against the GraphQL endpoint.

**Consequences.** TBD per resolution.

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
