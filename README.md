# USTA Portal

A personal tournament intelligence dashboard for a USTA tennis player. Authenticated sync from USTA-operated surfaces, persisted locally, augmented with computed intelligence (opponent scouting, WTN tracking, head-to-head, strength-of-draw). The dashboard becomes the canonical interface — you detach from the USTA site after sync.

> **Status:** Phase 1 live on real USTA Play Tennis data. The data-plane breakthrough on 2026-05-11 unlocked anonymous, Cloudflare-free access to the AWS API Gateway at `prod-api-playtennis.usta.com` (the same API the AEM-rendered National Search frontend at `playerapp.usta.com` calls at JS-runtime). Combined with anonymous third-party feeds from CoreTennis and UTR, the portal now runs on real data end-to-end. See `STATE.md` for what's live and `RECON.md` for the breakthrough details.

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
| [DECISIONS.md](DECISIONS.md) | Architecture decisions (ADRs). ADR-006 Anonymous USTA Play Tennis API as primary data plane; ADR-007 CoreTennis + UTR as third-party feeds; ADR-001 superseded for discovery; ADR-002 storage. |
| [QUESTIONS.md](QUESTIONS.md) | Open and resolved questions for the user. |
| [TODO.md](TODO.md) | Prioritized backlog by phase. |
| [RECON.md](RECON.md) | USTA site reconnaissance findings; status REACHED — primary data plane shipped 2026-05-11. |
| [RESEARCH.md](RESEARCH.md) | Prior-art research notes. |
| [DATA_MODEL.md](DATA_MODEL.md) | Canonical entity definitions. |
| [API_CONTRACTS.md](API_CONTRACTS.md) | Hypothesized and confirmed USTA endpoints, with anti-bot posture. |
| [RUNBOOK.md](RUNBOOK.md) | Operations and troubleshooting trees. |
| [TESTING.md](TESTING.md) | Test strategy, schema-drift detection, anonymization, mock-data testing. |
| [CHANGELOG.md](CHANGELOG.md) | Append-only history. |

## Data sources

The project pulls from three anonymous surfaces, each contributing a specific slice of the data plane:

- **USTA Play Tennis API (`prod-api-playtennis.usta.com`)** — the AWS API Gateway behind the AEM-rendered National Search frontend at `playerapp.usta.com`. **Primary data plane as of 2026-05-11.** Anonymous, Cloudflare-free, reachable from any egress including this sandbox. Three endpoints answer 200 without an Authorization token: `POST /playtennis/tournaments/query`, `POST /playtennis/programs/query`, `POST /product/api-courts/v1/courts/inventory`. Required selection fields: `d` (distance, miles), `lat`, `lon`. The sync orchestrator runs a discovery walk anchored on `USTA_ANCHOR_LAT/LON/DISTANCE_MILES/PLAYER_TYPE`. Contracts in `API_CONTRACTS.md` "USTA-API endpoints (anonymous)". Filed as ADR-006.
- **CoreTennis (`coretennis.net`)** — third-party HTML aggregator. Anonymous. Provides full per-player match history at `https://www.coretennis.net/tennis-player/<slug>/<id>/{profile,ranking,results}.html`. The source of Janav's four real Boys 12s USTA Level 3 ground-truth results. Filed as ADR-007.
- **UTR Sports search API (`api.utrsports.net`)** — third-party. Anonymous. Provides per-player identity and rating via `GET /v2/search/players?query=<name>&top=<int>`. The per-id detail endpoint is auth-walled and out of scope. Partially fills the WTN gap (UTR is the rating axis the broader junior community now uses).

**Secondary / fallback surfaces:**

- **TennisLink (`tennislink.usta.com`)** — legacy ASP.NET WebForms; **frozen historical archive** (post-2018 records are absent). Kept in the router for pre-2019 lookups (historical H2H, opponent history, ranking snapshots). Filed as ADR-005.
- **Clubspark / `playtennis.usta.com`** — Cloudflare-fronted. **Deferred.** No longer load-bearing now that the API Gateway path works. Retained as a fallback for per-id detail and auth-walled queries (ADR-001 superseded by ADR-006 for the discovery + search surfaces).

Posture: the live product runs on the USTA Play Tennis API + CoreTennis + UTR. TennisLink stays for archival lookups. The Clubspark plane is not exercised in v1.

## Quick start (local development)

```bash
git clone <repo>
cd USTAPortal
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # set USTA_ANCHOR_LAT, USTA_ANCHOR_LON, USTA_DISCOVER_DISTANCE_MILES, USTA_DISCOVER_PLAYER_TYPE, USTA_DISCOVER_ENABLED
python -m src.cli.main init-db
python -m src.cli.main sync       # canonical entry point: USTA-API discovery walk + per-player enrichment
uvicorn src.main:app --reload
# open http://localhost:8000
```

`usta sync` is the canonical entry point. It runs a USTA-API discovery walk for nearby tournaments anchored on `USTA_ANCHOR_LAT/LON/DISTANCE_MILES/PLAYER_TYPE` (gated by `USTA_DISCOVER_ENABLED`) and persists results through the same repositories the UI reads from. The legacy seeder `scripts/seed_dev_data.py` still works for offline demoing but is being phased out (see STATE.md "Next up").

## Deploy on Railway

The repo is configured for Railway out of the box.

1. Create a new Railway project from this repo.
2. Add a persistent volume mounted at `/data` (Railway dashboard → Volumes → New). Without this, every redeploy nukes the SQLite DB and raw cache.
3. Set environment variables in the Railway dashboard from `.env.example`.
4. Deploy. Railway uses Nixpacks by default; the included `nixpacks.toml` brings Python 3.11 and Playwright Chromium system deps. If the Nixpacks build fails on Playwright, switch the builder to Docker — the included `Dockerfile` (based on `mcr.microsoft.com/playwright/python`) is a known-good fallback.
5. Healthcheck path is `/health`, configured in `railway.json`.

**Egress caveat.** Railway runs from datacenter IP space. The primary USTA-API data plane (`prod-api-playtennis.usta.com`) is *not* behind Cloudflare and is expected to be reachable from Railway egress — verify on first deploy. The deferred Clubspark Cloudflare-fronted plane is unverified from Railway and is not load-bearing for v1.

## Posture

This is a personal-use tool for a single user's own tournament participation. Request volume is bounded by what a normal user clicking around the USTA site would generate — by default one request every two seconds, single concurrent connection. Do not crank these up. The point is intelligence, not bulk extraction.
