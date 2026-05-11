"""Health, metrics, and per-source status reporting.

Today this is a small scaffold — `health_snapshot()` returns a JSON-
serializable dict of current operational state. Future expansions
(Sentry, BetterStack, Prometheus) plug in here without changing the
route layer.
"""

from src.observability.health import (
    HealthSnapshot,
    SourceStatus,
    health_snapshot,
    probe_source,
)

__all__ = ["HealthSnapshot", "SourceStatus", "health_snapshot", "probe_source"]
