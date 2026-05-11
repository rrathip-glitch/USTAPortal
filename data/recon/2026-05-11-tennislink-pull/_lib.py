"""Shared helpers for the 2026-05-11 tennislink pull recon.

These are intentionally simple — they live under data/recon/ so they
do NOT change src/ or tests/ but can be re-used across the various
probe scripts in this directory.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

OUT = Path("/home/user/USTAPortal/data/recon/2026-05-11-tennislink-pull")
TL = "https://tennislink.usta.com"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def make_httpx() -> httpx.Client:
    return httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        verify=False,  # sandbox clock makes new certs look "not yet valid"
        headers={
            "User-Agent": UA,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )


def fetch_print(client: httpx.Client, list_id: str | int) -> tuple[int, str]:
    """GET RankingListsPrint.aspx?id=<id>&e=1&sortby=rank"""
    url = f"{TL}/Tournaments/Rankings/RankingListsPrint.aspx"
    resp = client.get(url, params={"id": str(list_id), "e": "1", "sortby": "rank"})
    return resp.status_code, resp.text


def fetch_form(client: httpx.Client, list_id: str | int) -> tuple[int, str]:
    """GET the non-print form view RankingHome.aspx?rankinglistid=<id>"""
    url = f"{TL}/tournaments/Rankings/RankingHome.aspx"
    resp = client.get(url, params={"rankinglistid": str(list_id)})
    return resp.status_code, resp.text


def quick_classify(html: str) -> dict[str, Any]:
    """Inspect a print HTML to decide whether it's a populated list.

    Returns dict with:
        - has_list: True if a populated table is present
        - title: list title (e.g., "Boys 12 (Combined)")
        - n_rows: number of player rows
        - top3: first 3 player names
        - is_no_info: True if "No ranking information"
    """
    if not html:
        return {"has_list": False, "title": None, "n_rows": 0, "top3": [], "is_no_info": True, "reason": "empty"}
    lower = html.lower()
    is_no_info = "no ranking information" in lower
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body
    text = body.get_text("\n", strip=True) if body else ""
    # Title detection (same as parse_full_print)
    raw_lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = None
    for line in raw_lines[:30]:
        if "(" in line and ")" in line and 5 < len(line) < 120 and any(t in line for t in ("Boys", "Girls", "Men", "Women", "Mixed", "Co-ed", "STA")):
            title = line
            break
    if not title:
        for line in raw_lines[:30]:
            if 5 < len(line) < 120 and any(t in line for t in ("Boys", "Girls", "Men", "Women", "Mixed", "Co-ed")) and any(ch.isdigit() for ch in line):
                if line in ("Home", "Tournaments", "TennisLink") or line.startswith(">"):
                    continue
                title = line
                break
    # Find player rows: rank pattern is digit at start of line followed by Last, First on next line
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    n_rows = 0
    top3 = []
    i = 0
    # Skip header
    while i < len(lines):
        if lines[i].lower() == "rank" and i + 1 < len(lines) and lines[i+1].lower() == "name":
            # we've found the column-header zone, scan forward
            # Find a column-header for "Points"
            j = i
            while j < len(lines) and lines[j].lower() != "points":
                j += 1
            i = j + 1
            break
        i += 1
    # Now iterate through rows. Each row: rank (int), name (Last, First), city, state, section, district, points
    while i + 6 < len(lines):
        if re.fullmatch(r"\d+", lines[i]) and "," in lines[i+1]:
            n_rows += 1
            if len(top3) < 3:
                top3.append(lines[i+1])
            i += 7
        else:
            i += 1
    return {
        "has_list": n_rows > 0,
        "title": title,
        "n_rows": n_rows,
        "top3": top3,
        "is_no_info": is_no_info,
    }


def save_html(name: str, content: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    p.write_text(content, encoding="utf-8")
    return p


def parse_full_print(html: str) -> dict[str, Any]:
    """Extract title + all player rows from a print HTML.

    Returns:
        {
            "title": "...",
            "n_rows": int,
            "players": [{"rank":..., "name":..., "city":..., "state":...,
                         "section":..., "district":..., "points":...}, ...]
        }
    """
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body
    text = body.get_text("\n", strip=True) if body else ""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = None
    # Title detection: prefer line with parentheses (e.g., "*Boys 12 (Combined)"),
    # else first line containing Boys/Girls/Men/Women/Co-ed/Mixed + digit
    for line in lines[:30]:
        if "(" in line and ")" in line and 5 < len(line) < 120 and any(t in line for t in ("Boys", "Girls", "Men", "Women", "Mixed", "Co-ed", "STA")):
            title = line
            break
    if not title:
        for line in lines[:30]:
            if 5 < len(line) < 120 and any(t in line for t in ("Boys", "Girls", "Men", "Women", "Mixed", "Co-ed")) and any(ch.isdigit() for ch in line):
                # Skip nav crumbs
                if line in ("Home", "Tournaments", "TennisLink") or line.startswith(">"):
                    continue
                title = line
                break
    # Find the column-header row
    players = []
    i = 0
    while i < len(lines):
        if lines[i].lower() == "rank" and i + 1 < len(lines) and lines[i+1].lower() == "name":
            j = i
            while j < len(lines) and lines[j].lower() != "points":
                j += 1
            i = j + 1
            break
        i += 1
    while i + 6 < len(lines):
        if re.fullmatch(r"\d+", lines[i]) and "," in lines[i+1]:
            try:
                players.append({
                    "rank": int(lines[i]),
                    "name": lines[i+1],
                    "city": lines[i+2],
                    "state": lines[i+3],
                    "section": lines[i+4],
                    "district": lines[i+5],
                    "points": lines[i+6],
                })
            except (ValueError, IndexError):
                pass
            i += 7
        else:
            i += 1
    return {"title": title, "n_rows": len(players), "players": players}
