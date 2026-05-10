# RUNBOOK.md — operations and troubleshooting

Practical guidance for running, debugging, and recovering the USTA Portal. The audience is a future-you (or a future-Claude session) staring at a broken sync at 11pm the night before a tournament.

## Common operations

### One-shot sync

```bash
python -m src.cli.main sync
```

Fetches every tournament the user is entered in, every draw, every entry, every player profile (with WTN), every match. Writes raw responses into `$RAW_CACHE_DIR` and parsed entities into the SQLite DB.

### Force-resync a single tournament

```bash
python -m src.cli.main sync --tournament <usta_id> --force
```

`--force` ignores cache freshness and re-fetches.

### Re-parse from cache

```bash
python -m src.cli.main reparse
```

Walks `$RAW_CACHE_DIR/` and re-runs every parser. Use this after a parser bug fix to recover historical data without re-hitting USTA.

### Rotate credentials

Update `USTA_USERNAME` / `USTA_PASSWORD` in `.env` (locally) or in the Railway env-vars dashboard (prod). The next sync re-authenticates.

### Inspect a raw cache entry

```bash
python -m src.cli.main inspect <hash_prefix>
```

### Export a draw

```bash
python -m src.cli.main export draw <draw_id> --format json > out.json
```

## Troubleshooting tree

### If a sync hits Cloudflare 403

The first triage question: which host returned the 403?

1. Read the failing URL from the log. If it's `playtennis.usta.com`, `prod-us-kube.clubspark.io`, `prd-itf-kube.clubspark.pro`, or `worldtennisnumber.com`, the host is Cloudflare-fronted on the Clubspark edge. This block keys on outbound IP/ASN, not on TLS fingerprint or browser realism — confirmed by the 2026-05-10 live-recon attempt (see RECON.md and DECISIONS.md ADR-001). No header tweak, UA spoof, or retry will help. Recovery: switch the affected entity type to its TennisLink equivalent if one exists, or pause that workstream until residential recon resolves Q-011. Do **not** attempt evasion from this egress — it will not work and risks an account flag.
2. If the failing host is `tennislink.usta.com` or `www.usta.com`, the 403 is real and is the application's own anti-abuse response. Back off: raise `REQUEST_INTERVAL_SECONDS` to 10–20, kill any concurrency, and try one fetch manually. If the block persists for more than an hour, surface to the user before retrying.
3. If the failing host is `account.usta.com` (Auth0), the issue is not Cloudflare — go to "Auth fails" below.

### Auth fails (401, login page returned, cookie expired)

1. Verify env vars are set: `python -c "from src.config import settings; print(bool(settings.usta_username))"`.
2. Check whether USTA changed its login flow. Open `playtennis.usta.com` in a browser, log in manually, watch DevTools Network. If the request shape changed, `src/auth/session.py` needs an update — not a guess; re-run recon for the auth flow.
3. Look for a new bot challenge (captcha mid-login). If present, stop. Do not attempt evasion. Surface it as a question.
4. If 2 and 3 are clean, the credential might be stale (account locked, password reset). User intervention required.

### Bot challenge mid-fetch

1. Halt sync immediately. Continuing risks an account flag.
2. Examine the response — was it Cloudflare, Akamai, or a USTA-internal page?
3. Lower `REQUEST_INTERVAL_SECONDS` to a much higher value (10 or 20) and try one fetch manually.
4. If still challenged, switch fetch strategy: if currently httpx-only, route fetches through the Playwright context (Strategy C in ADR-001).
5. If Strategy C also fails, the path is to wait it out (24 hours) and add browser-fingerprint realism on the next attempt.

### Parse errors

1. Run the schema-drift canary (see TESTING.md): `pytest tests/integration/test_schema_drift.py`.
2. The canary names the diverged field. Update the parser. Add a new fixture capturing the new shape.
3. After parser update, run `python -m src.cli.main reparse` to recover history from raw cache.
4. Append a `## Schema drift` entry to API_CONTRACTS.md with date, query, change, and recovery action.

### WTN missing from player payload

WTN sourcing is currently **deferred to residential recon**. `worldtennisnumber.com` and the WTN GraphQL endpoint at `prd-itf-kube.clubspark.pro` are both behind the same Cloudflare IP/ASN block as the rest of the Clubspark edge. The demo dataset emitted by `scripts/seed_dev_data.py` populates synthetic WTN values so the UI is exercisable today; those values are placeholders, not real ratings. Once Q-011 resolves and a residential session captures real WTN payloads, real values replace them.

If you see WTN missing during a live sync after residential recon completes:

1. Confirm the endpoint still includes WTN at all — fetch the same player in a browser, check the rendered profile.
2. If the browser shows WTN but our parser misses it, the field name moved. Treat as schema drift.
3. If the browser doesn't show WTN either, the user may have hit a USTA gate. Check whether the user's account level grants WTN access — recon may need a refresh.

### Slow sync

1. Profile: `python -m src.cli.main sync --profile`. Look at fetch vs parse split.
2. If fetch dominates, the rate limit is binding. Decide: lower it (more polite, slower), or parallelize across distinct tournaments (faster but more concurrent connections — review ADR-001 for whether parallelism is safe under the chosen strategy).
3. If parse dominates, profile per-parser. Likely a regex over a giant HTML blob — switch to JSON parsing once recon confirms GraphQL.

### DB locked (SQLite)

1. SQLite write contention. Confirm there's only one writer process. The Railway worker dyno and a local sync run will fight.
2. If a sync process crashed and left a stale lock, kill any orphan processes and remove `*.db-journal` if present.
3. Long-term: WAL mode is on (`db.py` sets it), so readers shouldn't block writers. If they still do, look for a long-running transaction — most likely a parse loop that holds a transaction open across hundreds of inserts. Batch and commit.

### Total failure recovery

The raw cache is canonical truth. If the SQLite DB is destroyed, deleted, or corrupted:

```bash
rm -f /data/usta.db          # or wherever DATABASE_URL points
python -m src.cli.main init-db
python -m src.cli.main reparse
```

This rebuilds every entity and snapshot from `$RAW_CACHE_DIR`. The only thing lost is fetched-after-last-cache-write data, which is small.

## Monitoring

- `/health` — Railway healthcheck. Returns 200 with `{status, db, last_sync, environment, checked_at}`. The dashboard header surfaces `last_sync` so the user always knows freshness.
- Logs: loguru writes to stderr (Railway captures it). Set `LOG_LEVEL=DEBUG` to see fetch URLs, `INFO` for normal operation.

## Railway-specific notes

- The persistent volume must be mounted at `/data` (where `DATABASE_URL` and `RAW_CACHE_DIR` point). Without it, every redeploy nukes accumulated data. To attach: Railway dashboard → Volumes → New Volume → mount path `/data`.
- Playwright Chromium needs system libraries Nixpacks may or may not bundle correctly. If `playwright install chromium` fails on first deploy, switch the builder to Docker (the `Dockerfile` is already there, based on `mcr.microsoft.com/playwright/python:v1.48.0-jammy`).
- The worker dyno (`worker: python -m src.cli.main sync-loop` in `Procfile`) is opt-in. The web dyno is sufficient for manual sync.
