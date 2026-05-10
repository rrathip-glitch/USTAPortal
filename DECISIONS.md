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
