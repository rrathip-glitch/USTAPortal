# CHANGELOG.md

Append-only. Most recent at the top.

---

## 2026-05-10 — Strength-of-draw enrichment

Implemented `strength_of_draw(draw, entries, ratings, focal_player_id, projected_path=None) -> StrengthOfDrawResult` in `src/enrich/strength_of_draw.py` as a pure function. Field aggregates (size, mean/median/min/max opponent rating, unrated count) and projected-path aggregates (mean, hardest, easiest) computed on a single rating axis where lower = stronger; the WTN-vs-ranking fallback decision is the caller's. Withdrawn entries are excluded from field and rating aggregates. Missing ratings are never imputed as zero — they increment `unrated_count` and skip aggregation. When `projected_path` is omitted the path is reconstructed from standard single-elim pairing on `position`, with each post-round-1 opponent picked as the lowest-rated entry in the focal player's bracket block (ties broken by smaller position; unrated treated as worst). Round-robin and other non-single-elim formats yield an empty path and `None` path aggregates. Added `tests/unit/test_strength_of_draw.py` with ten cases covering field aggregates, unrated handling, withdrawals, the path heuristic, round-robin, focal-not-in-entries, unrated path opponents, empty fields, explicit-path override, and round-2 tiebreak. ruff-clean, mypy-strict, pytest passes.

— enrich agent

---

## 2026-05-10 — Bootstrap

Project scaffolded from an empty repo. Established the canonical doc set and the multi-agent coordination protocol that drives ongoing work.

**Created.** Directory structure (`src/`, `tests/`, `scripts/`, `data/`, `.github/`, `.claude/`). Root config (`.gitignore`, `pyproject.toml`, `.python-version`, `LICENSE`, `.env.example`). Railway deployment config (`Procfile`, `railway.json`, `nixpacks.toml`, `Dockerfile` fallback based on `mcr.microsoft.com/playwright/python:v1.48.0-jammy`). Python source skeleton: `src/config.py`, `src/main.py` (FastAPI app with `/health`), stub modules under `src/auth/`, `src/fetch/`, `src/parse/`, `src/enrich/`, `src/ui/`, `src/cli/`. Pydantic models for Player, Tournament, Draw, DrawEntry, Match, RankingSnapshot, WTNSnapshot. SQLite schema in `src/store/db.py` with eight tables and WAL mode. Test scaffolding: `tests/conftest.py`, `tests/unit/test_health.py`, `tests/unit/test_schema.py`. CI workflow (`.github/workflows/ci.yml`) running ruff + mypy + pytest. PR template. Self-improvement script `scripts/update_canonical_docs.py` (drift report + `--apply` for mechanical refresh). Recon-runner skeleton `scripts/recon_session.py`. Dev-data seeder `scripts/seed_dev_data.py`. `.claude/` subagent charters (recon, parser, enrich, ui), slash commands (`/sync`, `/recon`, `/update-docs`), and project settings.

**Authored canonical docs.** SPEC.md (~6,800 words across 16 sections, written by Agent-Spec). RESEARCH.md (~2,500 words across 5 axes, written by Agent-Research). AGENTS.md (multi-agent coordination charter). DATA_MODEL.md (canonical entity definitions). RECON.md (reconnaissance plan, findings TBD). API_CONTRACTS.md (hypothesized endpoints, all rows unconfirmed). RUNBOOK.md (operations + troubleshooting tree). TESTING.md (pyramid, schema-drift detection, anonymization). README.md, STATE.md, DECISIONS.md (ADR-001 Proposed, ADR-002 Accepted), QUESTIONS.md (nine open items), TODO.md.

**Key research finding.** `playtennis.usta.com` is a Clubspark deployment with a documented GraphQL endpoint at `https://prod-us-kube.clubspark.io/usta/tournaments/api/graphql`. Community gists catalogue queries like `EventList` and `TournamentData`. The same Clubspark infrastructure powers WTN, suggesting WTN data may be reachable via the same surface. This collapses what looked like two scraping problems (tournament data + WTN data) into one and shifts the leading extraction strategy from HTML scraping to GraphQL queries. Validation lands in Phase 0 recon.

**Decisions.** ADR-001 (Extraction Strategy) filed as Proposed, gated on recon. ADR-002 (raw SQLite over SQLAlchemy ORM for v1) filed as Accepted.

**Did not do.** Live recon — credentials and explicit user authorization required. RECON.md is a plan, not findings; API_CONTRACTS.md is hypothesized, not verified. Tracked as Q-001.

— Orchestrator (Claude Code, bootstrap session)
