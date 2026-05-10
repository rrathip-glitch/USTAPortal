"""Typer CLI entry point.

Usage:
    usta init-db                                   # create schema in $DATABASE_URL
    usta sync [--tournament <id>] [--force]        # one-shot sync
    usta sync-loop                                 # daemon mode (Railway worker)
    usta reparse                                   # walk raw cache and reparse
    usta inspect <hash_prefix>                     # dump a raw cache entry
    usta export draw <draw_id> --format json|csv   # export a draw
    usta anonymize <input.json> <output.json>      # anonymize a fixture

Stub commands (sync-loop, export, parts of sync/reparse) print their intent
and the inputs they received until the parser, repository, and orchestrator
land in their respective phases. See AGENTS.md for the per-phase rollout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from src.config import settings
from src.store.db import init_schema
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


@app.command()
def sync(
    tournament: str | None = _OPT_TOURNAMENT,
    force: bool = _OPT_FORCE,
) -> None:
    """One-shot sync. Real orchestrator wiring lands in Phase 1."""
    typer.echo("syncing tournaments...")
    if tournament:
        typer.echo(f"  scope: tournament={tournament}")
    else:
        typer.echo("  scope: all tournaments for the primary user")
    typer.echo(f"  force-refetch: {force}")

    # Try to instantiate the auth + fetch layers. If they're stubs (no
    # credentials, NotImplementedError on login), fall back to a dry-run
    # description so the CLI is usable in the meantime.
    is_stub = True
    try:
        from src.auth.session import UstaSession
        from src.fetch.client import FetchClient

        _session = UstaSession()
        _client = FetchClient()
        # The stub session reports unauthenticated and raises on login. Detect
        # by checking the docstring for the placeholder marker.
        is_stub = "Stub" in (UstaSession.__doc__ or "") or "Stub" in (
            FetchClient.__doc__ or ""
        )
    except Exception as exc:  # pragma: no cover - defensive
        typer.echo(f"  could not instantiate auth/fetch: {exc}")
        is_stub = True

    if is_stub:
        typer.echo("  auth/fetch are stubs — would fetch tournaments, draws, matches, WTN.")
        typer.echo("sync: orchestrator not yet wired (pending recon and Phase 1).")
        return

    typer.echo("sync: orchestrator wiring pending; nothing to do.")  # pragma: no cover


@app.command(name="sync-loop")
def sync_loop() -> None:
    """Run sync on an interval. Used by the Railway worker process."""
    typer.echo("sync-loop: not yet implemented")


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


if __name__ == "__main__":
    app()
