"""Objective B: Florida-section filter via ASP.NET form POST.

We GET the RankingHome.aspx form, scrape its hidden fields
(__VIEWSTATE, __VIEWSTATEGENERATOR, __EVENTVALIDATION), then POST back
with the section dropdown set to "15" (Florida) and a Division like
D1007 (Boys' 12 Singles).

For each (division, year) combination we save the response HTML and
grep it for "Thasen".
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from _lib import OUT, TL, make_httpx

DIVISIONS = [
    ("D1009", "Boys' 10 Singles"),
    ("D1007", "Boys' 12 Singles"),
    ("D1005", "Boys' 14 Singles"),
    ("D1003", "Boys' 16 Singles"),
    ("D1001", "Boys' 18 Singles"),
    ("D1107", "Boys' 12 Doubles"),
    ("D1021", "Girls' 12 Singles"),
    ("D1019", "Girls' 14 Singles"),
]


def hidden_fields(html: str) -> dict[str, str]:
    out = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION", "__VIEWSTATEENCRYPTED", "__PREVIOUSPAGE", "__EVENTTARGET", "__EVENTARGUMENT"):
        m = re.search(rf'name="{re.escape(name)}"[^>]*value="([^"]*)"', html)
        if m:
            out[name] = m.group(1)
    return out


def post_search(client, hidden, section, year, division, list_type=-1):
    """POST the search form. Returns HTML or status string."""
    form = {
        **hidden,
        "ctl00$mainContent$SectionDistrict": section,
        "ctl00$mainContent$Year": str(year),
        "ctl00$mainContent$Division": division,
        "ctl00$mainContent$ListType": str(list_type),
        "ctl00$mainContent$btnSearch_Ranking": "FIND IT!",
    }
    resp = client.post(
        f"{TL}/tournaments/Rankings/RankingHome.aspx",
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return resp.status_code, resp.text


def main():
    client = make_httpx()
    out_index = []
    # Step 1: GET the form to acquire VIEWSTATE
    print("getting form...", flush=True)
    resp = client.get(f"{TL}/tournaments/Rankings/RankingHome.aspx")
    print(f"form GET status={resp.status_code} len={len(resp.text)}", flush=True)
    hidden = hidden_fields(resp.text)
    if "__VIEWSTATE" not in hidden:
        print("ERROR: no VIEWSTATE found!", flush=True)
        return
    print(f"acquired hidden fields: {sorted(hidden.keys())}", flush=True)

    # Try combinations for Florida (section=15) across years 2024-2026
    YEARS = [2026, 2025, 2024, 2023]
    LIST_TYPES = [-1, 0, 27, 26]  # All, Standing, 12-month rolling, Calendar Year

    for division, dname in DIVISIONS:
        for year in YEARS:
            for ltype in LIST_TYPES:
                fname = f"florida-{division}-{year}-LT{ltype}.html"
                fpath = OUT / fname
                try:
                    status, html = post_search(client, hidden, "15", year, division, ltype)
                except Exception as exc:
                    print(f"  {division} {year} LT={ltype} ERR: {exc}", flush=True)
                    continue
                fpath.write_text(html, encoding="utf-8")
                lower = html.lower()
                thasen = "thasen" in lower
                no_info = "no ranking information" in lower
                # Count populated rows - look for player record links
                # Hits also produce ranklistid hyperlinks
                ranklist_ids = sorted(set(re.findall(r"rankinglistid=(\d+)", html)))
                rec = {
                    "division": division,
                    "division_name": dname,
                    "year": year,
                    "list_type": ltype,
                    "status": status,
                    "has_thasen": thasen,
                    "no_info": no_info,
                    "ranklist_ids_seen": ranklist_ids,
                    "filepath": str(fpath.relative_to(OUT)),
                }
                out_index.append(rec)
                print(f"  {division} y={year} LT={ltype}: thasen={thasen} no_info={no_info} ranklists={ranklist_ids[:5]}", flush=True)
                # If thasen, dump rank context
                if thasen:
                    # Find lines around "Thasen"
                    for m in re.finditer(r".{0,400}thasen.{0,400}", html, re.IGNORECASE | re.DOTALL):
                        snippet = re.sub(r"\s+", " ", m.group(0))[:800]
                        print(f"    THASEN ctx: {snippet}", flush=True)
                # After a successful POST, refresh hidden fields from response
                # (VIEWSTATE rotates between POSTs)
                new_hidden = hidden_fields(html)
                if "__VIEWSTATE" in new_hidden:
                    hidden = new_hidden
                time.sleep(0.5)

    (OUT / "objB_index.json").write_text(json.dumps(out_index, indent=2, ensure_ascii=False))
    print(f"DONE. {len(out_index)} POSTs made.", flush=True)


if __name__ == "__main__":
    main()
