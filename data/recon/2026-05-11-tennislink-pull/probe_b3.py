"""Objective B3: scan Florida current-era ranking lists and grep for Janav.

For each Florida list ID we extracted, fetch the print HTML and search
for 'Thasen' (case-insensitive). This is the ONLY remaining path on
TennisLink to verify whether Janav has been ranked sectionally.

We also probe Florida B10 (D1009 — never on TennisLink per known_urls.md
but worth confirming for our era) and Florida Co-ed 10 (D2003).
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


def main():
    client = make_httpx()
    # Step 1: full re-scan of Florida B12/G12/Co-ed10/B10 across years 2017-2024
    resp = client.get(f"{TL}/tournaments/Rankings/RankingHome.aspx")
    hidden = hidden_fields(resp.text)

    queries = []
    # Focus on Janav-relevant: B10/B12 in Florida 2018-2024
    for year in range(2018, 2025):
        for division in ["D1007", "D1009", "D1011"]:  # B12, B10, B8 singles
            queries.append({"section": "15", "year": year, "division": division})
    # Adult Florida 2026 to confirm form works at all for current
    queries.append({"section": "15", "year": 2026, "division": "D3004"})  # M40
    queries.append({"section": "15", "year": 2026, "division": "D3018"})  # W30

    print(f"Running {len(queries)} Florida queries...", flush=True)
    findings = []
    all_florida_list_ids = set()
    for i, q in enumerate(queries):
        try:
            status, html = post_search(client, hidden, q["section"], q["year"], q["division"], -1)
        except Exception as exc:
            print(f"  [{i}] ERR: {exc}", flush=True)
            continue
        ids = sorted(set(re.findall(r"Sender=RankingList&type=searchresults&id=(\d+)", html)), key=int)
        all_florida_list_ids.update(ids)
        no_info = "no ranking information" in html.lower()
        rec = {**q, "n_ids": len(ids), "no_info": no_info, "first5": ids[:5]}
        findings.append(rec)
        if ids:
            print(f"  [{i}] {q['division']} y={q['year']} sec={q['section']}: {len(ids)} list IDs", flush=True)
        new_hidden = hidden_fields(html)
        if "__VIEWSTATE" in new_hidden:
            hidden = new_hidden
        time.sleep(0.3)

    print(f"\nTotal distinct Florida list IDs: {len(all_florida_list_ids)}", flush=True)
    (OUT / "objB3_florida_list_ids.json").write_text(json.dumps({
        "queries": findings,
        "all_florida_list_ids": sorted(all_florida_list_ids, key=int),
    }, indent=2))

    # Step 2: fetch each Florida list, search for Thasen
    print("\nFetching each Florida list and grepping for Thasen...", flush=True)
    thasen_hits = []
    list_meta = []
    for j, lid in enumerate(sorted(all_florida_list_ids, key=int)):
        try:
            s, html = fetch_print(client, lid)
        except Exception as exc:
            print(f"  {lid}: ERR {exc}", flush=True)
            continue
        if s != 200:
            continue
        clf = quick_classify(html)
        if "thasen" in html.lower():
            print(f"  !! {lid} CONTAINS THASEN ({clf['title']})", flush=True)
            thasen_hits.append({"list_id": lid, "title": clf["title"]})
            # Save it
            (OUT / f"tennislink-florida-{lid}.html").write_text(html, encoding="utf-8")
        list_meta.append({"list_id": lid, "title": clf["title"], "n_rows": clf["n_rows"], "top1": clf["top3"][0] if clf["top3"] else None})
        if j % 20 == 19:
            print(f"  ...{j+1}/{len(all_florida_list_ids)} done", flush=True)
    (OUT / "objB3_florida_meta.json").write_text(json.dumps({
        "thasen_hits": thasen_hits,
        "list_meta": list_meta,
    }, indent=2, ensure_ascii=False))
    print(f"DONE. Thasen hits: {len(thasen_hits)} / {len(list_meta)} lists", flush=True)


if __name__ == "__main__":
    main()
