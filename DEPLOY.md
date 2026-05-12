# DEPLOY.md — Railway deployment

How this project deploys to Railway. **Read this first** before touching
build config or pushing changes you expect to be live.

---

## TL;DR for future agents

- **Branch:** Railway auto-deploys from `claude/parallel-agent-scraper-3wz0r`.
  Push to that branch triggers a build + deploy.
- **Builder:** `DOCKERFILE` (per `railway.json`). The `Dockerfile` at the
  repo root is the source of truth. **`nixpacks.toml` is ignored** —
  if you see it in the tree, leave it alone or remove it; Railway will
  not look at it.
- **Health check:** `GET /health` must return `200` within 300 seconds
  of container start. `src/main.py` defines a zero-IO `/health` handler
  that responds before any heavy imports — keep it that way.
- **Persistent volume:** mount at `/data`. Without it, the SQLite database
  and raw cache are wiped on every redeploy. Configure via Railway
  dashboard → project → Volumes → New.
- **Required env vars:** see the table below. At minimum `PORT` (auto-set
  by Railway) and `DATABASE_URL`.

---

## Deploy procedure

1. Make changes on a feature branch.
2. Open a PR into `claude/parallel-agent-scraper-3wz0r` (or merge / push
   directly if you own the branch and the change is small).
3. Push triggers a Railway build automatically.
4. Watch the Railway dashboard for the build log. If the build succeeds
   and `/health` returns `200`, the deploy is live.
5. If `/health` times out, see "Common deploy failures" below.

To trigger a redeploy without code changes, push an empty commit:

```bash
git commit --allow-empty -m "chore(deploy): manual redeploy"
git push origin claude/parallel-agent-scraper-3wz0r
```

---

## Build config files (what each one does)

| File | Purpose |
| --- | --- |
| `Dockerfile` | Canonical build recipe. Python 3.11-slim base, **no Chromium / Playwright** (the current data plane uses `httpx` + `lxml` only, no browser needed — ADR-006). Image is ~150 MB. |
| `Procfile` | Process definitions. `web` runs uvicorn; `worker` runs the sync loop. Railway only uses `web` unless you provision a worker service explicitly. |
| `railway.json` | Tells Railway to build with `DOCKERFILE` and points `healthcheckPath` at `/health`. Restart policy: on-failure, max 3. |
| `nixpacks.toml` | **Ignored.** Vestigial from an earlier deploy attempt that used Nixpacks + Chromium. Kept for now to avoid churn but `railway.json` overrides the builder choice. |

---

## Environment variables

Configure these in Railway dashboard → project → Variables. Values that
ship in `.env.example` are placeholders only — never commit real
credentials there.

