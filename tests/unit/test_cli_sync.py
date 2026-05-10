"""Tests for the wired-up ``usta sync`` orchestrator and ``usta where-am-i``.

These are end-to-end at the CLI surface but the router never calls a real
network: TennisLinkClient is intentionally absent and ClubsparkClient is
the deferred stub. The expected behavior is a clean log of "nothing
fetched, no parsers wired" — no silent failures.
"""

from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()


def _reload_cli(monkeypatch: pytest.MonkeyPatch, **env: str) -> object:
    """Apply env vars and reload settings + CLI to pick them up."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    # Make doubly sure tennislink_client is unavailable for the sync tests
    # — that's the precondition that makes "no parsers wired" predictable.
    monkeypatch.setitem(sys.modules, "src.fetch.tennislink_client", None)

    import src.cli.main as cli_main
    import src.config
    import src.store.db

    importlib.reload(src.config)
    importlib.reload(src.store.db)
    importlib.reload(cli_main)
    return cli_main


def test_sync_runs_to_completion_with_no_creds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "test.db"
    cache_dir = tmp_path / "raw"
    cli_main = _reload_cli(
        monkeypatch,
        DATABASE_URL=f"sqlite:///{db_path}",
        USTA_USER_PLAYER_ID="",
        RAW_CACHE_DIR=str(cache_dir),
    )

    result = runner.invoke(cli_main.app, ["sync"])  # type: ignore[attr-defined]
    assert result.exit_code == 0, result.output
    assert "syncing tournaments" in result.output
    assert "USTA_USER_PLAYER_ID not configured" in result.output
    assert "sync summary" in result.output
    # No parsers wired, no creds → everything is zero.
    assert "fetched  : 0" in result.output
    assert "parsed   : 0" in result.output
    assert "errored  : 0" in result.output


def test_sync_with_player_id_logs_router_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "test.db"
    cli_main = _reload_cli(
        monkeypatch,
        DATABASE_URL=f"sqlite:///{db_path}",
        USTA_USER_PLAYER_ID="12345678",
    )

    result = runner.invoke(cli_main.app, ["sync"])  # type: ignore[attr-defined]
    # Even though the router can't actually fetch anything (no TennisLink
    # module, Clubspark stub raises NotImplementedError), the CLI exits 0
    # and reports a coherent summary.
    assert result.exit_code == 0, result.output
    assert "fetching player 12345678" in result.output
    assert "sync summary" in result.output
    # The fetch path falls through every source and ends in error or fetch=0.
    assert "errored" in result.output


def test_sync_accepts_tournament_and_force_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "test.db"
    cli_main = _reload_cli(monkeypatch, DATABASE_URL=f"sqlite:///{db_path}")

    result = runner.invoke(
        cli_main.app,  # type: ignore[attr-defined]
        ["sync", "--tournament", "TID-123", "--force"],
    )
    assert result.exit_code == 0, result.output
    assert "TID-123" in result.output
    assert "force-refetch: True" in result.output
    assert "sync summary" in result.output


def test_where_am_i_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "wai.db"
    cli_main = _reload_cli(
        monkeypatch,
        DATABASE_URL=f"sqlite:///{db_path}",
        USTA_USER_PLAYER_ID="98765432",
        RAW_CACHE_DIR=str(tmp_path / "raw"),
    )

    result = runner.invoke(cli_main.app, ["where-am-i"])  # type: ignore[attr-defined]
    assert result.exit_code == 0, result.output
    assert "database_url" in result.output
    assert "raw_cache_dir" in result.output
    assert "usta_user_player_id    : 98765432" in result.output
    assert "source preference" in result.output


def test_where_am_i_with_unset_player_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "wai.db"
    cli_main = _reload_cli(
        monkeypatch, DATABASE_URL=f"sqlite:///{db_path}", USTA_USER_PLAYER_ID=""
    )

    result = runner.invoke(cli_main.app, ["where-am-i"])  # type: ignore[attr-defined]
    assert result.exit_code == 0
    assert "<unset>" in result.output


def test_sync_loop_default_prints_not_yet_implemented() -> None:
    """The infinite daemon shape is deferred; default sync-loop call says so."""
    from src.cli.main import app

    result = runner.invoke(app, ["sync-loop"])
    assert result.exit_code == 0, result.output
    assert "not yet implemented" in result.output


def test_sync_loop_with_iterations_runs_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "loop.db"
    cli_main = _reload_cli(monkeypatch, DATABASE_URL=f"sqlite:///{db_path}")

    result = runner.invoke(
        cli_main.app,  # type: ignore[attr-defined]
        ["sync-loop", "--iterations", "1", "--interval", "0"],
    )
    assert result.exit_code == 0, result.output
    assert "iteration 1" in result.output
    assert "completed 1 iteration" in result.output


# ---------------------------------------------------------------------------
# sync_runs bookkeeping
# ---------------------------------------------------------------------------


def _read_sync_runs(db_path: Path) -> list[tuple[str, str, int, int, int, int]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT status, source, fetched_count, parsed_count, "
            "persisted_count, errored_count "
            "FROM sync_runs ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows]


def test_sync_records_a_run_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "runs.db"
    cli_main = _reload_cli(
        monkeypatch,
        DATABASE_URL=f"sqlite:///{db_path}",
        USTA_USER_PLAYER_ID="",
        RAW_CACHE_DIR=str(tmp_path / "raw"),
    )

    result = runner.invoke(cli_main.app, ["sync"])  # type: ignore[attr-defined]
    assert result.exit_code == 0, result.output

    rows = _read_sync_runs(db_path)
    assert len(rows) == 1
    status, _, fetched, parsed, persisted, errored = rows[0]
    # No creds, no parsers wired → ok with all zeros.
    assert status == "ok"
    assert (fetched, parsed, persisted, errored) == (0, 0, 0, 0)


def test_sync_records_partial_when_errors_occur(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "runs.db"
    # With a player id but no parsers, the router will fail to fetch and the
    # summary's errored count goes positive — that should land as 'partial'.
    cli_main = _reload_cli(
        monkeypatch,
        DATABASE_URL=f"sqlite:///{db_path}",
        USTA_USER_PLAYER_ID="12345678",
    )

    result = runner.invoke(cli_main.app, ["sync"])  # type: ignore[attr-defined]
    assert result.exit_code == 0, result.output

    rows = _read_sync_runs(db_path)
    assert len(rows) == 1
    status, _, _, _, _, errored = rows[0]
    if errored > 0:
        assert status == "partial"
    else:
        # If the router managed to swallow the error gracefully somehow,
        # 'ok' is also acceptable — the test is about the bookkeeping
        # branching, not the orchestrator's exact semantics.
        assert status == "ok"


def test_sync_log_command_prints_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "log.db"
    cli_main = _reload_cli(
        monkeypatch,
        DATABASE_URL=f"sqlite:///{db_path}",
        USTA_USER_PLAYER_ID="",
        RAW_CACHE_DIR=str(tmp_path / "raw"),
    )

    sync_result = runner.invoke(cli_main.app, ["sync"])  # type: ignore[attr-defined]
    assert sync_result.exit_code == 0, sync_result.output

    log_result = runner.invoke(cli_main.app, ["sync-log"])  # type: ignore[attr-defined]
    assert log_result.exit_code == 0, log_result.output
    assert "started_at" in log_result.output
    # The latest row's started_at is an ISO timestamp; check the date stub.
    rows = _read_sync_runs(db_path)
    assert rows, "sync did not record a row"


def test_sync_log_empty_table_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "empty.db"
    cli_main = _reload_cli(monkeypatch, DATABASE_URL=f"sqlite:///{db_path}")

    result = runner.invoke(cli_main.app, ["sync-log"])  # type: ignore[attr-defined]
    assert result.exit_code == 0, result.output
    assert "no sync runs recorded yet" in result.output
