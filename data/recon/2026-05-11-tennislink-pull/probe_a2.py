"""Objective A continuation - focus on CURRENT IDs (around 2072448, 1684711, 1752987).

Skip the stale 1241xxx region entirely. Probe in widening rings around
the three confirmed-current IDs, plus a denser scan of 2050000-2090000
which is where 2026 lists appear to live.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib import OUT, fetch_form, fetch_print, make_httpx, quick_classify


def candidate_ids() -> list[int]:
    ids: set[int] = set()
    # Tight neighborhood probes around each CURRENT known list (stride 1, +/-40)
    for base in [2072448, 1684711, 1752987]:
        for delta in range(-40, 41):
            ids.add(base + delta)
    # Stride 500 sweeps for the 2026 region
    for x in range(2_060_000, 2_085_000, 500):
        ids.add(x)
    # Stride 500 sweep for the 1.68M-1.76M middle region (B14/B16 era)
    for x in range(1_680_000, 1_760_000, 500):
        ids.add(x)
    return sorted(ids)


def main() -> None:
    out_index = OUT / "objA2_index.json"
    out_log = OUT / "objA2_probe_log.txt"
    findings: list[dict] = []
    log_lines: list[str] = []

    client = make_httpx()
    candidates = candidate_ids()
    print(f"probing {len(candidates)} candidate IDs (Round 2)...", flush=True)
    t0 = time.time()
    TIME_BUDGET_S = 18 * 60

    n_hits = 0
    n_known_skip = 0
    KNOWN_DONE = {1241763, 1241764, 1241766, 1241767, 1241769, 1241770,
                  1241772, 1241773, 1241775, 1241776, 1241778, 1241779,
                  1241780, 1241781, 1241782, 1241783, 1241784, 1241785,
                  1241786, 1241787, 1241788, 1241789, 1241790, 1241791,
                  1241792, 2072448, 1684711, 1752987, 1234828}
    for i, list_id in enumerate(candidates):
        elapsed = time.time() - t0
        if elapsed > TIME_BUDGET_S:
            log_lines.append(f"# time budget exceeded at i={i}")
            print(f"time budget exceeded at i={i}", flush=True)
            break
        if list_id in KNOWN_DONE:
            n_known_skip += 1
            continue
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
        if n_hits % 5 == 0:
            out_index.write_text(json.dumps(findings, indent=2, ensure_ascii=False))
            out_log.write_text("\n".join(log_lines), encoding="utf-8")
    out_index.write_text(json.dumps(findings, indent=2, ensure_ascii=False))
    out_log.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"DONE: hits={n_hits}, skipped={n_known_skip}, elapsed={time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
