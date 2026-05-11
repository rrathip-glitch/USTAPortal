"""Objective B continuation: verify the Florida-section form works for
years where the underlying database isn't frozen.

Use Adult Men's 40 or Senior NTRP which are CURRENT in 2026 to confirm
the form path actually works. Also try Florida B12 for years 2017-2020
where the underlying B12 data exists per known_urls.md.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib import OUT, TL, make_httpx
from probe_b import hidden_fields, post_search


def main():
    client = make_httpx()
    resp = client.get(f"{TL}/tournaments/Rankings/RankingHome.aspx")
    hidden = hidden_fields(resp.text)
    print(f"hidden keys: {sorted(hidden.keys())}", flush=True)

    # Florida (15) -- verified working at 2017-2020 per known_urls.md.
    # Also try district 1538 (Florida Region 8) which is the Janav area.
    queries = [
        # B12 Florida by year (where there should be data)
        {"section": "15", "year": 2020, "division": "D1007", "list_type": -1, "label": "Florida B12 Singles 2020 all"},
        {"section": "15", "year": 2019, "division": "D1007", "list_type": -1, "label": "Florida B12 Singles 2019 all"},
        {"section": "15", "year": 2018, "division": "D1007", "list_type": -1, "label": "Florida B12 Singles 2018 all"},
        # Florida Region 8 (Broward FL = Janav's home)
        {"section": "1538", "year": 2018, "division": "D1007", "list_type": -1, "label": "Florida Region8 B12 2018"},
        # Florida district 7 (Region 7)
        {"section": "1537", "year": 2018, "division": "D1007", "list_type": -1, "label": "Florida Region7 B12 2018"},
        # B12 Doubles Florida
        {"section": "15", "year": 2018, "division": "D1107", "list_type": -1, "label": "Florida B12 Doubles 2018"},
        # Adult Men's 40 Florida 2026
        {"section": "15", "year": 2026, "division": "D3004", "list_type": -1, "label": "Florida M40 Singles 2026"},
        # Florida G12 2018 (where data should be present)
        {"section": "15", "year": 2018, "division": "D1021", "list_type": -1, "label": "Florida G12 Singles 2018"},
        # Florida B12 2025 (where freeze applies)
        {"section": "15", "year": 2025, "division": "D1007", "list_type": -1, "label": "Florida B12 Singles 2025 (frozen)"},
    ]
    findings = []
    for q in queries:
        try:
            status, html = post_search(client, hidden, q["section"], q["year"], q["division"], q["list_type"])
        except Exception as exc:
            print(f"  {q['label']}: ERR {exc}", flush=True)
            continue
        fname = f"florida-extended-{q['division']}-{q['section']}-{q['year']}-LT{q['list_type']}.html"
        (OUT / fname).write_text(html, encoding="utf-8")
        lower = html.lower()
        thasen = "thasen" in lower
        no_info = "no ranking information" in lower
        ranklist_ids = sorted(set(re.findall(r"rankinglistid=(\d+)", html)))
        rec = {
            **q,
            "status": status,
            "has_thasen": thasen,
            "no_info": no_info,
            "ranklist_ids_seen": ranklist_ids,
            "file": fname,
        }
        findings.append(rec)
        print(f"  {q['label']}: status={status} thasen={thasen} no_info={no_info} #ranklists={len(ranklist_ids)} (first 5: {ranklist_ids[:5]})", flush=True)
        new_hidden = hidden_fields(html)
        if "__VIEWSTATE" in new_hidden:
            hidden = new_hidden
        time.sleep(0.4)

    (OUT / "objB2_index.json").write_text(json.dumps(findings, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
