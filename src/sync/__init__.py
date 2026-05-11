"""Sync orchestration helpers (incremental filters, etc.).

This package houses building blocks used by the sync orchestrator in
``src/cli/main.py``. The orchestrator itself is wired up elsewhere — this
package only exposes composable primitives so they can be unit-tested in
isolation.
"""
