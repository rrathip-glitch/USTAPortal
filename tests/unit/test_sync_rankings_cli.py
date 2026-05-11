"""End-to-end CLI tests for ``usta sync-rankings`` against the fixture path.

These exercise the entire vertical slice: ``--from-fixture`` skips the
network, the parser ingests the captured HTML, the repositories upsert
header + entries + minted Player rows, and the ``sync_runs`` row records
the operational state.
"""

from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "recon"
    / "2026-05-11-janav-browse"
    / "tennislink-2072448.html"
)


def _reload_cli(monkeypatch: pytest.MonkeyPatch, **env: str) -> object:
    """Apply env vars and reload settings + CLI to pick them up."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # The TennisLink-path doesn't actually call out to the network in
    # --from-fixture mode, but defensively unload the client so a stray
    # import path in this test can't surprise us.
    monkeypatch.setitem(sys.modules, "src.fetch.tennislink_client", None)

    import src.cli.main as cli_main
    import src.config
    import src.store.db

    importlib.reload(src.config)
    importlib.reload(src.store.db)
    importlib.reload(cli_main)
    return cli_main


def test_sync_rankings_from_fixture_persists_full_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loading the recon fixture lands all 1,014 entries + a SyncRun row."""
    db_path = tmp_path / "rank.db"
    cli_main = _reload_cli(
        monkeypatch,
        DATABASE_URL=f"sqlite:///{db_path}",
        RAW_CACHE_DIR=str(tmp_path / "raw"),
    )

    result = runner.invoke(
        cli_main.app,  # type: ignore[attr-defined]
        [
            "sync-rankings",
            "--list-id",
            "2072448",
            "--from-fixture",
            str(FIXTURE_PATH),
        ],
    )
    assert result.exit_code == 0, result.output
    # One-line "Persisted N entries" summary appears on success.
    assert "Persisted 1014 entries from list 2072448" in result.output
    # The summary block carries the parsed/persisted counts.
    assert "fetched  : 1" in result.output
    assert "parsed   : 1" in result.output
    assert "persisted: 1015" in result.output  # 1 header + 1014 entries.
    assert "errored  : 0" in result.output

    # DB-level verification: ranking_lists and ranking_list_entries are
    # populated, and a sync_runs row is recorded.
    conn = sqlite3.connect(db_path)
    try:
        list_rows = conn.execute(
            "SELECT id, age_category, gender, scope, total_players, source "
            "FROM ranking_lists"
        ).fetchall()
        assert len(list_rows) == 1
        list_id, age_category, gender, scope, total, source = list_rows[0]
        assert list_id == "2072448"
        assert age_category == "Boys 12s"
        assert gender == "M"
        assert scope == "national"
        assert total == 1014
        assert source == "tennislink"

        (entry_count,) = conn.execute(
            "SELECT COUNT(*) FROM ranking_list_entries WHERE list_id = ?",
            (list_id,),
        ).fetchone()
        assert entry_count == 1014

        # Top entry is Quan Rudy per known_urls.md.
        top_name = conn.execute(
            "SELECT player_name_raw FROM ranking_list_entries "
            "WHERE list_id = ? AND position = 1",
            (list_id,),
        ).fetchone()[0]
        assert top_name == "Quan, Rudy"

        # Player rows minted by the CLI: at least one for every entry.
        (player_count,) = conn.execute("SELECT COUNT(*) FROM players").fetchone()
        assert player_count == 1014

        # sync_runs row exists, source=tennislink, status=ok.
        run_row = conn.execute(
            "SELECT source, status, fetched_count, parsed_count, persisted_count "
            "FROM sync_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert run_row[0] == "tennislink"
        assert run_row[1] == "ok"
        assert run_row[2] == 1  # fetched (the fixture load counts)
        assert run_row[3] == 1  # parsed
        assert run_row[4] == 1015  # persisted (header + entries)
    finally:
        conn.close()


def test_sync_rankings_clubspark_path_still_friendly_without_creds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without --list-id and without proxy creds, the command exits 0.

    We patch ``settings.residential_proxy_provider`` directly because the
    Pydantic Literal field rejects empty strings, so we cannot null it
    via the env var. The reload step is unnecessary here — we override
    the live settings object the CLI consults.
    """
    db_path = tmp_path / "rank.db"
    cli_main = _reload_cli(
        monkeypatch,
        DATABASE_URL=f"sqlite:///{db_path}",
    )

    from src import config as config_module

    monkeypatch.setattr(
        config_module.settings, "residential_proxy_provider", None
    )

    result = runner.invoke(
        cli_main.app,  # type: ignore[attr-defined]
        ["sync-rankings"],
    )
    assert result.exit_code == 0, result.output
    assert "No residential-proxy provider configured" in result.output
    # The friendly message now also points at the --list-id alternative.
    assert "--list-id" in result.output


def test_sync_rankings_missing_fixture_records_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing fixture path records a failed sync_runs row, exits 0."""
    db_path = tmp_path / "rank.db"
    cli_main = _reload_cli(
        monkeypatch,
        DATABASE_URL=f"sqlite:///{db_path}",
    )

    bogus = tmp_path / "does-not-exist.html"
    result = runner.invoke(
        cli_main.app,  # type: ignore[attr-defined]
        [
            "sync-rankings",
            "--list-id",
            "2072448",
            "--from-fixture",
            str(bogus),
        ],
    )
    # The CLI swallows the error, surfaces it in the summary, and exits 0
    # so operators see the friendly status rather than a stack trace.
    assert result.exit_code == 0, result.output
    assert "fixture missing" in result.output or "FileNotFoundError" in result.output

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status, errored_count FROM sync_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[0] == "failed"
        assert row[1] == 1
    finally:
        conn.close()
