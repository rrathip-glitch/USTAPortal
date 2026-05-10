# TODO.md — prioritized backlog

Live items. Completed items move to CHANGELOG.md and out of this file.

## Phase 0 — Reconnaissance (next)

- [ ] Get credentials + authorization (resolves Q-001)
- [ ] Spawn recon subagent (`.claude/agents/recon.md`)
- [ ] Run `scripts/recon_session.py` against the target URL list
- [ ] Populate RECON.md "Findings" section
- [ ] Populate API_CONTRACTS.md with confirmed endpoints + queries
- [ ] Confirm WTN exposure pathway (resolves Q-003)
- [ ] File ADR-001 (Extraction Strategy) — Accepted with rationale
- [ ] Capture two anonymized fixtures per entity into `tests/fixtures/`

## Phase 1 — Core pipeline (gated on Phase 0)

- [ ] Implement `src/auth/session.py` per ADR-001
- [ ] Implement `src/fetch/client.py` with rate limiter, retry, raw cache write
- [ ] Implement parsers in `src/parse/` per entity (one parser subagent each)
- [ ] Implement repositories in `src/store/repositories.py`
- [ ] Implement sync orchestrator (the `usta sync` CLI command)
- [ ] Schema-drift canary test (`tests/integration/test_schema_drift.py`)
- [ ] First green end-to-end run against the user's own tournaments

## Phase 2 — Intelligence

- [ ] `src/enrich/h2h.py` + tests
- [ ] `src/enrich/form.py` + tests
- [ ] `src/enrich/strength_of_draw.py` + tests
- [ ] `src/enrich/expected_outcome.py` (Elo from WTN) + tests

## Phase 3 — UI

- [ ] `/` dashboard
- [ ] `/tournaments` list
- [ ] `/tournaments/{id}` detail
- [ ] `/draws/{id}` bracket view with inline scouting cards
- [ ] `/players/{id}` scouting card
- [ ] `/h2h/{a}/{b}` head-to-head deep dive
- [ ] `/sync` manual trigger + status
- [ ] `/admin/raw/{hash}` raw cache inspector

## Phase 4 — Hardening

- [ ] Anonymized fixture set covering every entity
- [ ] Full unit + integration test pyramid green
- [ ] Smoke test against captured "known draw"
- [ ] Railway deploy with persistent volume attached
- [ ] Documented credential rotation procedure verified end-to-end
- [ ] Logging level + structured fields tuned for production triage

## Phase 5 — Optional

- [ ] UTR cross-reference (if obtainable for the user's account)
- [ ] Light Elo-style "expected outcome" tuning vs realized results
- [ ] Mobile-friendly polish pass
- [ ] Multi-user / shared dashboards for coach + parent

## Cross-cutting (any phase)

- [ ] Address open QUESTIONS.md items as the user responds
- [ ] Run `scripts/update_canonical_docs.py` at session boundaries
- [ ] Keep SPEC.md aligned with reality (the spec is allowed to drift; the drift just has to be intentional)
