"""Objective E: probe Florida Regions (1538=Region 8 = Janav home) for B10/B12 in his birth window.

Janav was born ~2013. He was on the 'Boys 10' radar 2022-2024 and the
'Boys 12' radar 2024-2026 (currently). Per known_urls.md, B10 was
NEVER on TennisLink. B12 froze in early 2021.

Probe every Florida Region for every age category in every year 2019-2024
to rule out any micro-window where Janav-relevant data might exist.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib import OUT, TL, fetch_print, make_httpx, quick_classify
from probe_b import hidden_fields, post_search


REGIONS = [
    ("1531", "Florida - Region 1"),
    ("1532", "Florida - Region 2"),
    ("1533", "Florida - Region 3"),
    ("1534", "Florida - Region 4"),
    ("1535", "Florida - Region 5"),
    ("1536", "Florida - Region 6"),
    ("1537", "Florida - Region 7"),
    ("1538", "Florida - Region 8"),  # Broward = Janav's home
]


def main():
    client = make_httpx()
    resp = client.get(f"{TL}/tournaments/Rankings/RankingHome.aspx")
    hidden = hidden_fields(resp.text)

    findings = []
    all_list_ids = set()
    queries = []
    for region_code, region_name in REGIONS:
        for year in range(2019, 2025):
            for division in ["D1007", "D1009"]:  # B12, B10
                queries.append({"section": region_code, "region_name": region_name, "year": year, "division": division})

    print(f"Running {len(queries)} Florida-region queries...", flush=True)
    for i, q in enumerate(queries):
        try:
            status, html = post_search(client, hidden, q["section"], q["year"], q["division"], -1)
        except Exception as exc:
            print(f"  [{i}] ERR: {exc}", flush=True)
            continue
        ids = sorted(set(re.findall(r"Sender=RankingList&type=searchresults&id=(\d+)", html)), key=int)
        all_list_ids.update(ids)
        no_info = "no ranking information" in html.lower()
        if ids:
            print(f"  [{i}] {q['region_name']} y={q['year']} {q['division']}: {len(ids)} lists", flush=True)
        findings.append({**q, "n_ids": len(ids), "no_info": no_info, "first5": ids[:5]})
        new_hidden = hidden_fields(html)
        if "__VIEWSTATE" in new_hidden:
            hidden = new_hidden
        time.sleep(0.3)
    print(f"\nTotal Florida-region list IDs: {len(all_list_ids)}", flush=True)
    (OUT / "objE_index.json").write_text(json.dumps({"queries": findings, "all_list_ids": sorted(all_list_ids, key=int)}, indent=2))

    # Now grep each for Thasen
    thasen_hits = []
    list_meta = []
    print("\nFetching each Florida-region list and searching for Thasen...", flush=True)
    for j, lid in enumerate(sorted(all_list_ids, key=int)):
        try:
            s, html = fetch_print(client, lid)
        except Exception as exc:
            print(f"  {lid}: ERR {exc}", flush=True)
            continue
        if s != 200:
            continue
        clf = quick_classify(html)
        if "thasen" in html.lower():
            print(f"  !! {lid} CONTAINS THASEN", flush=True)
            thasen_hits.append({"list_id": lid, "title": clf["title"]})
            (OUT / f"tennislink-region-{lid}.html").write_text(html, encoding="utf-8")
        list_meta.append({"list_id": lid, "title": clf["title"], "n_rows": clf["n_rows"], "top1": clf["top3"][0] if clf["top3"] else None})
    (OUT / "objE_meta.json").write_text(json.dumps({"thasen_hits": thasen_hits, "list_meta": list_meta}, indent=2, ensure_ascii=False))
    print(f"DONE. Thasen hits: {len(thasen_hits)} / {len(list_meta)}", flush=True)


if __name__ == "__main__":
    main()
