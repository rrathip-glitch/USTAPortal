# USTA Portal

A personal tournament intelligence dashboard for a USTA tennis player. Authenticated sync from USTA-operated surfaces, persisted locally, augmented with computed intelligence (opponent scouting, WTN tracking, head-to-head, strength-of-draw). The dashboard becomes the canonical interface — you detach from the USTA site after sync.

> **Status:** Phase 1.5 — Rankings pipeline live on TennisLink historical data (current Clubspark data path in flight via Bright Data Web Unlocker, verified working). See `STATE.md` for what's live right now.

## What it does (v1 target)

- Mirrors every tournament you're entered in, every draw, every match.
- For every opponent in every draw, captures the full player profile including WTN singles and doubles ratings.
- Computes pre-tournament briefings: your projected path, opponent scouting cards, strength-of-draw, head-to-head record.
- Renders it all on a fast, offline-first dashboard you control.

## What it doesn't do

- No betting, no public sharing, no ML in v1.
- No live in-match telemetry. Sync is a discrete action.
- No multi-user mode in v1 (single account, designed for one player + their parent/coach reading the same dashboard).

## Documentation

| Document | Purpose |
| --- | --- |
| [SPEC.md](SPEC.md) | The 16-section master specification. Read this first. |
| [STATE.md](STATE.md) | What's live, what's in flight, what's queued. |
| [AGENTS.md](AGENTS.md) | Multi-agent coordination charter and agent registry. |
| [DECISIONS.md](DECISIONS.md) | Architecture decisions (ADRs). ADR-001 Accepted as Strategy C; ADR-002 storage. |
| [QUESTIONS.md](QUESTIONS.md) | Open and resolved questions for the user. |
| [TODO.md](TODO.md) | Prioritized backlog by phase. |
| [RECON.md](RECON.md) | USTA site reconnaissance findings; status BLOCKED on residential egress. |
| [RESEARCH.md](RESEARCH.md) | Prior-art research notes. |
| [DATA_MODEL.md](DATA_MODEL.md) | Canonical entity definitions. |
| [API_CONTRACTS.md](API_CONTRACTS.md) | Hypothesized and confirmed USTA endpoints, with anti-bot posture. |
| [RUNBOOK.md](RUNBOOK.md) | Operations and troubleshooting trees. |
| [TESTING.md](TESTING.md) | Test strategy, schema-drift detection, anonymization, mock-data testing. |
| [CHANGELOG.md](CHANGELOG.md) | Append-only history. |

## Data sources

The project pulls from two USTA-operated surfaces, treated very differently:

- **TennisLink (`tennislink.usta.com`)** — the legacy ASP.NET WebForms surface. Anonymously reachable from every egress tested so far, including this development environment. It is the **primary live data source** for v1: tournaments the user is entered in, draws, match results, and the Janav-account profile sync all land here. Parsers and sync wiring for TennisLink are tracked as the Phase 1.5 TennisLink track in TODO.md.
- **Clubspark / `playtennis.usta.com`** — the new Clubspark-backed SPA with the documented GraphQL endpoint. **Deferred.** Cloudflare blocks every datacenter egress this project has access to (GCP sandbox, Anthropic WebFetch infrastructure, and likely Railway — see the deploy caveat below). The extraction strategy is filed as ADR-001 / Strategy C (Playwright-resident requests through a long-lived browser context), but cannot be exercised until recon runs from a residential egress. Q-011 tracks the unblock.

Posture: until residential recon completes, the live product runs on TennisLink data. The Clubspark fetch layer is scaffolded against mocked GraphQL but not validated against real captures.

## Quick start (local development)

```bash
git clone <repo>
cd USTAPortal
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # then fill in USTA_USERNAME and USTA_PASSWORD
python -m src.cli.main init-db
python scripts/seed_dev_data.py    # populate a realistic Janav-themed demo dataset
uvicorn src.main:app --reload
# open http://localhost:8000
```

`scripts/seed_dev_data.py` inserts a synthetic Janav-themed dataset (player, opponents, tournament, draw, matches, ranking and WTN snapshots) stamped with `dev-` id prefixes so it can never collide with real fetched data. The dashboard is immediately demoable from this seed, no live USTA fetch required.

## Rankings pipeline (proven 2026-05-12)

The TennisLink rankings vertical slice is live end-to-end against the captured Boys' 12 Combined fixture (list 2072448, 1,014 players). Load it into the rankings UI:

```bash
# Load the captured Boys 12 Combined fixture into the rankings UI:
python -m src.cli.main sync-rankings --list-id 2072448 \
  --from-fixture data/recon/2026-05-11-janav-browse/tennislink-2072448.html
# Then visit http://localhost:8000/rankings/u12-boys-national
```

The page renders with Janav highlighted when his row is present and a "Source: TennisLink (historical)" footnote making the era explicit (TennisLink froze Boys' 12 national rankings in early 2021). Current 2025/2026 data requires the Bright Data Web Unlocker proxy (verified end-to-end, see `STATE.md`) plus completion of the Clubspark current-rankings recon (in flight).

## Deploy on Railway

The repo is configured for Railway out of the box.

1. Create a new Railway project from this repo.
2. Add a persistent volume mounted at `/data` (Railway dashboard → Volumes → New). Without this, every redeploy nukes the SQLite DB and raw cache.
3. Set environment variables in the Railway dashboard from `.env.example`.
4. Deploy. Railway uses Nixpacks by default; the included `nixpacks.toml` brings Python 3.11 and Playwright Chromium system deps. If the Nixpacks build fails on Playwright, switch the builder to Docker — the included `Dockerfile` (based on `mcr.microsoft.com/playwright/python`) is a known-good fallback.
5. Healthcheck path is `/health`, configured in `railway.json`.

**Egress caveat.** Railway runs from datacenter IP space; we have not yet verified whether its egress is also Cloudflare-blocked on the Clubspark edge. Treat the deployment as testable today for the UI shell and the TennisLink data plane only. The Clubspark data plane on Railway is unverified and is part of the Q-011 follow-up (sub-question b).

## Posture

This is a personal-use tool for a single user's own tournament participation. Request volume is bounded by what a normal user clicking around the USTA site would generate — by default one request every two seconds, single concurrent connection. Do not crank these up. The point is intelligence, not bulk extraction.
