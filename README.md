# USTA Portal

A personal tournament intelligence dashboard for a USTA tennis player. Authenticated sync from `playtennis.usta.com`, persisted locally, augmented with computed intelligence (opponent scouting, WTN tracking, head-to-head, strength-of-draw). The dashboard becomes the canonical interface — you detach from the USTA site after sync.

> **Status:** bootstrap. The skeleton is in place; recon (Phase 0) is the next active workstream and gates Phase 1 application code. See `STATE.md` for what's live right now.

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
| [AGENTS.md](AGENTS.md) | Multi-agent coordination charter. |
| [DECISIONS.md](DECISIONS.md) | Architecture decisions (ADRs). |
| [QUESTIONS.md](QUESTIONS.md) | Open questions for the user. |
| [TODO.md](TODO.md) | Prioritized backlog. |
| [RECON.md](RECON.md) | USTA site reconnaissance plan and findings. |
| [RESEARCH.md](RESEARCH.md) | Prior-art research notes. |
| [DATA_MODEL.md](DATA_MODEL.md) | Canonical entity definitions. |
| [API_CONTRACTS.md](API_CONTRACTS.md) | Discovered USTA endpoints. |
| [RUNBOOK.md](RUNBOOK.md) | Operations and troubleshooting. |
| [TESTING.md](TESTING.md) | Test strategy. |
| [CHANGELOG.md](CHANGELOG.md) | Append-only history. |

## Quick start (local development)

```bash
git clone <repo>
cd USTAPortal
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # then fill in USTA_USERNAME and USTA_PASSWORD
python -m src.cli.main init-db
uvicorn src.main:app --reload
# open http://localhost:8000
```

The web app boots even with no data — sync is wired up after Phase 1 lands.

## Deploy on Railway

The repo is configured for Railway out of the box.

1. Create a new Railway project from this repo.
2. Add a persistent volume mounted at `/data` (Railway dashboard → Volumes → New). Without this, every redeploy nukes the SQLite DB and raw cache.
3. Set environment variables in the Railway dashboard from `.env.example`.
4. Deploy. Railway uses Nixpacks by default; the included `nixpacks.toml` brings Python 3.11 and Playwright Chromium system deps. If the Nixpacks build fails on Playwright, switch the builder to Docker — the included `Dockerfile` (based on `mcr.microsoft.com/playwright/python`) is a known-good fallback.
5. Healthcheck path is `/health`, configured in `railway.json`.

## Posture

This is a personal-use tool for a single user's own tournament participation. Request volume is bounded by what a normal user clicking around the USTA site would generate — by default one request every two seconds, single concurrent connection. Do not crank these up. The point is intelligence, not bulk extraction.
