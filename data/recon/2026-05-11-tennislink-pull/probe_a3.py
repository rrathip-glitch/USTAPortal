"""Objective A round 3: dense scan of 2072500-2085000 for additional junior lists.

In round 2 we found 2072420-2072459 was a contiguous junior block.
Maybe there are more contiguous junior blocks nearby. Probe stride-1
in two ranges 2072500-2073000 and 2080000-2085000.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib import OUT, fetch_form, fetch_print, make_httpx, quick_classify


KNOWN_DONE = set()
# Build the already-done list
for fname in OUT.glob("tennislink-*.html"):
    if "-form.html" in fname.name:
        continue
    m = fname.stem.replace("tennislink-", "")
    if m.isdigit():
        KNOWN_DONE.add(int(m))
# Also exclude the janav-browse files
for fname in Path("/home/user/USTAPortal/data/recon/2026-05-11-janav-browse").glob("tennislink-*.html"):
    m = fname.stem.replace("tennislink-", "").replace("-print", "")
    if m.isdigit():
        KNOWN_DONE.add(int(m))


def candidate_ids() -> list[int]:
    ids: set[int] = set()
    # Dense scan 2072500-2073000 (just past the known block)
    for x in range(2072460, 2073050):
        ids.add(x)
    # Dense scan in 2074000-2074500
    for x in range(2074000, 2074600, 1):
        ids.add(x)
    # Dense scan in 2083000-2085000 (where one 2018 list hit at 2083000, 2084000)
    for x in range(2082500, 2085500, 2):  # stride 2
        ids.add(x)
    # Also scan around 1752987 more
    for x in range(1753000, 1753100, 1):
        ids.add(x)
    # And around 1684711
    for x in range(1684750, 1684850, 1):
        ids.add(x)
    return sorted(ids - KNOWN_DONE)


def main():
    out_index = OUT / "objA3_index.json"
    out_log = OUT / "objA3_probe_log.txt"
    findings: list[dict] = []
    log_lines: list[str] = []

    client = make_httpx()
    candidates = candidate_ids()
    print(f"probing {len(candidates)} candidate IDs (Round 3, KNOWN_DONE size={len(KNOWN_DONE)})...", flush=True)
    t0 = time.time()
    TIME_BUDGET_S = 12 * 60  # 12 min

    n_hits = 0
    for i, list_id in enumerate(candidates):
        elapsed = time.time() - t0
        if elapsed > TIME_BUDGET_S:
            log_lines.append(f"# time budget exceeded at i={i}")
            print(f"time budget exceeded at i={i}", flush=True)
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
            log_lines.append(f"{list_id}\tEMPTY")
            continue
        n_hits += 1
        (OUT / f"tennislink-{list_id}.html").write_text(html, encoding="utf-8")
        finding = {
            "list_id": list_id,
            "title": clf["title"],
            "n_rows": clf["n_rows"],
            "top3": clf["top3"],
        }
        findings.append(finding)
        log_lines.append(f"{list_id}\tHIT\t{clf['title']}\t{clf['n_rows']}\t{clf['top3']}")
        print(f"  HIT {list_id}: {clf['title']} | n={clf['n_rows']} | {clf['top3'][0] if clf['top3'] else ''}", flush=True)
        if n_hits % 10 == 0:
            out_index.write_text(json.dumps(findings, indent=2, ensure_ascii=False))
            out_log.write_text("\n".join(log_lines), encoding="utf-8")
    out_index.write_text(json.dumps(findings, indent=2, ensure_ascii=False))
    out_log.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"DONE: hits={n_hits}, elapsed={time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
