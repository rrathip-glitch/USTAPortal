"""Objective C: hunt Janav Thasen's TennisLink player record.

The player-record search lives on RankingHome.aspx. The actual search
is triggered client-side by the SearchPlayerRecord() JS, which calls
__doPostBack with a specific payload. The hidden hfHistoryPointParam
field shows the encoded query format.

Strategy: POST to RankingHome.aspx with __EVENTTARGET set to
ctl00$mainContent$UpdatePanel_RankingHome and __EVENTARGUMENT set to
the player-record search payload. The page returns a Vue-driven
listing of matching players.
"""

from __future__ import annotations

import json
import re
import time
import sys
from pathlib import Path
import urllib.parse

sys.path.insert(0, str(Path(__file__).parent))
from _lib import OUT, TL, make_httpx


def hidden_fields(html: str) -> dict[str, str]:
    out = {}
    for name in (
        "__VIEWSTATE",
        "__VIEWSTATEGENERATOR",
        "__EVENTVALIDATION",
        "__VIEWSTATEENCRYPTED",
        "__PREVIOUSPAGE",
    ):
        m = re.search(rf'name="{re.escape(name)}"[^>]*value="([^"]*)"', html)
        if m:
            out[name] = m.group(1)
    return out


def search_player_record(client, hidden, *, first_name="", last_name="",
                         usta_num="", start="01/01/2017", end="12/31/2026"):
    """POST a player-record search."""
    # Build the encoded query string for hfHistoryPointParam
    # Sender code 2 = PlayerRecord search; format is "2\Usta_X\FirstName_Y\..."
    hist_param = (
        f"2\\Usta_{usta_num}\\FirstName_{first_name}\\MiddleName_\\"
        f"LastName_{last_name}\\Start_{start}\\End_{end}"
    )
    form = {
        **hidden,
        "__EVENTTARGET": "ctl00$mainContent$UpdatePanel_RankingHome",
        "__EVENTARGUMENT": f"Sender=PlayerRecords&FirstName={first_name}&LastName={last_name}&Usta={usta_num}&Start={start}&End={end}",
        "ctl00$mainContent$txtRecordPlayerName": f"{last_name}, {first_name}" if last_name else "",
        "ctl00$mainContent$txtUstaNum": usta_num,
        "ctl00$mainContent$hfHistoryPointParam": hist_param,
        "ctl00$mainContent$txtStartDate": start,
        "ctl00$mainContent$txtEndDate": end,
        "q_player_record": "rdoExactMatch",  # exact match
        "ctl00$ScriptManager1": "ctl00$mainContent$UpdatePanel_RankingHome|ctl00$mainContent$UpdatePanel_RankingHome",
    }
    resp = client.post(
        f"{TL}/tournaments/Rankings/RankingHome.aspx",
        data=form,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-MicrosoftAjax": "Delta=true",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    return resp.status_code, resp.text


def main():
    client = make_httpx()
    print("getting form...", flush=True)
    resp = client.get(f"{TL}/tournaments/Rankings/RankingHome.aspx")
    hidden = hidden_fields(resp.text)
    print(f"  hidden keys: {sorted(hidden.keys())}", flush=True)

    queries = [
        # variation 1: Janav last=Thasen
        {"first_name": "Janav", "last_name": "Thasen", "start": "01/01/2017", "end": "12/31/2026"},
        {"first_name": "Janav", "last_name": "Thasen", "start": "01/01/2023", "end": "12/31/2026"},
        # in case it's swapped or short
        {"first_name": "J", "last_name": "Thasen", "start": "01/01/2017", "end": "12/31/2026"},
        # Last-name only
        {"first_name": "", "last_name": "Thasen", "start": "01/01/2017", "end": "12/31/2026"},
        # Sister Vihana — known to exist
        {"first_name": "Vihana", "last_name": "Thasen", "start": "01/01/2017", "end": "12/31/2026"},
        # Control: Quan Rudy (we know he's #1 on 2072448)
        {"first_name": "Rudy", "last_name": "Quan", "start": "01/01/2017", "end": "12/31/2026"},
    ]
    findings = []
    for i, q in enumerate(queries):
        try:
            status, html = search_player_record(client, hidden, **q)
        except Exception as exc:
            print(f"  [{i}] ERR: {exc}", flush=True)
            continue
        fname = f"player-record-search-{q['last_name'] or 'noLast'}-{q['first_name'] or 'noFirst'}.html"
        (OUT / fname).write_text(html, encoding="utf-8")
        # Sniff for results: "Search Results(N)" or player table
        m = re.search(r"Search Results\s*\((\d+)\)", html)
        n_results = int(m.group(1)) if m else None
        # Check raw HTML for the player name to be sure
        has_thasen = "thasen" in html.lower()
        has_target = (q.get("last_name", "").lower() in html.lower()) if q.get("last_name") else False
        # Look for playerid= links
        playerids = sorted(set(re.findall(r"playerid=([A-Za-z0-9%]+)", html)))
        # Refresh hidden after each
        new_hidden = hidden_fields(html)
        if "__VIEWSTATE" in new_hidden:
            hidden = new_hidden
        rec = {
            "query": q,
            "status": status,
            "n_results_label": n_results,
            "has_target_name": has_target,
            "has_thasen": has_thasen,
            "playerids_found": playerids,
            "file": fname,
        }
        findings.append(rec)
        print(f"  [{i}] {q}: status={status} n_results={n_results} has_target={has_target} playerids={playerids[:5]}", flush=True)
        time.sleep(0.5)
    (OUT / "objC_index.json").write_text(json.dumps(findings, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
