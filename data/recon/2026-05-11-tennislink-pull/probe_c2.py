"""Objective C round 2: proper player search using the actual submit button names.

There are two search forms on RankingHome.aspx:

1. Search Player Record (tournament history):
   POST with ctl00$mainContent$btnSearch_PlayerRecord=SEARCH and
   ctl00$mainContent$txtRecordPlayerName="LastName, FirstName"
   Date range fields: txtStartDate, txtEndDate

2. Search Archived Player Ranking (by year):
   POST with ctl00$mainContent$btnSearch_PlayerRanking=SEARCH and
   ctl00$mainContent$txtRankingPlayerName="LastName, FirstName"
   Year field: ddlYearRanking
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib import OUT, TL, make_httpx
from probe_b import hidden_fields


def search_player_record(client, hidden, *, player_name, start="01/01/2010", end="12/31/2026"):
    form = {
        **hidden,
        "ctl00$mainContent$txtRecordPlayerName": player_name,
        "ctl00$mainContent$txtRankingUSTANo": "",
        "ctl00$mainContent$txtUstaNum": "",
        "ctl00$mainContent$txtStartDate": start,
        "ctl00$mainContent$txtEndDate": end,
        "ctl00$mainContent$btnSearch_PlayerRecord": "SEARCH",
    }
    resp = client.post(
        f"{TL}/tournaments/Rankings/RankingHome.aspx",
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return resp.status_code, resp.text


def search_player_ranking(client, hidden, *, player_name, year=""):
    form = {
        **hidden,
        "ctl00$mainContent$txtRankingPlayerName": player_name,
        "ctl00$mainContent$txtRankingUSTANo": "",
        "ctl00$mainContent$ddlYearRanking": str(year) if year else "",
        "ctl00$mainContent$btnSearch_PlayerRanking": "SEARCH",
    }
    resp = client.post(
        f"{TL}/tournaments/Rankings/RankingHome.aspx",
        data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return resp.status_code, resp.text


def diagnose(html, what):
    """Return summary of search results state."""
    soup_text = re.sub(r"<[^>]+>", " ", html)
    soup_text = re.sub(r"\s+", " ", soup_text)
    m = re.search(r"Search Results\s*\((\d+)\)", soup_text)
    n_results = int(m.group(1)) if m else None
    has_thasen = "thasen" in html.lower()
    no_players_msg = "no players found" in html.lower()
    has_target = what.lower() in html.lower()
    # MID= or playerid= or Sender=PlayerRecords links
    mids = sorted(set(re.findall(r"MID=(\d+)", html)))
    playerids = sorted(set(re.findall(r"playerid=([A-Za-z0-9%]+)", html)))
    return {
        "n_results_label": n_results,
        "has_thasen": has_thasen,
        "no_players_msg": no_players_msg,
        "has_target_name": has_target,
        "mids": mids,
        "playerids": playerids,
    }


def main():
    client = make_httpx()
    resp = client.get(f"{TL}/tournaments/Rankings/RankingHome.aspx")
    hidden = hidden_fields(resp.text)
    print(f"hidden keys: {sorted(hidden.keys())}", flush=True)

    findings = []
    # Test 1: Use the player-RECORD search (tournament history) for Janav
    targets_record = [
        ("Thasen, Janav", "01/01/2017", "12/31/2026"),
        ("Thasen, J", "01/01/2017", "12/31/2026"),
        ("Thasen, ", "01/01/2017", "12/31/2026"),  # last-name only
        ("Thasen, Vihana", "01/01/2017", "12/31/2026"),
        # Control: known top-of-list players (recent tournaments)
        ("Quan, Rudy", "01/01/2017", "12/31/2020"),
        ("Quan, Rudy", "01/01/2020", "12/31/2026"),
        ("Nakashima, Brandon", "01/01/2015", "12/31/2020"),
    ]
    for player_name, start, end in targets_record:
        try:
            s, html = search_player_record(client, hidden, player_name=player_name, start=start, end=end)
        except Exception as exc:
            print(f"  RECORD '{player_name}' ERR: {exc}", flush=True)
            continue
        diag = diagnose(html, player_name.split(",")[0])
        fname = f"prc-record-{player_name.replace(', ', '_').replace(' ', '_')}-{start.replace('/','')}-{end.replace('/','')}.html"
        (OUT / fname).write_text(html, encoding="utf-8")
        rec = {"type": "record", "player_name": player_name, "start": start, "end": end, "file": fname, **diag}
        findings.append(rec)
        print(f"  RECORD '{player_name}' [{start}..{end}]: n={diag['n_results_label']} thasen={diag['has_thasen']} no_players={diag['no_players_msg']} mids={diag['mids'][:5]} playerids={diag['playerids'][:3]}", flush=True)
        new_hidden = hidden_fields(html)
        if "__VIEWSTATE" in new_hidden:
            hidden = new_hidden
        time.sleep(0.4)

    print()
    # Test 2: Use the archived-RANKING search for Janav
    targets_ranking = [
        ("Thasen, Janav", ""),
        ("Thasen, Janav", "2020"),
        ("Thasen, Janav", "2018"),
        ("Thasen, ", ""),
        # Control: known players who appeared in archived rankings
        ("Quan, Rudy", "2018"),
        ("Quan, Rudy", ""),
        ("Nakashima, Brandon", "2017"),
    ]
    for player_name, year in targets_ranking:
        try:
            s, html = search_player_ranking(client, hidden, player_name=player_name, year=year)
        except Exception as exc:
            print(f"  RANKING '{player_name}' y={year} ERR: {exc}", flush=True)
            continue
        diag = diagnose(html, player_name.split(",")[0])
        fname = f"prc-ranking-{player_name.replace(', ', '_').replace(' ', '_')}-y{year or 'all'}.html"
        (OUT / fname).write_text(html, encoding="utf-8")
        rec = {"type": "ranking", "player_name": player_name, "year": year, "file": fname, **diag}
        findings.append(rec)
        print(f"  RANKING '{player_name}' y={year or 'all'}: n={diag['n_results_label']} thasen={diag['has_thasen']} no_players={diag['no_players_msg']} mids={diag['mids'][:5]} playerids={diag['playerids'][:3]}", flush=True)
        new_hidden = hidden_fields(html)
        if "__VIEWSTATE" in new_hidden:
            hidden = new_hidden
        time.sleep(0.4)

    (OUT / "objC2_index.json").write_text(json.dumps(findings, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
