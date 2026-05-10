"""Fixture anonymizer for raw USTA responses.

Per TESTING.md and Q-009 (resolved), every fixture committed to the repo must
first pass through this module. The anonymizer replaces:

- USTA IDs (GUIDs and numeric IDs alike) → deterministic synthetic substitutes.
  GUIDs use ``uuid.uuid5`` against a fixed namespace so the mapping is stable
  across runs. Numeric IDs are hashed to a 9-digit synthetic.
- Name-shaped fields (key matches /name|first|last|displayname/i) →
  ``Player_<short_hash>``. The primary user is anonymized too (Q-009).
- Email and phone fields → empty string.
- Date/time fields, scores, ratings → preserved (not PII).

The anonymizer is recursive over dicts and lists. Free-form strings are
scanned by :func:`anonymize_string` for embedded GUIDs / numeric IDs and the
mapping is applied to those substrings as well.

The mapping (real_id → fake_id) is appended to per-fixture and, when a
``mapping_path`` is supplied, persisted to JSON alongside the fixture so a
later debugger can correlate.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# Fixed namespace for uuid5 — chosen once and never changed; rotating it would
# invalidate every committed fixture's mapping.
_NAMESPACE = uuid.UUID("d3b07384-d9a8-5f6e-9b3a-6c9f2e7c8d10")

# Field-name patterns. Matching is case-insensitive on the *key*, not the value.
_NAME_KEY_RE = re.compile(r"name|first|last|displayname", re.IGNORECASE)
_EMAIL_KEY_RE = re.compile(r"email", re.IGNORECASE)
_PHONE_KEY_RE = re.compile(r"phone|mobile|tel", re.IGNORECASE)
_ID_KEY_RE = re.compile(r"(^|_)id$|guid|uuid|playerid|userid|tournamentid|drawid|matchid", re.IGNORECASE)

# Substring patterns for scrubbing inside free-form strings.
_GUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
# Numeric ID heuristic: 6+ consecutive digits (USTA IDs are typically 7-9
# digits; phone numbers and dates are excluded by length / surrounding context
# in practice). This is intentionally conservative.
_NUMERIC_ID_RE = re.compile(r"\b\d{6,}\b")


def _is_guid(value: str) -> bool:
    return bool(_GUID_RE.fullmatch(value))


def _is_numeric_id(value: str) -> bool:
    # Plain digit string of >=6 chars. Excludes dates like "2026-05-10" or
    # decimal scores because those contain non-digit characters.
    return value.isdigit() and len(value) >= 6


def _fake_guid(real: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, real))


def _fake_numeric(real: str) -> str:
    digest = hashlib.sha256(real.encode("utf-8")).hexdigest()
    # Map first 12 hex chars → integer → 9-digit zero-padded.
    n = int(digest[:12], 16) % 1_000_000_000
    return f"{n:09d}"


def _fake_name(real: str) -> str:
    digest = hashlib.sha256(real.encode("utf-8")).hexdigest()[:8]
    return f"Player_{digest}"


def _map_id(real: str, mapping: dict[str, str]) -> str:
    if real in mapping:
        return mapping[real]
    if _is_guid(real):
        fake = _fake_guid(real)
    elif _is_numeric_id(real):
        fake = _fake_numeric(real)
    else:
        return real
    mapping[real] = fake
    return fake


def anonymize_string(s: str, mapping: dict[str, str]) -> str:
    """Apply the id mapping to GUID-shaped or numeric-id substrings in ``s``.

    Mutates ``mapping`` in place when new ids are encountered.
    """
    if not s:
        return s

    def _sub_guid(match: re.Match[str]) -> str:
        return _map_id(match.group(0), mapping)

    def _sub_numeric(match: re.Match[str]) -> str:
        return _map_id(match.group(0), mapping)

    out = _GUID_RE.sub(_sub_guid, s)
    out = _NUMERIC_ID_RE.sub(_sub_numeric, out)
    return out


def _anonymize_value(key: str | None, value: Any, mapping: dict[str, str]) -> Any:
    # Dict / list — recurse.
    if isinstance(value, dict):
        return _anonymize_dict(value, mapping)
    if isinstance(value, list):
        return [_anonymize_value(key, item, mapping) for item in value]

    # Non-string scalars: recurse into nothing, but numeric ids stored as ints
    # under id-shaped keys still need mapping.
    if isinstance(value, bool):
        # bool is a subclass of int; preserve as-is.
        return value
    if isinstance(value, int) and key is not None and _ID_KEY_RE.search(key):
        as_str = str(value)
        if _is_numeric_id(as_str):
            return int(_map_id(as_str, mapping))
        return value
    if not isinstance(value, str):
        return value

    # Strings.
    if key is not None:
        if _EMAIL_KEY_RE.search(key) or _PHONE_KEY_RE.search(key):
            return ""
        if _ID_KEY_RE.search(key):
            # Whole field is an id — map directly even if shape is non-standard.
            if _is_guid(value) or _is_numeric_id(value):
                return _map_id(value, mapping)
            # Fall through to substring scan.
        if _NAME_KEY_RE.search(key):
            if not value:
                return value
            return _fake_name(value)

    # Free-form string: scrub embedded ids.
    return anonymize_string(value, mapping)


def _anonymize_dict(d: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    return {k: _anonymize_value(k, v, mapping) for k, v in d.items()}


def anonymize(
    raw: dict[str, Any],
    *,
    mapping_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Anonymize ``raw`` and return ``(anonymized, mapping)``.

    If ``mapping_path`` is provided, an existing mapping at that path is loaded
    first (so repeated runs accumulate consistent ids), and the merged mapping
    is written back after anonymization.
    """
    mapping: dict[str, str] = {}
    if mapping_path is not None and mapping_path.exists():
        loaded = json.loads(mapping_path.read_text())
        if isinstance(loaded, dict):
            mapping.update({str(k): str(v) for k, v in loaded.items()})

    out = _anonymize_dict(raw, mapping)

    if mapping_path is not None:
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        mapping_path.write_text(json.dumps(mapping, indent=2, sort_keys=True))

    return out, mapping


__all__: Iterable[str] = ("anonymize", "anonymize_string")
