"""Tests for the Typer CLI (src/cli/main.py).

Documented behavior:
- ``usta inspect <prefix>`` exits with code 1 when no entry matches (clean
  error message). The user can rely on a non-zero exit to detect misses in
  shell pipelines.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()


def test_root_help_exits_zero() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["sync", "--help"],
        ["sync-loop", "--help"],
        ["init-db", "--help"],
        ["reparse", "--help"],
        ["inspect", "--help"],
        ["anonymize", "--help"],
        ["export", "--help"],
        ["export", "draw", "--help"],
    ],
)
def test_subcommand_help_exits_zero(args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output


def _reload_settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    """Apply env vars and reload the modules that read them at import time."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import src.config
    import src.store.db
    import src.cli.main as cli_main

    importlib.reload(src.config)
    importlib.reload(src.store.db)
    importlib.reload(cli_main)


def test_init_db_creates_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test.db"
    _reload_settings(monkeypatch, DATABASE_URL=f"sqlite:///{db_path}")
    import src.cli.main as cli_main

    result = runner.invoke(cli_main.app, ["init-db"])
    assert result.exit_code == 0, result.output
    assert db_path.exists()
    assert "Schema initialized" in result.output


def test_inspect_missing_prefix_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "raw"
    cache_dir.mkdir()
    monkeypatch.setattr("src.cli.main.settings.raw_cache_dir", cache_dir)

    result = runner.invoke(app, ["inspect", "deadbeef"])
    assert result.exit_code == 1
    assert "no raw entry found" in result.output


def test_inspect_finds_and_prints_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "raw"
    (cache_dir / "tournaments").mkdir(parents=True)
    payload: dict[str, Any] = {"hello": "world", "n": 1}
    target = cache_dir / "tournaments" / "abc123def.json"
    target.write_text(json.dumps(payload))
    monkeypatch.setattr("src.cli.main.settings.raw_cache_dir", cache_dir)

    result = runner.invoke(app, ["inspect", "abc123"])
    assert result.exit_code == 0, result.output
    assert '"hello": "world"' in result.output


def test_inspect_ambiguous_prefix_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "raw"
    cache_dir.mkdir()
    (cache_dir / "abc111.json").write_text("{}")
    (cache_dir / "abc222.json").write_text("{}")
    monkeypatch.setattr("src.cli.main.settings.raw_cache_dir", cache_dir)

    result = runner.invoke(app, ["inspect", "abc"])
    assert result.exit_code == 1
    assert "ambiguous" in result.output


def test_reparse_summarizes_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "raw"
    (cache_dir / "tournaments").mkdir(parents=True)
    (cache_dir / "draws").mkdir()
    (cache_dir / "tournaments" / "a.json").write_text("{}")
    (cache_dir / "tournaments" / "b.json").write_text("{}")
    (cache_dir / "draws" / "c.json").write_text("{}")
    monkeypatch.setattr("src.cli.main.settings.raw_cache_dir", cache_dir)

    result = runner.invoke(app, ["reparse"])
    assert result.exit_code == 0, result.output
    assert "found 3 raw entries" in result.output
    assert "tournaments: 2" in result.output
    assert "draws: 1" in result.output


def test_reparse_missing_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.cli.main.settings.raw_cache_dir", tmp_path / "absent")
    result = runner.invoke(app, ["reparse"])
    assert result.exit_code == 0
    assert "found 0 raw entries" in result.output


def test_sync_prints_intent() -> None:
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0, result.output
    assert "syncing tournaments" in result.output


def test_sync_with_tournament_and_force() -> None:
    result = runner.invoke(app, ["sync", "--tournament", "TID-123", "--force"])
    assert result.exit_code == 0, result.output
    assert "TID-123" in result.output
    assert "force-refetch: True" in result.output


def test_sync_loop_placeholder() -> None:
    result = runner.invoke(app, ["sync-loop"])
    assert result.exit_code == 0, result.output
    assert "not yet implemented" in result.output


def test_export_draw_placeholder() -> None:
    result = runner.invoke(app, ["export", "draw", "DR-9", "--format", "csv"])
    assert result.exit_code == 0, result.output
    assert "DR-9" in result.output
    assert "csv" in result.output


def test_export_draw_rejects_unknown_format() -> None:
    result = runner.invoke(app, ["export", "draw", "DR-9", "--format", "xml"])
    assert result.exit_code == 2
    assert "unknown format" in result.output


def test_anonymize_round_trip(tmp_path: Path) -> None:
    src_path = tmp_path / "raw.json"
    out_path = tmp_path / "anon.json"
    payload = {
        "playerId": "11111111-2222-3333-4444-555555555555",
        "firstName": "Janav",
        "email": "x@example.com",
    }
    src_path.write_text(json.dumps(payload))

    result = runner.invoke(app, ["anonymize", str(src_path), str(out_path)])
    assert result.exit_code == 0, result.output
    assert out_path.exists()
    written = json.loads(out_path.read_text())
    assert written["playerId"] != payload["playerId"]
    assert written["firstName"].startswith("Player_")
    assert written["email"] == ""

    mapping_path = out_path.with_suffix(out_path.suffix + ".mapping.json")
    assert mapping_path.exists()
    mapping = json.loads(mapping_path.read_text())
    assert payload["playerId"] in mapping
