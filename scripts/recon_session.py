"""Playwright recon runner skeleton.

This script is intentionally a skeleton — it is the staging ground that the
recon subagent uses, not a tool to run unattended. Running it requires:

  - USTA_USERNAME and USTA_PASSWORD set in .env
  - Explicit user authorization for live network activity in this session
  - Playwright Chromium installed (`playwright install chromium`)

What it does (when fleshed out):
  1. Launch a Chromium context, headed by default for visibility.
  2. Navigate to the USTA login page.
  3. Wait for the user to confirm successful login (or auto-fill creds).
  4. Walk a fixed list of URLs (passed via --targets), capturing every
     network request/response into data/recon/<timestamp>/network.jsonl
     and saving the rendered DOM at each stop into data/recon/<timestamp>/dom/.
  5. Print a one-page summary of distinct hosts, endpoints, and content types.

The output is what RECON.md and API_CONTRACTS.md are written from.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--targets",
        type=Path,
        help="Path to a file with one URL per line to walk during recon.",
    )
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args(argv)

    print("recon_session.py is a skeleton — implementation lands during Phase 0 recon.")
    print(f"Targets file: {args.targets}")
    print(f"Headless: {args.headless}")
    print("Refer to .claude/agents/recon.md for the recon protocol.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