| Variable | Required? | Notes |
| --- | --- | --- |
| `PORT` | auto | Railway sets this; the container binds to `${PORT}`. |
| `DATABASE_URL` | yes | Default `sqlite:////data/db/usta.db`. Volume must mount at `/data` for persistence. |
| `RAW_CACHE_DIR` | yes | Default `/data/raw`. Same volume. |
| `LOG_LEVEL` | optional | `INFO` is fine. |
| `USTA_USER_PLAYER_ID` | yes | Clubspark GUID for the primary user (Janav). Drives the dashboard's "you" view. |
| `USTA_USERNAME` / `USTA_PASSWORD` | optional | Currently unused by the production data plane (anonymous AWS API Gateway). Carried forward for the auth-walled fallback path; safe to leave blank. |
| `USTA_ANCHOR_LAT` / `USTA_ANCHOR_LON` | yes | Lat/lon anchor for the tournament discovery walk (e.g., Janav's home address). Required selection field on the USTA API. |
| `USTA_ANCHOR_DISTANCE_MILES` | optional | Default 100. |
| `USTA_PLAYER_TYPE` | optional | `Junior` / `Adult` / `Wheelchair`. Default `Junior`. |
| `USTA_DISCOVER_ENABLED` | optional | `true` to enable the discovery walk in `usta sync`. Default off — set to `true` for production. |
| `RESEND_API_KEY` | optional | For sync-failure email alerts. Free tier: 3k/month. |
| `NOTIFY_FROM` / `NOTIFY_TO` | optional | Resend sender + recipient. See `src/notify/resend.py` docs. |
| `RESIDENTIAL_PROXY_PROVIDER` | optional | `brightdata` / `scrapfly` if you need the residential-proxy fallback for Cloudflare-fronted Clubspark endpoints. Default off — the anonymous USTA API is reachable without it. |
| `BRIGHT_DATA_API_KEY` / `BRIGHT_DATA_ZONE` | optional | Only if `RESIDENTIAL_PROXY_PROVIDER=brightdata`. |
| `SCRAPFLY_API_KEY` | optional | Only if `RESIDENTIAL_PROXY_PROVIDER=scrapfly`. |
| `ENVIRONMENT` | optional | `production` on Railway, `local` otherwise. Toggles a couple of sanity-check guards. |

---

## Persistent volume

Without a volume, **every redeploy wipes the SQLite DB and raw cache**.
This is the single most common cause of "my data disappeared after I
pushed a fix" surprises. Set up once:

1. Railway dashboard → project → Volumes → New
2. Mount path: `/data`
3. Size: 1 GB is plenty for a single-user dataset
4. Attach to the `web` service (and the `worker` service if you run one)

The container pre-creates `/data/raw`, `/data/db`, `/data/exports` so
first boot succeeds even without the volume — but the data will be
ephemeral until you attach one.

---

## First-boot database migration

The container does **not** auto-run `usta init-db` on start. The schema
is created lazily by the first repository call. If you want to verify
the schema is current after a deploy, run a one-off command from the
Railway dashboard:

```bash
python -m src.cli.main init-db
```

The schema migration logic in `src/store/db.py` is idempotent — it bumps
through versions v1 → v2 → v3 → … with `CREATE TABLE IF NOT EXISTS`
statements only. No data migration is destructive.

---

## Common deploy failures and fixes

These are the lessons learned from the 5 `fix(deploy):` commits in this
branch's history. If you hit any of these, the pattern is documented.

### 1. `${PORT}` not expanding → 404 / connection refused

**Symptom:** Build succeeds but `/health` times out; container logs show
uvicorn binding to literal `${PORT}` not the port Railway assigned.

**Fix:** Wrap the `startCommand` in `sh -c "..."` so the shell expands
`${PORT}`. Already done in `railway.json` and `Procfile` — don't change
it.

### 2. `/health` healthcheck races the boot → Railway kills the container

**Symptom:** Container builds, starts, but Railway's healthcheck arrives
before the FastAPI app has finished importing heavy modules. Container
is killed, restart loop, "deploy failed".

**Fix:** `src/main.py` registers `/health` **before any heavy imports**
(repository init, fetch clients, etc.). If you add new top-of-module
imports, keep them above the `app = FastAPI(...)` + `/health` decorator
chain. The healthcheck must respond with zero IO.

### 3. Chromium / Playwright pulls a 1 GB image → slow cold start

**Symptom:** Build is slow, image is huge, container is slow to boot,
healthcheck times out.

**Fix:** Don't reinstall Playwright/Chromium. The current data plane is
`httpx` + `lxml` only (ADR-006). The `Dockerfile` deliberately omits
Playwright; `nixpacks.toml` is ignored. If a future change brings
Playwright back (e.g., authenticated Clubspark recon from prod), think
hard about whether it can run on a sibling service (worker) instead of
the `web` container.

### 4. Python version mismatch → `pip install` fails

**Symptom:** Build fails with `requires-python>=3.11` error.

**Fix:** The `Dockerfile` base is `python:3.11-slim-bookworm`. Don't
downgrade. If you switch images, verify `python3 --version` matches.

### 5. `VOLUME` instruction in Dockerfile → Railway volume conflicts

**Symptom:** Volume mount doesn't persist, or the container can't write
to `/data`.

**Fix:** Don't add a `VOLUME /data` instruction to the Dockerfile.
Railway's volume system handles the mount; declaring it in Dockerfile
creates a conflicting layer. The current Dockerfile correctly omits
`VOLUME` and just `mkdir -p`'s the directories.

---

## What this branch contains beyond the main project

This branch (`claude/parallel-agent-scraper-3wz0r`) is the deploy-tuned
line. It carries forward research/intel that came in from a parallel
Claude Code session:

- `data/reference/known_urls.md` — comprehensive table of USTA URLs,
  GraphQL endpoints, identifier patterns, and verified API shapes (Bright
  Data Web Unlocker, ITF WTN GraphQL, TennisLink). Read this when
  reasoning about a new data-source path.
- `data/recon/2026-05-11-*/` — raw evidence trail for the data-plane
  decisions:
  - `bypass/` — Anthropic MITM proxy cert + Cloudflare 403 baselines.
    Proves why direct curl/Playwright against Cloudflare-fronted
    Clubspark fails from any datacenter egress.
  - `brightdata-test/` — verified Bright Data Web Unlocker works
    end-to-end against `playtennis.usta.com` and the production ITF
    GraphQL. Auth shape: `Authorization: Bearer <token>`, POST body
    uses `body` key (not `data`), zone `web_unlocker1`. Pricing:
    pay-as-you-go, $5 trial credit good for ~1,500 calls.
  - `tennislink-rankings/` + `tennislink-pull/` — TennisLink rankings
    surface is **historical-only**. B12 froze early 2021. B10 was
    never published. 906 probe files prove the freeze across every age
    group. The post-2021 cohort lives on the AWS API Gateway only.
  - `janav-browse/` — Janav-specific probes. His Clubspark GUID
    (`971BA48D-A2EA-4FB7-8305-F42EA466F6DF`) is unindexed in the ITF
    WTN dataset under every `PersonIDEnum`; his stub record
    (`JAN9450835`) has no WTN assigned.
  - `clubspark-rankings/` — exhaustive probe of Clubspark-fronted
    rankings paths. All returned 403/502. Confirms the AWS API Gateway
    is the only path; future agents can skip these dead ends.
- `.claude/agents/rankings.md` — charter for the rankings vertical-slice
  agent. Use this template when spawning a fresh rankings build.
- `.claude/agents/bypass.md` — charter for the bypass agent (only
  invoked with explicit per-session user authorization; records the
  authorization in STATE.md before dispatching).

---

## Known security issues

- **`.env.example` at line 2-3 holds real USTA credentials** committed in
  history at commit `aa88f32`. Rotating the USTA password is recommended;
  scrubbing git history with `git filter-repo` is the more thorough fix.
  See `QUESTIONS.md` SECURITY notice.
- The `BRIGHT_DATA_API_KEY` referenced in some commit messages is the
  user's trial key — already authenticated. Rotate via Bright Data
  dashboard if leaked.

---

## Open lead: current-rankings endpoint (2026-05-12)

The Clubspark recon agent located the exact endpoint that backs USTA's
modern Tournament Rankings tab:

```
POST https://prod-api-playtennis.usta.com/usta/api?type=playerRankings
Content-Type: application/json

{"selection": {"uaid": "<clubspark-guid>"}}
```

Same host as the production data plane already shipped on this branch
(ADR-006). For Janav, the UAID is his Clubspark GUID
`971BA48D-A2EA-4FB7-8305-F42EA466F6DF`. The endpoint's AEM declaration is
labelled `endpoint-security-type="public"` but in practice the API gate
is Akamai/OneTrust session-based (not Cloudflare): requests through
Bright Data Web Unlocker return 403 even after Chrome rendering. The
rendered page literally shows "Whoops, something went wrong. Please try
logging in again."

Two paths forward for a future agent:

1. **Manually capture authenticated session cookies once** (`_abck`,
   `bm_sz`, `ak_bmsc` from Akamai + an OAuth bearer from
   `auth-playtennis.usta.com` for client `clubspark-ui`), persist them
   alongside the residential-proxy config, replay against this endpoint.
   Cookie refresh cadence + lifetime unknown — needs measurement.
2. **Bright Data Scraping Browser** (sticky-session product; different
   SKU from Web Unlocker) which would establish a real Akamai session
   automatically. Higher per-call cost than Web Unlocker but skips the
   manual cookie capture.

Sibling endpoints discovered at the same host (also auth-walled):
- `/usta/api?type=playerInfo` — bio + ratings + WTN by UAID
- `/usta/api?type=playerRanklists&uaid=<uaid>` — list of available rank
  lists for player
- `/dataexchange/profile/search/public` — player search by name

Full inventory + AEM `<v-api-container endpoint=...>` declarations in
`data/reference/known_urls.md` "USTA current-rankings API surface
(2026-05-12)" section.

Side-discovery: the **`tournamentPublic(id)` GraphQL query on
`prd-usta-kube.clubspark.pro/tournamentdesk-api/graphql` works
**unauthenticated** for tournament IDs (verified against the user-supplied
draw GUID `CB005855-...`). This is potentially useful for backfilling
historical draw metadata without auth — separate workstream from
rankings.

---

## Where to look when something breaks

1. **Build failure:** Railway dashboard → Deployments → click failed
   deploy → Build log. Match against the 5 deploy fixes above.
2. **Healthcheck failure:** look for "service did not become healthy in
   300 seconds" — check the runtime log for import errors, missing
   env vars, or `/data` permission errors.
3. **Runtime error:** Railway dashboard → Deployments → live deploy →
   Logs. The app uses `loguru` with structured fields; grep for
   `ERROR` or `traceback`.
4. **Data missing after deploy:** the volume isn't mounted. See
   "Persistent volume" above.
5. **Schema-drift error in logs:** the parsers have detected a USTA
   response-shape change. Run `usta reparse` against the raw cache after
   the parser fix; see `RUNBOOK.md` "Parse errors" tree.
