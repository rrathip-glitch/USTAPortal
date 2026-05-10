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

    player_parser = _try_import_parser("src.parse.players")
    if player_parser is None or not hasattr(player_parser, "parse_player_tournaments"):
        typer.echo(
            "  tennislink parser not yet available; "
            "fetched body cached, skipping walk."
        )
        return

    try:
        tournament_ids: list[str] = list(
            player_parser.parse_player_tournaments(body)
        )
        summary["parsed"] += 1
    except Exception as exc:
        typer.echo(f"  player parse failed: {exc!r}")
        summary["errored"] += 1
        return

    typer.echo(f"  discovered {len(tournament_ids)} tournaments for player {player_id}")
    for tid in tournament_ids:
        await _sync_single_tournament(router, conn, tid, summary)


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

    tournament_parser = _try_import_parser("src.parse.tournaments")
    if tournament_parser is None or not hasattr(tournament_parser, "parse_tournament"):
        typer.echo("  tennislink parser for tournament not available; skipping parse.")
        return

    try:
        parsed = tournament_parser.parse_tournament(body)
        summary["parsed"] += 1
    except Exception as exc:
        typer.echo(f"  tournament {tournament_id} parse failed: {exc!r}")
        summary["errored"] += 1
        return

    # Persistence wiring goes here once Tournament/Draw repos are tied in.
    # For now the parsed object is logged and counted but not written —
    # the orchestrator agent does not own repository writes (Docs-Clean /
    # parser agents do). Bumping a placeholder keeps the summary honest
    # without inventing data.
    draw_ids = list(getattr(parsed, "draw_ids", []) or [])
    if not draw_ids:
        return

    for draw_id in draw_ids:
        await _sync_single_draw(router, conn, draw_id, summary)


async def _sync_single_draw(
    router: FetchRouter,
    conn: sqlite3.Connection,
    draw_id: str,
    summary: SyncSummary,
) -> None:
    try:
        await router.get_draw(draw_id)
        summary["fetched"] += 1
    except Exception as exc:
        typer.echo(f"  draw {draw_id} fetch failed: {exc!r}")
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

        typer.echo = _tee  # type: ignore[assignment]
        return self

    def __exit__(self, *exc: object) -> bool:
        typer.echo = self._original  # type: ignore[assignment]
        return False


if __name__ == "__main__":
    app()
