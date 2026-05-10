snapshot: 2026-05-10T00:00:00Z

# STATE.md — live project status

## Phase

**Phase 0 (Reconnaissance) — pending start.** Phase 1 (Core pipeline) is gated on Phase 0 producing ADR-001.

## Active workstreams

_None. The bootstrap session has just completed; no agent currently holds a claim._

## Recently completed

- **Bootstrap (this session, 2026-05-10).** Repository scaffolded: directory structure, Python source stubs, Railway deployment config (Procfile, railway.json, nixpacks.toml, Dockerfile), test scaffolding, CI workflow, `.claude/` subagent charters and slash commands, self-improvement script (`scripts/update_canonical_docs.py`), and the canonical doc set (SPEC, AGENTS, DATA_MODEL, RECON, API_CONTRACTS, RUNBOOK, TESTING, RESEARCH). Two parallel subagents authored SPEC.md (~6,800 words across 16 sections) and RESEARCH.md (~2,500 words across 5 axes). RESEARCH.md surfaced the leading hypothesis — `playtennis.usta.com` is a Clubspark deployment with a documented GraphQL endpoint, suggesting we target GraphQL rather than HTML scraping.

## Next up

1. Recon (Phase 0). Requires the user to provide live USTA credentials and explicit authorization for live network activity in a follow-up session. Spawn the `recon` subagent (charter: `.claude/agents/recon.md`).
2. ADR-001 (Extraction Strategy) — outcome of Phase 0.
3. Phase 1 implementation: auth, fetch, parse for tournament/draw/player/match, repositories, sync CLI.

## Open blockers

- **Need credentials and authorization to start recon.** Tracked in QUESTIONS.md as Q-001.
- **Need to confirm WTN exposure pathway.** Tracked as Q-003. The leading hypothesis (research-backed) is that WTN is in the same Clubspark GraphQL surface as tournament data; recon validates.

## Recent decisions awaiting closure

- ADR-001 (Extraction Strategy) — **Proposed**, gated on Phase 0 recon.
- ADR-002 (Storage layer: SQLite raw vs. SQLAlchemy ORM) — **Accepted** as raw SQLite for v1.

## Doc snapshot health

- SPEC.md: current as of bootstrap. Will need refresh after ADR-001 lands.
- RECON.md: a plan, not findings. Replace with findings once Phase 0 runs.
- API_CONTRACTS.md: all rows hypothesized. Replace with confirmed entries after recon.
- DATA_MODEL.md: aligned with Pydantic models in `src/models/`.
- DECISIONS.md: one Accepted ADR (storage), one Proposed (extraction).
- TODO.md: bootstrap items archived; Phase 0/1 items listed.
