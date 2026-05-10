# TESTING.md — test strategy

The test pyramid for USTA Portal. The shape is wide at the bottom (cheap unit tests on parsers and math), narrower in the middle (integration tests against captured fixtures), narrowest at the top (full-pipeline smoke against one known draw).

## Pyramid

### Unit (fast, no IO)

Targets: parsers, score parsing, enrichment math, rate-limiter, auth state machine.

Conventions:

- One module under test per file: `tests/unit/test_<module>.py`.
- Pure functions where possible; constructors that take dependencies as args (no global singletons).
- Use `hypothesis` for any code with structured input — score parsing especially. Property: parse-then-format must round-trip; sets must obey tennis scoring (no 7-4 sets, tiebreaks land at 7-6 with parenthesized minor).

Coverage targets: 90% on `src/parse/`, `src/enrich/`, `src/models/`. Misses must be justified.

### Integration (medium, hits filesystem and SQLite)

Targets: parse-from-fixture, repository round-trips (insert → query), sync orchestrator with a mocked fetch layer (`respx` for httpx mocking).

Fixtures live in `tests/fixtures/<entity>/`. Every fixture is a real-shape USTA response that has been run through `tests/anonymize.py` (to be written) — real USTA IDs replaced with synthetic ones, names of non-public people zeroed, emails removed.

Coverage targets: 70% on `src/fetch/`, `src/auth/`, `src/store/`.

### Smoke (slow, full pipeline against captured fixtures)

One end-to-end test that runs the full sync pipeline against a captured "known draw" — every fetch is served from `tests/fixtures/known_draw/`, parsing runs end-to-end, the resulting database is asserted against a snapshot. This is the test that catches "I changed a parser and didn't realize it broke the orchestrator."

Lives at `tests/integration/test_known_draw_smoke.py`. Marked `slow`; runs in CI on push to main, not on every PR.

## Schema drift detection

The most insidious failure mode is USTA silently changing a field name and our parser silently producing partial data. Defenses:

1. **Schema canary**: a small integration test (`tests/integration/test_schema_drift.py`) that, when run with `--canary` flag, hits one known endpoint via the live fetch layer and diffs the response shape against `tests/fixtures/canary/expected_shape.json`. Fields appearing or disappearing fail the test loudly. Designed to run nightly via a cron Railway task once Phase 1 is live.
2. **`SchemaDriftError`**: parsers raise this rather than returning partial data. A field expected by the parser but missing from the response → fail. A new top-level field in the response → log a warning (we may want to start parsing it).
3. **Fixture freshness**: a CI job (later) re-runs sync against captured fixtures and verifies the resulting DB hashes match the committed snapshot.

## Property tests for tennis scoring

Score parsing is small but tricky. Properties to assert:

- A set ends with one player on 6 or 7 (or higher in a deciding-set tiebreak format).
- If a set is `7-6`, a tiebreak score is present and the loser scored < 7 of (or 6+ in extended formats).
- A walkover has no parsed sets but a winner.
- A retirement has at least one parsed set and a winner.
- Total games per set is bounded above (no 50-49 sets).

`hypothesis` strategies for these live in `tests/strategies.py` (to land with the score parser).

## Anonymized fixtures

Recon and live sync produce raw responses with real player names, IDs, and other PII. Before any fixture is committed:

- USTA IDs (GUIDs) are mapped through `tests/anonymize.py` to deterministic-but-fake GUIDs. The mapping is committed alongside.
- Names of non-public people: replaced with `Player_<short_hash>`.
- Email and phone fields: zeroed.
- The user's own name and ID can be left intact only if the user explicitly opts in; default is to anonymize even the primary user.

The anonymizer is itself tested.

## CI

`.github/workflows/ci.yml` runs on every push and PR:

1. `ruff check src tests`
2. `mypy src`
3. `pytest -q` (unit + non-slow integration)

The smoke test (`-m slow`) runs only on push to main.

## Local development loop

```bash
pip install -e ".[dev]"
playwright install chromium    # only if running recon scripts
ruff check . && mypy src && pytest
```

Before committing: re-run all three. The CI runs the same.
