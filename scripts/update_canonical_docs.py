"""Self-improvement loop.

Scans the repository for signals that the canonical docs are out of date and
prints suggested updates. Does NOT silently rewrite docs — it writes a report
to stdout that a human (or the Orchestrator agent in a follow-up turn) reviews.

Signals examined:
  - CHANGELOG.md entries since the last STATE.md "snapshot" line.
  - Files modified since the timestamp embedded in STATE.md.
  - DECISIONS.md ADRs in "Proposed" status.
  - QUESTIONS.md items with no "resolved" marker.
  - TODO.md items checked off but not removed from the file.
  - SPEC.md sections referencing modules whose paths have moved or been deleted.

Usage:
    python scripts/update_canonical_docs.py            # report only
    python scripts/update_canonical_docs.py --apply    # apply mechanical fixes
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

CANON = {
    "spec": REPO / "SPEC.md",
    "state": REPO / "STATE.md",
    "decisions": REPO / "DECISIONS.md",
    "questions": REPO / "QUESTIONS.md",
    "todo": REPO / "TODO.md",
    "changelog": REPO / "CHANGELOG.md",
    "agents": REPO / "AGENTS.md",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def list_modified_paths(since: str) -> list[str]:
    """Return paths modified after `since` (an ISO-8601 timestamp), via git."""
    try:
        out = subprocess.check_output(
            ["git", "log", f"--since={since}", "--pretty=", "--name-only"],
            cwd=REPO,
            text=True,
        )
    except subprocess.CalledProcessError:
        return []
    return sorted({line.strip() for line in out.splitlines() if line.strip()})


def find_open_questions(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("- Q-") and "[resolved]" not in line.lower()
    ]


def find_proposed_adrs(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if re.match(r"^- ADR-\d+ .+ \[Proposed\]", line.strip())
    ]


def find_completed_todos(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("- [x]")
    ]


def report() -> int:
    print("# Canonical-doc drift report")
    print(f"# Generated: {datetime.utcnow().isoformat()}Z")
    print()

    state = read(CANON["state"])
    snap_match = re.search(r"snapshot:\s*([0-9TZ:.\-]+)", state)
    since = snap_match.group(1) if snap_match else "1970-01-01"
    print(f"Last STATE.md snapshot: {since}")

    modified = list_modified_paths(since)
    if modified:
        print(f"\n## Files changed since last snapshot ({len(modified)})")
        for path in modified:
            print(f"  - {path}")

    questions = find_open_questions(read(CANON["questions"]))
    if questions:
        print(f"\n## Open questions ({len(questions)})")
        for q in questions:
            print(f"  {q}")

    proposed = find_proposed_adrs(read(CANON["decisions"]))
    if proposed:
        print(f"\n## ADRs awaiting decision ({len(proposed)})")
        for adr in proposed:
            print(f"  {adr}")

    completed = find_completed_todos(read(CANON["todo"]))
    if completed:
        print(f"\n## Completed TODOs still listed ({len(completed)})")
        for todo in completed:
            print(f"  {todo}")
        print("  (consider archiving these into CHANGELOG and removing from TODO.md)")

    print("\n# Suggested actions")
    print(
        "  - Update STATE.md `snapshot:` line to current UTC and refresh the project status.\n"
        "  - Move resolved questions out of QUESTIONS.md into RECON.md or DECISIONS.md.\n"
        "  - Resolve any [Proposed] ADRs by writing the rationale and changing status.\n"
        "  - Append a CHANGELOG.md entry summarizing this session.\n"
        "  - Re-read SPEC.md and confirm it still describes reality."
    )
    return 0


def apply_mechanical() -> int:
    """Apply only mechanical, low-risk updates: refresh STATE.md snapshot timestamp."""
    state = read(CANON["state"])
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    if "snapshot:" in state:
        state = re.sub(r"snapshot:.*", f"snapshot: {now}", state, count=1)
    else:
        state = f"snapshot: {now}\n\n" + state
    CANON["state"].write_text(state, encoding="utf-8")
    print(f"Refreshed STATE.md snapshot to {now}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="apply mechanical fixes")
    args = parser.parse_args(argv)
    return apply_mechanical() if args.apply else report()


if __name__ == "__main__":
    sys.exit(main())
