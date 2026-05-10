"""Typer CLI entry point.

Usage:
    usta sync                # one-shot full sync
    usta sync-loop           # daemon mode (used by Railway worker dyno)
    usta init-db             # create schema in $DATABASE_URL
    usta inspect <hash>      # dump a raw cache entry by hash
"""

from __future__ import annotations

import typer

from src.config import settings
from src.store.db import init_schema

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def sync() -> None:
    """One-shot sync. Pending Phase 1 implementation."""
    typer.echo("sync: not yet implemented (pending recon and Phase 1).")


@app.command(name="sync-loop")
def sync_loop() -> None:
    """Run sync on an interval. Used by the Railway worker process."""
    typer.echo("sync-loop: not yet implemented.")


@app.command(name="init-db")
def init_db() -> None:
    """Create the SQLite schema."""
    init_schema()
    typer.echo(f"Schema initialized at {settings.database_url}")


@app.command()
def inspect(_hash: str) -> None:
    """Print a raw cache entry by hash."""
    typer.echo("inspect: not yet implemented.")


if __name__ == "__main__":
    app()
