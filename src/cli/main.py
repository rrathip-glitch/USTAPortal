"""Typer CLI entry point.

Usage:
    usta init-db                                   # create schema in $DATABASE_URL
    usta sync [--tournament <id>] [--force]        # one-shot sync (multi-source)
    usta sync-loop                                 # daemon mode (Railway worker)
    usta reparse                                   # walk raw cache and reparse
    usta inspect <hash_prefix>                     # dump a raw cache entry
    usta where-am-i                                # print current config
    usta export draw <draw_id> --format json|csv   # export a draw
    usta anonymize <input.json> <output.json>      # anonymize a fixture

The ``sync`` command is wired end-to-end against the multi-source
:class:`FetchRouter` per ADR-005. Until the TennisLink parsers land it
still produces a coherent log: what we fetched, what we tried to parse,
what we persisted, what errored. No silent failures.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import sqlite3
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any

import typer
from loguru import logger as _loguru_logger

from src.config import settings
from src.fetch.router import FetchRouter, configured_source_preference
from src.store.db import db_path, init_schema
from src.store.repositories import SyncRunRepository
from tests.anonymize import anonymize as _anonymize_payload

app = typer.Typer(no_args_is_help=True, add_completion=False)
export_app = typer.Typer(no_args_is_help=True, add_completion=False, help="Export data.")
app.add_typer(export_app, name="export")

# Module-level Typer parameter singletons. Defined here (not as call-site
# defaults) to satisfy ruff B008 — function-call defaults are evaluated once
# at import time and would otherwise share state.
_OPT_TOURNAMENT = typer.Option(None, "--tournament", help="Sync only the given tournament id.")
_OPT_FORCE = typer.Option(False, "--force", help="Bypass the raw cache and re-fetch from USTA.")
_ARG_INPUT = typer.Argument(..., exists=True, readable=True, help="Raw fixture JSON.")
_ARG_OUTPUT = typer.Argument(..., help="Anonymized fixture destination.")
_OPT_MAPPING = typer.Option(
    None,
    "--mapping",
    help="Where to read/write the id mapping (defaults to <output>.mapping.json).",
)
_ARG_DRAW_ID = typer.Argument(..., help="USTA draw id.")
_OPT_FORMAT = typer.Option("json", "--format", help="Output format: json or csv.")
_OPT_LOOP_INTERVAL = typer.Option(
    3600.0, "--interval", help="Seconds between sync runs in loop mode."
)
_OPT_LOOP_ITERATIONS = typer.Option(
    0,
    "--iterations",
    help=(
        "Cap on loop iterations. 0 (default) means the daemon shape is not "
        "yet implemented — pass a positive integer (e.g. --iterations 1) "
        "to run sync once on a loop interval."
    ),
)
_OPT_SYNC_LOG_LIMIT = typer.Option(
    10,
    "--limit",
    help="How many recent sync runs to display (default 10).",
)
_OPT_RANK_AGE = typer.Option(
    12,
    "--age",
    help="Age category (numeric): 10, 12, 14, 16, 18.",
)
_OPT_RANK_GENDER = typer.Option(
    "B",
    "--gender",
    help="Gender flag: B (boys), G (girls), X (mixed).",
)
_OPT_RANK_SCOPE = typer.Option(
    "national",
    "--scope",
    help="Scope: national, sectional, or district.",
)
_OPT_RANK_SECTION = typer.Option(
    None,
    "--section",
    help="Section name (required when --scope=sectional).",
)
_OPT_RANK_FORCE = typer.Option(
    False,
    "--force",
    help="Bypass the raw cache and re-fetch from Clubspark.",
)
_OPT_RANK_LIST_ID = typer.Option(
    None,
    "--list-id",
    help=(
        "TennisLink rankinglistid (e.g. 2072448). When set, the command "
        "fetches the printable list directly via TennisLinkClient. "
        "Bypasses --age/--gender/--scope (which target the deferred "
        "Clubspark flow)."
    ),
)
_OPT_RANK_FROM_FIXTURE = typer.Option(
    None,
    "--from-fixture",
    help=(
        "Skip the network and parse a local HTML file instead. Useful for "
        "unit tests and local demos. Pass with --list-id so the persisted "
        "list keeps the TennisLink id in its slug for traceability."
    ),
)


# ---------------------------------------------------------------------------
# sync — multi-source orchestrator
# ---------------------------------------------------------------------------


@app.command()
def sync(
    tournament: str | None = _OPT_TOURNAMENT,
    force: bool = _OPT_FORCE,
) -> None:
    """One-shot sync. Walks the user's player → tournaments → draws → matches.

    Records a row in ``sync_runs`` (status ``running`` → ``ok``/``partial``/
    ``failed``) so the ``/sync`` UI page and ``usta sync-log`` can surface
    operational state without tailing files.
    """
    capture = _LogCapture()

    # Open a dedicated DB connection for the run's bookkeeping. We deliberately
    # open this BEFORE the orchestrator's own connection so the ``running`` row
    # is durable even if the orchestrator's setup fails.
    bookkeeping_conn: sqlite3.Connection | None = None
    run_id: int | None = None
    try:
        bookkeeping_conn = _connect_and_init_db()
        run_repo = SyncRunRepository(bookkeeping_conn)
        run_id = run_repo.start(source=_sync_source_label())
    except Exception as exc:  # pragma: no cover - defensive
        # If we can't even record the run, log it and proceed without
        # bookkeeping rather than blocking the actual sync.
        typer.echo(f"  sync_runs: failed to record run start ({exc!r}); continuing without log")
        bookkeeping_conn = None
        run_id = None

    capture.echo("syncing tournaments...")
    if tournament:
        capture.echo(f"  scope: tournament={tournament}")
    else:
        capture.echo("  scope: all tournaments for the primary user")
    capture.echo(f"  force-refetch: {force}")
    capture.echo(f"  source preference: {','.join(configured_source_preference())}")

    error_summary: str | None = None
    summary: SyncSummary
    sink_id: int | None = capture.attach_loguru()
    try:
        with capture.tee_typer_echo():
            try:
                summary = asyncio.run(_run_sync(tournament=tournament, force=force))
                _print_sync_summary(summary)
            except Exception as exc:
                error_summary = f"{type(exc).__name__}: {exc}"
                capture.echo(f"sync: aborted by exception: {error_summary}")
                summary = SyncSummary()
                summary["errored"] = 1
                _record_finish(
                    bookkeeping_conn,
                    run_id,
                    status="failed",
                    summary=summary,
                    error_summary=error_summary,
                    log_text=capture.text(),
                )
                raise
    finally:
        if sink_id is not None:
            capture.detach_loguru(sink_id)

    status = "ok" if summary["errored"] == 0 else "partial"
    _record_finish(
        bookkeeping_conn,
        run_id,
        status=status,
        summary=summary,
        error_summary=None,
        log_text=capture.text(),
    )

    if bookkeeping_conn is not None:
        with _IgnoreErrors():
            bookkeeping_conn.close()


@app.command(name="sync-log")
def sync_log(limit: int = _OPT_SYNC_LOG_LIMIT) -> None:
    """Print the last N sync runs in a tabular format."""
    if limit <= 0:
        typer.echo("sync-log: --limit must be a positive integer.")
        raise typer.Exit(code=2)
    conn = _connect_and_init_db()
    try:
        runs = SyncRunRepository(conn).recent(limit=limit)
    finally:
        with _IgnoreErrors():
            conn.close()
    if not runs:
        typer.echo("sync-log: no sync runs recorded yet.")
        return
    typer.echo(
        f"{'started_at':<32}{'source':<12}{'status':<10}"
        f"{'fetched':>9}{'parsed':>9}{'persisted':>11}{'errored':>9}"
    )
    typer.echo("-" * 92)
    for run in runs:
        typer.echo(
            f"{run.started_at.isoformat():<32}"
            f"{run.source:<12}"
            f"{run.status:<10}"
            f"{run.fetched_count:>9}"
            f"{run.parsed_count:>9}"
            f"{run.persisted_count:>11}"
            f"{run.errored_count:>9}"
        )


@app.command(name="sync-rankings")
def sync_rankings(
    age: int = _OPT_RANK_AGE,
    gender: str = _OPT_RANK_GENDER,
    scope: str = _OPT_RANK_SCOPE,
    section: str | None = _OPT_RANK_SECTION,
    force: bool = _OPT_RANK_FORCE,
    list_id: str | None = _OPT_RANK_LIST_ID,
    from_fixture: Path | None = _OPT_RANK_FROM_FIXTURE,
) -> None:
    """Fetch and persist a ranking list.

    Two data planes are wired:

    1. **TennisLink** (active): when ``--list-id`` is supplied (and/or
       ``--from-fixture`` is set), the command fetches the printable
       ``RankingListsPrint.aspx?id=<LIST_ID>`` view, parses it via
       :mod:`src.parse.tennislink_rankings_list`, and upserts both the
       :class:`RankingList` header and every :class:`RankingListEntry`
       row into SQLite. This is the Rankings-First v1 path. The
       upstream data is historical (TennisLink froze the B12 plane in
       early 2021) but the pipeline is real.

    2. **Clubspark** (deferred): when neither ``--list-id`` nor
       ``--from-fixture`` is supplied, the command falls through to the
       residential-proxy flow described in ADR-001. Without
       ``RESIDENTIAL_PROXY_PROVIDER`` configured it prints a friendly
       message and exits ``0`` so the absence of credentials remains a
       soft state.
    """
    typer.echo(
        f"sync-rankings: age={age} gender={gender} scope={scope} "
        f"section={section or '-'} force={force} "
        f"list_id={list_id or '-'} from_fixture={from_fixture or '-'}"
    )

    # TennisLink path — either by list-id (fetched) or fixture (offline).
    if list_id or from_fixture:
        _run_tennislink_ranking_capture(
            list_id=list_id,
            from_fixture=from_fixture,
        )
        return

    if not settings.residential_proxy_provider:
        typer.echo(
            "  No residential-proxy provider configured. "
            "Set RESIDENTIAL_PROXY_PROVIDER + credentials in .env, or pass "
            "--list-id <id> (e.g. 2072448) to capture a TennisLink list. "
            "See data/reference/known_urls.md for the data-plane decision."
        )
        return

    # Record the sync_runs row so the UI surfaces this attempt.
    bookkeeping_conn: sqlite3.Connection | None = None
    run_id: int | None = None
    try:
        bookkeeping_conn = _connect_and_init_db()
        run_repo = SyncRunRepository(bookkeeping_conn)
        run_id = run_repo.start(source="clubspark")
    except Exception as exc:  # pragma: no cover - defensive
        typer.echo(f"  sync_runs: failed to record run start ({exc!r}); continuing")
        bookkeeping_conn = None
        run_id = None

    summary = SyncSummary()
    error_summary: str | None = None
    status = "ok"
    log_lines: list[str] = []

    try:
        log_lines.append(f"provider: {settings.residential_proxy_provider}")
        typer.echo(f"  provider: {settings.residential_proxy_provider}")

        asyncio.run(
            _run_sync_rankings(
                age=age,
                gender=gender,
                scope=scope,
                section=section,
                summary=summary,
            )
        )
    except NotImplementedError as exc:
        # Expected today — fetch_rankings + parser are stubs.
        error_summary = f"NotImplementedError: {exc}"
        typer.echo(f"  pending implementation: {exc}")
        summary["errored"] += 1
        status = "partial"
    except Exception as exc:
        error_summary = f"{type(exc).__name__}: {exc}"
        typer.echo(f"  sync-rankings aborted: {error_summary}")
        summary["errored"] += 1
        status = "failed"

    _print_sync_summary(summary)
    log_text = "\n".join(log_lines)

    _record_finish(
        bookkeeping_conn,
        run_id,
        status=status,
        summary=summary,
        error_summary=error_summary,
        log_text=log_text,
    )
    if bookkeeping_conn is not None:
        with _IgnoreErrors():
            bookkeeping_conn.close()


def _run_tennislink_ranking_capture(
    *,
    list_id: str | None,
    from_fixture: Path | None,
) -> None:
    """Run the TennisLink-backed ranking-capture flow.

    Either ``list_id`` or ``from_fixture`` (or both) must be set; the
    caller (``sync_rankings``) already gates on that. When both are set,
    the fixture wins — the on-disk HTML is parsed and ``list_id`` is
    used only as the slug-id seed so re-loads upsert cleanly.

    Records a ``sync_runs`` row tagged ``source="tennislink"`` so the
    /sync UI page surfaces this attempt. Prints a one-line summary on
    success: ``Persisted <N> entries from list <id> (<age_category>)``.
    """
    from src.models.player import Player
    from src.parse.tennislink_rankings_list import (
        ParseError,
        parse_tennislink_rankings_list,
    )
    from src.store.repositories import PlayerRepository, RankingListRepository

    # 1. Open DB + start sync_runs row.
    bookkeeping_conn: sqlite3.Connection | None = None
    run_id: int | None = None
    try:
        bookkeeping_conn = _connect_and_init_db()
        run_repo = SyncRunRepository(bookkeeping_conn)
        run_id = run_repo.start(source="tennislink")
    except Exception as exc:  # pragma: no cover - defensive
        typer.echo(f"  sync_runs: failed to record run start ({exc!r}); continuing")
        bookkeeping_conn = None
        run_id = None

    summary = SyncSummary()
    error_summary: str | None = None
    status = "ok"
    log_lines: list[str] = []

    try:
        # 2. Fetch (or load fixture).
        if from_fixture is not None:
            if not from_fixture.exists():
                raise FileNotFoundError(
                    f"--from-fixture path does not exist: {from_fixture}"
                )
            typer.echo(f"  loading fixture: {from_fixture}")
            log_lines.append(f"fixture: {from_fixture}")
            html = from_fixture.read_text(encoding="utf-8")
        else:
            if list_id is None:  # pragma: no cover - guarded by caller
                raise ValueError("list_id must be set when no fixture is supplied")
            typer.echo(f"  fetching TennisLink list {list_id}...")
            log_lines.append(f"fetch: list_id={list_id}")
            html = asyncio.run(_fetch_tennislink_ranking_list(list_id))
        summary["fetched"] += 1

        # 3. Parse.
        header, entries = parse_tennislink_rankings_list(html, list_id=list_id)
        summary["parsed"] += 1
        log_lines.append(
            f"parsed: id={header.id} age_category={header.age_category} "
            f"entries={len(entries)}"
        )

        # 4. Persist. Players have to land first so the FK on
        # ranking_list_entries.player_usta_id is satisfied.
        if bookkeeping_conn is None:
            raise RuntimeError("bookkeeping connection is not available; cannot persist")
        player_repo = PlayerRepository(bookkeeping_conn)
        ranking_repo = RankingListRepository(bookkeeping_conn)

        ranking_repo.upsert_list(header)
        summary["persisted"] += 1

        for entry in entries:
            existing = player_repo.get(entry.player_usta_id)
            if existing is None:
                first_name, last_name = _split_last_first(entry.player_name_raw)
                player_repo.upsert(
                    Player(
                        usta_id=entry.player_usta_id,
                        full_name=entry.player_name_raw,
                        first_name=first_name,
                        last_name=last_name,
                        section=entry.section,
                    )
                )
            ranking_repo.upsert_entry(entry)
            summary["persisted"] += 1

        bookkeeping_conn.commit()

        typer.echo(
            f"  Persisted {len(entries)} entries from list "
            f"{list_id or header.id} ({header.age_category}, "
            f"as_of={header.as_of.isoformat()})"
        )

    except ParseError as exc:
        error_summary = f"ParseError: {exc}"
        typer.echo(f"  sync-rankings parse failed: {error_summary}")
        summary["errored"] += 1
        status = "failed"
    except FileNotFoundError as exc:
        error_summary = f"FileNotFoundError: {exc}"
        typer.echo(f"  sync-rankings fixture missing: {error_summary}")
        summary["errored"] += 1
        status = "failed"
    except Exception as exc:
        error_summary = f"{type(exc).__name__}: {exc}"
        typer.echo(f"  sync-rankings aborted: {error_summary}")
        summary["errored"] += 1
        status = "failed"

    _print_sync_summary(summary)
    log_text = "\n".join(log_lines)
    _record_finish(
        bookkeeping_conn,
        run_id,
        status=status,
        summary=summary,
        error_summary=error_summary,
        log_text=log_text,
    )
    if bookkeeping_conn is not None:
        with _IgnoreErrors():
            bookkeeping_conn.close()


async def _fetch_tennislink_ranking_list(list_id: str) -> str:
    """Fetch a TennisLink print-view ranking list. Returns response body."""
    from src.fetch.tennislink_client import TennisLinkClient

    async with TennisLinkClient() as client:
        return await client.get_ranking_list(list_id)


def _split_last_first(name_raw: str) -> tuple[str | None, str | None]:
    """Split a ``"Last, First"`` name into (first, last). Best effort.

    Returns ``(None, None)`` when the input is empty or doesn't carry a
    comma — for those cases the caller keeps the full name in
    ``Player.full_name`` and leaves first/last unset.
    """
    if not name_raw or "," not in name_raw:
        return None, None
    last, first = name_raw.split(",", 1)
    return first.strip() or None, last.strip() or None


async def _run_sync_rankings(
    *,
    age: int,
    gender: str,
    scope: str,
    section: str | None,
    summary: SyncSummary,
) -> None:
    """Run the (deferred) Clubspark sync-rankings flow.

    Today: instantiate the residential-proxy backend, then call the
    Clubspark client's deferred ``fetch_rankings`` method, which raises
    :class:`NotImplementedError`. The caller (``sync_rankings``) catches
    that and records a ``partial`` run in ``sync_runs``.

    When the orchestrator wires real fetching + parsing, the chain is:

    1. ``backend = get_residential_proxy(...)``
    2. ``body = await client.fetch_rankings(age, gender, scope, section)``
    3. ``ranking_list, entries = parse_clubspark_rankings(body)``
    4. ``repo.upsert_list(ranking_list)`` + iterate ``upsert_entry(entry)``
    """
    from src.fetch.clubspark_client import ClubsparkClient
    from src.fetch.residential_proxy import (
        ResidentialProxyConfigError,
        get_residential_proxy,
    )
    from src.parse.clubspark_rankings import parse_clubspark_rankings
    from src.store.repositories import RankingListRepository

    # Instantiate the residential-proxy backend so any config error is
    # surfaced *before* the deferred-fetch call. This is the wiring the
    # orchestrator can hold the line on while credentials land.
    try:
        _backend = get_residential_proxy()
    except ResidentialProxyConfigError as exc:
        # Translate to a clear NotImplementedError so the outer handler
        # records this as a "partial" run rather than a "failed" one.
        raise NotImplementedError(
            f"Residential-proxy backend not ready: {exc}"
        ) from exc

    # When the chain below lands for real, this is where ``conn`` and
    # ``RankingListRepository(conn)`` come in. Keeping the reference
    # in scope so ruff doesn't flag the unused import for future devs.
    _ = RankingListRepository

    client = ClubsparkClient()
    try:
        body = await client.fetch_rankings(
            age=age,
            gender=gender,
            scope=scope,
            section=section,
        )
        summary["fetched"] += 1
    finally:
        await client.close()

    # Equally a NotImplementedError today; the chain above will raise
    # first under the current stub.
    _list, _entries = parse_clubspark_rankings(body)
    summary["parsed"] += 1


@app.command(name="sync-loop")
def sync_loop(
    interval: float = _OPT_LOOP_INTERVAL,
    iterations: int = _OPT_LOOP_ITERATIONS,
) -> None:
    """Run sync on an interval. Used by the Railway worker process.

    The infinite-daemon shape is not yet implemented; without
    ``--iterations N`` (N >= 1) this prints intent and exits cleanly.
    """
    if iterations <= 0:
        typer.echo("sync-loop: not yet implemented — pass --iterations N to run finitely.")
        return
    typer.echo(f"sync-loop: interval={interval}s, iterations={iterations}")
    asyncio.run(_run_sync_loop(interval=interval, iterations=iterations))


# ---------------------------------------------------------------------------
# where-am-i — debug config dump
# ---------------------------------------------------------------------------


@app.command(name="where-am-i")
def where_am_i() -> None:
    """Print the current effective configuration (DB, cache, source order, ids)."""
    try:
        db = str(db_path())
    except ValueError as exc:
        db = f"<unsupported: {exc}>"

    player_id = settings.usta_user_player_id or "<unset>"
    prefs = configured_source_preference()

    typer.echo("usta where-am-i:")
    typer.echo(f"  database_url           : {settings.database_url}")
    typer.echo(f"  resolved db path       : {db}")
    typer.echo(f"  raw_cache_dir          : {settings.raw_cache_dir}")
    typer.echo(f"  usta_user_player_id    : {player_id}")
    typer.echo(f"  source preference      : {','.join(prefs)}")
    typer.echo(f"  request_interval_secs  : {settings.request_interval_seconds}")
    typer.echo(f"  log_level              : {settings.log_level}")
    typer.echo(f"  environment            : {settings.environment}")


# ---------------------------------------------------------------------------
# init-db / inspect / reparse / export / anonymize (unchanged-ish)
# ---------------------------------------------------------------------------


@app.command(name="init-db")
def init_db() -> None:
    """Create the SQLite schema."""
    init_schema()
    typer.echo(f"Schema initialized at {settings.database_url}")


@app.command()
def reparse() -> None:
    """Walk the raw cache and reparse every entry into the database.

    Today this prints a summary of what's in the cache; once parsers and
    repositories are wired this will reparse and upsert.
    """
    cache_dir: Path = settings.raw_cache_dir
    if not cache_dir.exists():
        typer.echo(f"reparse: raw cache directory does not exist: {cache_dir}")
        typer.echo("found 0 raw entries; reparse not yet wired")
        return

    counts: dict[str, int] = {}
    total = 0
    for path in cache_dir.rglob("*"):
        if path.is_file():
            bucket = path.parent.relative_to(cache_dir).as_posix() or "."
            counts[bucket] = counts.get(bucket, 0) + 1
            total += 1

    for bucket, count in sorted(counts.items()):
        typer.echo(f"  {bucket}: {count}")
    typer.echo(f"found {total} raw entries; reparse not yet wired")


@app.command()
def inspect(hash_prefix: str) -> None:
    """Pretty-print a raw cache entry whose filename hash starts with ``hash_prefix``.

    Exits non-zero (1) when the prefix matches no entries or is ambiguous,
    so shell pipelines can detect misses.
    """
    cache_dir: Path = settings.raw_cache_dir
    if not cache_dir.exists():
        typer.echo(f"inspect: raw cache directory does not exist: {cache_dir}")
        raise typer.Exit(code=1)

    matches = [p for p in cache_dir.rglob("*") if p.is_file() and p.name.startswith(hash_prefix)]
    if not matches:
        typer.echo(f"inspect: no raw entry found with prefix {hash_prefix!r}")
        raise typer.Exit(code=1)
    if len(matches) > 1:
        typer.echo(f"inspect: prefix {hash_prefix!r} is ambiguous ({len(matches)} matches):")
        for m in matches:
            typer.echo(f"  {m}")
        raise typer.Exit(code=1)

    target = matches[0]
    try:
        data: Any = json.loads(target.read_text())
        typer.echo(json.dumps(data, indent=2, sort_keys=True))
    except json.JSONDecodeError:
        typer.echo(target.read_text())


@export_app.command("draw")
def export_draw(
    draw_id: str = _ARG_DRAW_ID,
    fmt: str = _OPT_FORMAT,
) -> None:
    """Export a draw. Not yet wired."""
    if fmt not in {"json", "csv"}:
        typer.echo(f"export draw: unknown format {fmt!r}; use 'json' or 'csv'.")
        raise typer.Exit(code=2)
    typer.echo(f"export draw: not yet wired (draw_id={draw_id}, format={fmt})")


@app.command()
def anonymize(
    input_path: Path = _ARG_INPUT,
    output_path: Path = _ARG_OUTPUT,
    mapping_path: Path | None = _OPT_MAPPING,
) -> None:
    """Anonymize a raw USTA response so it can be committed as a fixture."""
    raw = json.loads(input_path.read_text())
    if not isinstance(raw, dict):
        typer.echo("anonymize: input must be a JSON object at the top level.")
        raise typer.Exit(code=2)

    map_path = (
        mapping_path
        if mapping_path is not None
        else output_path.with_suffix(output_path.suffix + ".mapping.json")
    )
    out, mapping = _anonymize_payload(raw, mapping_path=map_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(out, indent=2, sort_keys=True))
    typer.echo(f"anonymize: wrote {output_path} ({len(mapping)} ids mapped)")
    typer.echo(f"anonymize: mapping at {map_path}")


# ---------------------------------------------------------------------------
# Async orchestration internals
# ---------------------------------------------------------------------------


# Summary keys that the sync run accumulates as it walks. Stable for tests.
class SyncSummary(dict[str, int]):
    """Mutable counter dict with a fixed set of keys used by ``usta sync``."""

    def __init__(self) -> None:
        super().__init__(
            {
                "fetched": 0,
                "parsed": 0,
                "persisted": 0,
                "errored": 0,
            }
        )


def _try_import_parser(name: str) -> ModuleType | None:
    """Lazily import a parser module. Returns ``None`` if not yet available."""
    try:
        return import_module(name)
    except ImportError:
        return None


async def _run_sync(*, tournament: str | None, force: bool) -> SyncSummary:
    summary = SyncSummary()

    # 1. Ensure the database is initialized so writes can land.
    try:
        conn = _connect_and_init_db()
    except Exception as exc:  # pragma: no cover - defensive
        typer.echo(f"  db: failed to open ({exc}); aborting sync.")
        summary["errored"] += 1
        return summary

    # 2. Stand up the router. (Lazy-imports source clients on first use.)
    router = FetchRouter()

    try:
        if tournament:
            await _sync_single_tournament(router, conn, tournament, summary)
        else:
            await _sync_for_primary_user(router, conn, summary)
    finally:
        with _IgnoreErrors():
            await router.close()
        with _IgnoreErrors():
            conn.commit()
            conn.close()

    return summary


async def _sync_for_primary_user(
    router: FetchRouter,
    conn: sqlite3.Connection,
    summary: SyncSummary,
) -> None:
    player_id = settings.usta_user_player_id
    if not player_id:
        typer.echo(
            "  USTA_USER_PLAYER_ID not configured — sync will skip "
            "player-tournament discovery."
        )
        return

    typer.echo(f"  fetching player {player_id}...")
    try:
        body = await router.get_player(player_id)
        summary["fetched"] += 1
    except Exception as exc:
        typer.echo(f"  player fetch failed: {exc!r}")
        summary["errored"] += 1
        return

    # The TennisLink player-history page does not directly carry the
    # primary user's tournament list as a structured array (it is rendered
    # by VIEWSTATE postbacks). For v1, persist the player profile shell
    # we can extract and skip the tournament-walk discovery from a single
    # MID page; orchestrators that want a wider walk should pass
    # ``--tournament <id>`` directly. See parser TODOs.
    try:
        from src.parse.tennislink_players import parse_player_profile

        player_obj = parse_player_profile(body)
        summary["parsed"] += 1
    except Exception as exc:
        typer.echo(f"  player parse failed: {exc!r}")
        summary["errored"] += 1
        return

    try:
        from src.store.repositories import PlayerRepository

        PlayerRepository(conn).upsert(player_obj)
        summary["persisted"] += 1
    except Exception as exc:
        typer.echo(f"  player persist failed: {exc!r}")
        summary["errored"] += 1


async def _sync_single_tournament(
    router: FetchRouter,
    conn: sqlite3.Connection,
    tournament_id: str,
    summary: SyncSummary,
) -> None:
    typer.echo(f"  fetching tournament {tournament_id}...")
    try:
        body = await router.get_tournament(tournament_id)
        summary["fetched"] += 1
    except Exception as exc:
        typer.echo(f"  tournament {tournament_id} fetch failed: {exc!r}")
        summary["errored"] += 1
        return

    try:
        from src.parse.tennislink_tournaments import parse_tournament_detail

        tournament, draws = parse_tournament_detail(body)
        # The parser cannot know the URL's `T=` value — backfill the
        # caller-provided id when the page didn't expose its own.
        if not tournament.usta_id:
            tournament = tournament.model_copy(update={"usta_id": tournament_id})
        for d in draws:
            if not d.tournament_id:
                d.tournament_id = tournament.usta_id
        summary["parsed"] += 1
    except Exception as exc:
        typer.echo(f"  tournament {tournament_id} parse failed: {exc!r}")
        summary["errored"] += 1
        return

    try:
        from src.store.repositories import DrawRepository, TournamentRepository

        TournamentRepository(conn).upsert(tournament)
        draw_repo = DrawRepository(conn)
        for d in draws:
            draw_repo.upsert(d)
        summary["persisted"] += 1 + len(draws)
    except Exception as exc:
        typer.echo(f"  tournament {tournament_id} persist failed: {exc!r}")
        summary["errored"] += 1
        return

    # Walk each draw's bracket so matches and entries actually land. We
    # only walk if the draw carries a usable composite id (T:E shape).
    for d in draws:
        if ":" in d.usta_id:
            await _sync_single_draw(router, conn, d.usta_id, summary)


async def _sync_single_draw(
    router: FetchRouter,
    conn: sqlite3.Connection,
    draw_id: str,
    summary: SyncSummary,
) -> None:
    try:
        body = await router.get_draw(draw_id)
        summary["fetched"] += 1
    except Exception as exc:
        typer.echo(f"  draw {draw_id} fetch failed: {exc!r}")
        summary["errored"] += 1
        return

    try:
        from src.parse.tennislink_draws import parse_draw

        draw, entries, matches = parse_draw(body)
        summary["parsed"] += 1
        # The draw's parsed tournament_id is read from the page's form
        # action, which on a refetched bracket may not match the caller's
        # composite id. When the caller passed a "T=<t>:E=<e>" id, prefer
        # the caller's tournament id as the FK target — that's the row
        # the orchestrator just persisted upstream.
        if ":" in draw_id:
            t_part = draw_id.split(":", 1)[0]
            t_val = t_part.split("=", 1)[1] if "=" in t_part else t_part
            if t_val:
                draw.tournament_id = t_val
                # Keep the composite usta_id consistent so subsequent
                # lookups of the same draw resolve. We carry the parsed
                # event id (after the colon) into the new composite.
                e_part = (
                    draw_id.split(":", 1)[1]
                    if ":" in draw_id
                    else draw.usta_id.split(":", 1)[-1]
                )
                e_val = e_part.split("=", 1)[1] if "=" in e_part else e_part
                draw.usta_id = f"{t_val}:{e_val}" if e_val else f"{t_val}"
                for e in entries:
                    e.draw_id = draw.usta_id
                for m in matches:
                    m.draw_id = draw.usta_id
    except Exception as exc:
        typer.echo(f"  draw {draw_id} parse failed: {exc!r}")
        summary["errored"] += 1
        return

    try:
        from src.store.repositories import (
            DrawEntryRepository,
            DrawRepository,
            MatchRepository,
            PlayerRepository,
        )

        # The draw row was already upserted by the tournament step; doing
        # it again is idempotent (INSERT OR REPLACE).
        DrawRepository(conn).upsert(draw)

        # Entries reference players via FK; ensure the players exist
        # first (with whatever name we extracted from the bracket).
        player_repo = PlayerRepository(conn)
        # The parser stuffed Player objects into the entries flow via
        # _extract_players; we don't have direct access to that map here,
        # so the entries' player_id values point at MIDs that may not yet
        # exist in players table. Best-effort: create stub Player rows
        # with name "(unknown)" so the FK is satisfied.
        from src.models.player import Player
        from src.parse.tennislink_draws import parse_draw as _parse_draw  # noqa: F401

        for e in entries:
            existing = player_repo.get(e.player_id)
            if existing is None:
                player_repo.upsert(
                    Player(usta_id=e.player_id, full_name="(unknown)")
                )

        entry_repo = DrawEntryRepository(conn)
        for e in entries:
            entry_repo.upsert(e)

        match_repo = MatchRepository(conn)
        # Matches synthesized from the draw page don't have USTA-assigned
        # IDs (TennisLink doesn't expose them on the bracket view); skip
        # them rather than fabricate a key. Matches with usta_id set get
        # persisted.
        persisted_matches = 0
        for m in matches:
            if m.usta_id is None:
                continue
            match_repo.upsert(m)
            persisted_matches += 1

        summary["persisted"] += 1 + len(entries) + persisted_matches
    except Exception as exc:
        typer.echo(f"  draw {draw_id} persist failed: {exc!r}")
        summary["errored"] += 1


def _connect_and_init_db() -> sqlite3.Connection:
    """Connect to the SQLite DB and run ``init_schema`` against it."""
    # Use the local helper to ensure schema is fresh; ``init_schema`` handles
    # the IF NOT EXISTS clauses, so re-running is safe.
    from src.store.db import connect

    conn = connect()
    init_schema(conn)
    return conn


class _IgnoreErrors:
    """Tiny context manager that swallows exceptions during teardown."""

    def __enter__(self) -> _IgnoreErrors:
        return self

    def __exit__(self, *exc: object) -> bool:
        return True


def _print_sync_summary(summary: SyncSummary) -> None:
    typer.echo("sync summary:")
    typer.echo(f"  fetched  : {summary['fetched']}")
    typer.echo(f"  parsed   : {summary['parsed']}")
    typer.echo(f"  persisted: {summary['persisted']}")
    typer.echo(f"  errored  : {summary['errored']}")


async def _run_sync_loop(*, interval: float, iterations: int) -> None:
    count = 0
    while True:
        count += 1
        typer.echo(f"sync-loop: iteration {count}")
        summary = await _run_sync(tournament=None, force=False)
        _print_sync_summary(summary)
        if count >= iterations:
            typer.echo(f"sync-loop: completed {iterations} iteration(s); exiting.")
            return
        await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# Sync run bookkeeping helpers
# ---------------------------------------------------------------------------


def _sync_source_label() -> str:
    """Pick a source label for the sync_runs row.

    The orchestrator dispatches across the configured source preference;
    when there's more than one it's logged as ``multi``. With a single
    source we record that source's name verbatim.
    """
    prefs = configured_source_preference()
    if len(prefs) == 1:
        return prefs[0]
    return "multi"


def _record_finish(
    conn: sqlite3.Connection | None,
    run_id: int | None,
    *,
    status: str,
    summary: SyncSummary,
    error_summary: str | None,
    log_text: str,
) -> None:
    """Best-effort terminal UPDATE on the sync_runs row.

    If either the connection or the run id is missing (because bookkeeping
    failed at start time), this is a no-op — the actual sync flow has
    already run and we shouldn't crash the CLI on a logging failure.
    """
    if conn is None or run_id is None:
        return
    repo = SyncRunRepository(conn)
    try:
        repo.finish(
            run_id=run_id,
            status=status,
            fetched=summary["fetched"],
            parsed=summary["parsed"],
            persisted=summary["persisted"],
            errored=summary["errored"],
            error_summary=error_summary,
            log_text=log_text,
        )
    except Exception as exc:  # pragma: no cover - defensive
        typer.echo(f"  sync_runs: failed to record run finish ({exc!r})")


class _LogCapture:
    """Capture both ``typer.echo`` and loguru output into one buffer.

    Used by the ``sync`` command to persist a multi-line log into the
    ``sync_runs.log_text`` column. The buffer is plain text — no rich
    formatting — so the UI can render it inside a ``<pre>`` panel without
    sanitization concerns beyond standard Jinja autoescaping.
    """

    def __init__(self) -> None:
        self._buffer = io.StringIO()

    # --- typer.echo tee ----------------------------------------------------

    def echo(self, message: str = "") -> None:
        """Write to stdout via ``typer.echo`` AND append to the buffer."""
        typer.echo(message)
        self._buffer.write(message)
        self._buffer.write("\n")

    def tee_typer_echo(self) -> _TyperEchoTee:
        """Context manager that wraps ``typer.echo`` so every call lands in the buffer."""
        return _TyperEchoTee(self._buffer)

    # --- loguru sink -------------------------------------------------------

    def attach_loguru(self) -> int | None:
        """Add a loguru sink that mirrors records into the buffer.

        Returns the sink id so the caller can detach it on teardown.
        Returns ``None`` if loguru rejected the sink (e.g. the logger has
        already been removed in a teardown sequence).
        """
        try:
            return _loguru_logger.add(
                self._buffer,
                format="{time:YYYY-MM-DDTHH:mm:ss} | {level:<8} | {name}:{function}:{line} - {message}",
                level=settings.log_level,
                enqueue=False,
            )
        except Exception:  # pragma: no cover - defensive
            return None

    def detach_loguru(self, sink_id: int) -> None:
        with contextlib.suppress(ValueError, KeyError):
            _loguru_logger.remove(sink_id)

    # --- accessor ----------------------------------------------------------

    def text(self) -> str:
        return self._buffer.getvalue()


class _TyperEchoTee:
    """Context manager that monkey-patches ``typer.echo`` to also write to a buffer."""

    def __init__(self, buffer: io.StringIO) -> None:
        self._buffer = buffer
        self._original = typer.echo

    def __enter__(self) -> _TyperEchoTee:
        original = self._original
        buffer = self._buffer

        def _tee(message: object = "", *args: Any, **kwargs: Any) -> None:
            original(message, *args, **kwargs)
            buffer.write(str(message))
            buffer.write("\n")

        typer.echo = _tee
        return self

    def __exit__(self, *exc: object) -> None:
        typer.echo = self._original


if __name__ == "__main__":
    app()
