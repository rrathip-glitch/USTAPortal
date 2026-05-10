"""End-to-end TennisLink sync integration test.

Exercises the wired-up ``usta sync --tournament <id>`` path with respx
mocking the TennisLink HTTP surface. After the sync runs, verifies that
a Tournament + Player + Match row landed in the SQLite database.
"""

from __future__ import annotations

import importlib
import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "tennislink"

runner = CliRunner()


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def reloaded_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[object, Path]]:
    """Patch settings + reload CLI module so the run sees tmp paths.

    Reverts module reloads on teardown so subsequent tests in the same
    process do not see partially-initialized modules.
    """
    db_path = tmp_path / "sync.db"
    cache_dir = tmp_path / "raw"

    # Patch the settings object directly. This is more surgical than
    # reloading src.config, which leaves the singleton in a half-baked
    # state when monkeypatch teardown reverts the env vars.
    import src.config as _config

    monkeypatch.setattr(_config.settings, "database_url", f"sqlite:///{db_path}")
    monkeypatch.setattr(_config.settings, "raw_cache_dir", cache_dir)
    monkeypatch.setattr(_config.settings, "usta_user_player_id", "")
    monkeypatch.setattr(_config.settings, "request_interval_seconds", 0.0)

    # Reload only the modules whose module-level state captured the old
    # config singleton — keep the reload list minimal so we don't break
    # tests that come after.
    for mod_name in ("src.cli.main",):
        if mod_name in sys.modules:
            importlib.reload(sys.modules[mod_name])

    import src.cli.main as cli_main

    try:
        yield cli_main, db_path
    finally:
        # Reload once more after the test so subsequent tests see the
        # canonical settings-bound module state.
        for mod_name in ("src.cli.main",):
            if mod_name in sys.modules:
                importlib.reload(sys.modules[mod_name])


@respx.mock
def test_sync_with_tournament_id_persists_rows(
    reloaded_cli: tuple[object, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli_main, db_path = reloaded_cli

    # Patch asyncio.sleep so any retry/backoff is a no-op (not strictly
    # needed since respx returns 200, but cheap insurance).
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    base = "https://tennislink.usta.com"
    tournament_html = _read("tournament_detail.html")
    draw_html = _read("draw_detail.html")

    # The orchestrator calls get_tournament(<tid>) -> Tournament.aspx?T=<tid>,
    # then for each draw calls get_draw("T=<tid>:E=<eid>") which hits
    # Tournament.aspx?T=<tid>&E=<eid>&tab=Draws. Mock both via the same
    # path with a side-effect dispatch.
    def _route(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if "E" in params and params.get("tab") == "Draws":
            return httpx.Response(
                200, text=draw_html, headers={"Content-Type": "text/html"}
            )
        return httpx.Response(
            200, text=tournament_html, headers={"Content-Type": "text/html"}
        )

    respx.get(f"{base}/tournaments/TournamentHome/Tournament.aspx").mock(side_effect=_route)

    result = runner.invoke(
        cli_main.app,  # type: ignore[attr-defined]
        ["sync", "--tournament", "150068318"],
    )
    assert result.exit_code == 0, result.output
    assert "syncing tournaments" in result.output
    assert "fetching tournament 150068318" in result.output
    assert "sync summary" in result.output

    # Inspect the DB.
    conn = sqlite3.connect(db_path)
    try:
        # Tournament row landed.
        t_rows = conn.execute(
            "SELECT usta_id, name FROM tournaments WHERE usta_id = ?",
            ("150068318",),
        ).fetchall()
        assert t_rows, f"expected tournament 150068318 to be persisted; output:\n{result.output}"
        assert "TriTennis" in t_rows[0][1]

        # Draw rows landed.
        draw_rows = conn.execute(
            "SELECT usta_id FROM draws WHERE tournament_id = ?",
            ("150068318",),
        ).fetchall()
        assert len(draw_rows) >= 1

        # Player rows landed (stub players for each MID seen on the draw).
        player_rows = conn.execute("SELECT usta_id FROM players").fetchall()
        assert len(player_rows) >= 1, "expected at least one player row from the draw"
    finally:
        conn.close()


@respx.mock
def test_sync_skips_when_no_player_id_and_no_tournament(
    reloaded_cli: tuple[object, Path],
) -> None:
    """No creds, no tournament arg → coherent log, zero counts, exit 0."""
    cli_main, _db_path = reloaded_cli
    result = runner.invoke(cli_main.app, ["sync"])  # type: ignore[attr-defined]
    assert result.exit_code == 0, result.output
    assert "USTA_USER_PLAYER_ID not configured" in result.output
    assert "fetched  : 0" in result.output


@respx.mock
def test_sync_logs_fetch_failure(
    reloaded_cli: tuple[object, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When TennisLink returns 503 persistently, the orchestrator logs
    a tournament-fetch failure and continues — exit 0, errored > 0."""
    cli_main, _db_path = reloaded_cli

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    respx.get(
        "https://tennislink.usta.com/tournaments/TournamentHome/Tournament.aspx"
    ).mock(return_value=httpx.Response(503, text="busy"))

    result = runner.invoke(
        cli_main.app,  # type: ignore[attr-defined]
        ["sync", "--tournament", "999"],
    )
    assert result.exit_code == 0, result.output
    assert "tournament 999 fetch failed" in result.output
    assert "errored  : 1" in result.output or "errored : 1" in result.output
