"""Objective D: crawl WTN for top-20 of each CURRENT list via stg-itf.

For each of the high-confidence CURRENT lists, parse top-20 names then
query `publicPersons` filter by searchTerm=lastname. For each match
that looks plausible (same first+last, US country, plausible birth
year for the age category), pull the full `person` record with
worldTennisNumbers.

Rate limit: 2 seconds between GraphQL calls.
Stop: 200 GraphQL calls total or 25 minutes elapsed.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib import OUT, parse_full_print
from curl_cffi import requests as cc_requests


STG = "https://stg-itf-kube.clubspark.io/tods-gw-api/graphql"

# Curated list of CURRENT lists to crawl (highest priority)
# Boys 12 (Combined) is the canonical Janav list, even though he's not in it.
PRIORITY_LISTS = [
    # B12
    (2072448, "Boys 12 Combined"),
    (2072432, "Boys 12 Singles Seeding"),
    (2072424, "Boys 12 Doubles Seeding"),
    # B14
    (2072451, "Boys 14 Combined"),
    (2072433, "Boys 14 Singles Seeding"),
    (2072425, "Boys 14 Doubles Seeding"),
    # B16
    (2072454, "Boys 16 Combined"),
    (2072434, "Boys 16 Singles Seeding"),
    (2072426, "Boys 16 Doubles Seeding"),
    # B18
    (2072457, "Boys 18 Combined"),
    (2072435, "Boys 18 Singles Seeding"),
    (2072427, "Boys 18 Doubles Seeding"),
    # Girls
    (2072436, "Girls 12 Combined"),
    (2072439, "Girls 14 Combined"),
    (2072442, "Girls 16 Combined"),
    (2072445, "Girls 18 Combined"),
]

# Birth year range expected for each age category.
# IMPORTANT: TennisLink lists are HISTORICAL (frozen ~early 2021), so the
# "Boys 12" list players are now ~19-20 years old (born ~2006-2007).
# The "Boys 14" list players are now ~21-22 (born ~2004-2005).
# So we use a WIDE band that covers both interpretations: the
# "from year 2018-2019" interpretation and the "currently aged 11-12" interp.
AGE_BAND_BIRTH_YEAR = {
    "12": (2003, 2015),  # very wide
    "14": (2001, 2013),
    "16": (1999, 2011),
    "18": (1997, 2009),
}


def search_persons(session, full_name, max_retries=2):
    """Search publicPersons by 'First Last' string."""
    safe = full_name.replace('"', '\\"')
    query = """
    {
      publicPersons(filter: { search: { term: "%s" } }, pageArgs: { skip: 0, limit: 25 }) {
        items {
          id
          tennisID
          clubsparkId
          nativeGivenName
          nativeFamilyName
          birthYear
          sex
          worldTennisNumbers {
            tennisNumber
            type
            confidence
            isRanked
            ratingDate
          }
        }
      }
    }
    """ % safe
    for attempt in range(max_retries):
        try:
            r = session.post(STG, json={"query": query}, impersonate="chrome131", timeout=30, verify=False)
            if r.status_code != 200:
                if attempt + 1 < max_retries:
                    time.sleep(2.0)
                    continue
                return None, f"HTTP {r.status_code}"
            try:
                return r.json(), None
            except Exception as exc:
                return None, f"parse_error: {exc}"
        except Exception as exc:
            if attempt + 1 < max_retries:
                time.sleep(2.0)
                continue
            return None, str(exc)
    return None, "max_retries"


def match_person(items, target_first, target_last, age_band):
    """Score each candidate. Returns best match or None.

    items: list of person items from publicPersons
    target_first/target_last: from TennisLink (e.g., "Rudy", "Quan")
    age_band: e.g. "12"
    """
    if not items:
        return None
    low_first = target_first.lower().strip()
    low_last = target_last.lower().strip()
    full_target = f"{low_first} {low_last}"
    by_min, by_max = AGE_BAND_BIRTH_YEAR.get(age_band, (1900, 2100))
    best = None
    best_score = -1
    for item in items:
        g = (item.get("nativeGivenName") or "").lower().strip()
        f = (item.get("nativeFamilyName") or "").lower().strip()
        by = item.get("birthYear") or 0
        # Three name-match patterns:
        # 1. straight: given=first, family=last
        # 2. swapped: given=last, family=first
        # 3. concat: given="first last" or family="first last"
        concat_match = (g == full_target) or (f == full_target)
        straight = (g == low_first and f == low_last)
        swapped = (g == low_last and f == low_first)
        if concat_match or straight or swapped:
            name_score = 100
        elif g == low_first and f.startswith(low_last):
            name_score = 80
        elif (g == low_first) or (f == low_last):
            name_score = 50
        else:
            continue
        age_score = 0
        if by_min <= by <= by_max:
            age_score = 50
        elif by == 0:
            age_score = 20
        wtn = bool(item.get("worldTennisNumbers"))
        wtn_score = 30 if wtn else 0
        total = name_score + age_score + wtn_score
        if total > best_score:
            best = item
            best_score = total
    return best if best_score >= 80 else None


def run_for_list(session, list_id, label, top_n=20, calls_remaining=200):
    """Crawl WTN for the top-N of a single list."""
    path = OUT / f"tennislink-{list_id}.html"
    if not path.exists():
        path = Path("/home/user/USTAPortal/data/recon/2026-05-11-janav-browse") / f"tennislink-{list_id}.html"
        if not path.exists():
            return [], "no_html"
    parsed = parse_full_print(path.read_text(encoding="utf-8"))
    title = parsed.get("title", "")
    age_match = re.search(r"\b(12|14|16|18)\b", title or label or "")
    age_band = age_match.group(1) if age_match else "12"

    results = []
    calls = 0
    for player in parsed["players"][:top_n]:
        if calls >= calls_remaining:
            break
        name = player["name"]  # "Last, First"
        if "," not in name:
            continue
        last, first = [s.strip() for s in name.split(",", 1)]
        time.sleep(2.0)
        full = f"{first} {last}"
        resp, err = search_persons(session, full)
        calls += 1
        rec = {
            "rank": player["rank"],
            "name": name,
            "city": player["city"],
            "state": player["state"],
            "search_status": "ok" if not err else f"err:{err}",
        }
        if err or not resp or "data" not in resp or not resp["data"]:
            results.append(rec)
            continue
        items = (resp["data"].get("publicPersons") or {}).get("items") or []
        rec["search_n_results"] = len(items)
        best = match_person(items, first, last, age_band)
        if best:
            rec["match_tennisID"] = best.get("tennisID")
            rec["match_id"] = best.get("id")
            rec["match_nativeGivenName"] = best.get("nativeGivenName")
            rec["match_nativeFamilyName"] = best.get("nativeFamilyName")
            rec["match_birthYear"] = best.get("birthYear")
            rec["match_sex"] = best.get("sex")
            wtns = best.get("worldTennisNumbers") or []
            rec["wtn"] = wtns
            # Extract singles/doubles
            for w in wtns:
                if w.get("type") == "SINGLE":
                    rec["wtn_singles"] = w.get("tennisNumber")
                elif w.get("type") == "DOUBLE":
                    rec["wtn_doubles"] = w.get("tennisNumber")
        results.append(rec)
    return results, None


def main():
    session = cc_requests.Session()
    total_calls = 0
    summary = []
    BUDGET = 180  # cap at 180 calls
    TIME_LIMIT = 25 * 60  # 25 min
    t0 = time.time()

    out_dir = OUT
    for list_id, label in PRIORITY_LISTS:
        elapsed = time.time() - t0
        if elapsed > TIME_LIMIT or total_calls >= BUDGET:
            print(f"BUDGET/TIME exhausted; stopping at {list_id}", flush=True)
            break
        print(f"\n== List {list_id} ({label}) ==", flush=True)
        remaining = BUDGET - total_calls
        results, err = run_for_list(session, list_id, label, top_n=20, calls_remaining=remaining)
        if err:
            print(f"  SKIP: {err}", flush=True)
            continue
        total_calls += len(results)
        n_match = sum(1 for r in results if r.get("match_tennisID"))
        n_with_wtn = sum(1 for r in results if r.get("wtn_singles") or r.get("wtn_doubles"))
        print(f"  top-{len(results)} results: matched={n_match} with-WTN={n_with_wtn}", flush=True)
        # Save per-list
        out_file = out_dir / f"wtn-{list_id}-top20.json"
        out_file.write_text(json.dumps({
            "list_id": list_id,
            "label": label,
            "results": results,
            "n_matched": n_match,
            "n_with_wtn": n_with_wtn,
        }, indent=2, ensure_ascii=False))
        summary.append({
            "list_id": list_id,
            "label": label,
            "n_results": len(results),
            "n_matched": n_match,
            "n_with_wtn": n_with_wtn,
        })
    (out_dir / "objD_summary.json").write_text(json.dumps({
        "total_calls": total_calls,
        "elapsed_s": int(time.time() - t0),
        "per_list": summary,
    }, indent=2))
    print(f"\nDONE. total_calls={total_calls}, elapsed={int(time.time()-t0)}s", flush=True)


if __name__ == "__main__":
    main()
