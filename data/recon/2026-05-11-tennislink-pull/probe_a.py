"""Objective A: harvest current national junior ranking lists from TennisLink.

Strategy: do a cheap HEAD-style classification probe on a curated set of
candidate IDs. Save full HTML only for IDs that return a populated list.

We avoid scanning huge ranges blindly. Instead, we sweep:
  - Direct neighbors of each known list (+- 50)
  - 2050000-2080000 in stride 250 (where the current B12 list 2072448 lives)
  - 1680000-1760000 in stride 250 (B14 Seeding / B16 Combined region)

For each candidate, we GET the print URL. If it returns a populated
list, we save both print and form HTML. Otherwise we move on.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib import OUT, fetch_form, fetch_print, make_httpx, quick_classify


KNOWN_IDS = [2072448, 1684711, 1752987, 1241792]


def candidate_ids() -> list[int]:
    ids: set[int] = set()
    # Tight neighborhood probes around each known list (stride 1, +/-30)
    for base in KNOWN_IDS:
        for delta in range(-30, 31, 1):
            ids.add(base + delta)
    # Coarse sweep in stride 1000 for the high range
    for x in range(2_050_000, 2_090_000, 1000):
        ids.add(x)
    # Coarse sweep stride 1000 for the 1.65M-1.78M range
    for x in range(1_650_000, 1_780_000, 1000):
        ids.add(x)
    return sorted(ids)


def main() -> None:
    out_index = OUT / "objA_index.json"
    out_log = OUT / "objA_probe_log.txt"
    findings: list[dict] = []
    log_lines: list[str] = []

    client = make_httpx()
    candidates = candidate_ids()
    print(f"probing {len(candidates)} candidate IDs...", flush=True)
    t0 = time.time()
    # Stop conditions: 30 minutes elapsed OR 25 populated lists found
    POPULATED_TARGET = 25
    TIME_BUDGET_S = 28 * 60

    n_hits = 0
    for i, list_id in enumerate(candidates):
        elapsed = time.time() - t0
        if elapsed > TIME_BUDGET_S:
            log_lines.append(f"# time budget exceeded at i={i}, stopping")
            print(f"time budget exceeded at i={i}", flush=True)
            break
        if n_hits >= POPULATED_TARGET:
            log_lines.append(f"# target hit count reached at i={i}, stopping")
            print(f"target reached at i={i}", flush=True)
            break
        try:
            status, html = fetch_print(client, list_id)
        except Exception as exc:
            log_lines.append(f"{list_id}\tERR\t{exc}")
            continue
        if status != 200:
            log_lines.append(f"{list_id}\tHTTP {status}")
            continue
        clf = quick_classify(html)
        if not clf["has_list"]:
            log_lines.append(f"{list_id}\tEMPTY\tnoinfo={clf['is_no_info']}")
            continue
        # Hit! Save both print and form HTML
        n_hits += 1
        (OUT / f"tennislink-{list_id}.html").write_text(html, encoding="utf-8")
        try:
            _, form_html = fetch_form(client, list_id)
            (OUT / f"tennislink-{list_id}-form.html").write_text(form_html, encoding="utf-8")
        except Exception as exc:
            log_lines.append(f"{list_id}\tFORM_ERR\t{exc}")
        finding = {
            "list_id": list_id,
            "title": clf["title"],
            "n_rows": clf["n_rows"],
            "top3": clf["top3"],
        }
        findings.append(finding)
        log_lines.append(f"{list_id}\tHIT\t{clf['title']}\t{clf['n_rows']}\t{clf['top3']}")
        print(f"  HIT {list_id}: {clf['title']} | n={clf['n_rows']} | {clf['top3'][0] if clf['top3'] else ''}", flush=True)
        # Progress dump every 5 hits
        if n_hits % 5 == 0:
            out_index.write_text(json.dumps(findings, indent=2, ensure_ascii=False))
            out_log.write_text("\n".join(log_lines), encoding="utf-8")

    # Final write
    out_index.write_text(json.dumps(findings, indent=2, ensure_ascii=False))
    out_log.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"DONE: {n_hits} hits, elapsed={time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
