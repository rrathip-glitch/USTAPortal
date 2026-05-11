"""Classify every hit list into current vs stale by inspecting top-5 names.

If a list's top-5 contains current 2026 juniors (e.g., Quan Rudy as
top B12, Cooper Woestendick, Andres Martin as top B18) it's likely
CURRENT. If it contains pre-2021 era players (Brandon Nakashima,
Hurricane Tyra Black, Catherine Bellis, Caroline Dolehide, Brandon
Holt) it's STALE.

This is heuristic — not perfect, but enough to prioritize.
"""

from __future__ import annotations

import json
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _lib import OUT, parse_full_print

# Players known to be on CURRENT (2025-2026) junior boys lists
CURRENT_PROS_TO_BE = {
    "Quan, Rudy", "Razeghi, Alexander", "Woestendick, Cooper",
    "Exsted, Maxwell", "Belday, Rohan", "Muhala, Santiago",
    "Bigun, Kaylan", "Lee, Mitchell", "Sun, Adam", "Chunduru, Abhinav",
    # B14 era top
    "Dale, Andrew", "Kim, John", "Kim, Aidan", "Fishback, Ryan",
    "Heck, Hunter", "Woldeab, Siem", "Martin, Andres",
    # B16
    "Chopra, Keshav", "Brown, Nathan", "Cooper, George",
    # Girls
    "Ngounoue, Clervie", "Yu, Eleana", "Block, Natalie",
    "Perez, Natalia", "Subhash, Natasha", "Zamarripa, Maribella",
    "Briggs, Mischa",
}

# Players known to be on STALE pre-2021 junior boys lists (they're now ATP/WTA)
STALE_TOPS = {
    "Nakashima, Brandon", "Black, Hurricane Tyra", "Bellis, Catherine",
    "Dolehide, Caroline", "Loeb, Jamie", "Ouellet-Pizer, Chloe",
    "Andrews, Gabrielle", "Liu, Claire", "Letzt, Alexandra",
    "Spurbeck, Daniel", "Stofflet, Cole", "Stringfellow, Brandon",
    "Vallabhaneni, Niroop",
}


def classify(top_names: list[str]) -> tuple[str, list[str]]:
    """Return ('current'|'stale'|'unknown', signal_names)."""
    signals = []
    for n in top_names:
        if n in CURRENT_PROS_TO_BE:
            signals.append(f"CURRENT:{n}")
        if n in STALE_TOPS:
            signals.append(f"STALE:{n}")
    if any(s.startswith("CURRENT") for s in signals):
        return "current", signals
    if any(s.startswith("STALE") for s in signals):
        return "stale", signals
    return "unknown", signals


def main():
    # Load both rounds
    rounds = []
    for fname in ("objA_index.json", "objA2_index.json"):
        p = OUT / fname
        if p.exists():
            rounds.extend(json.load(p.open()))
    # Add manually-known
    rounds.append({"list_id": 2072448, "title": "*Boys 12 (Combined)", "n_rows": 1014, "top3": ["Quan, Rudy", "Razeghi, Alexander", "Woestendick, Cooper"]})
    rounds.append({"list_id": 1684711, "title": "Boys 14 Singles Seeding", "n_rows": 1156, "top3": ["Dale, Andrew"]})
    rounds.append({"list_id": 1752987, "title": "*STA Boys 16 Standings (Combined)", "n_rows": 1655, "top3": ["Chopra, Keshav"]})
    rounds.append({"list_id": 1241792, "title": "*Boys 12 (Combined)", "n_rows": 1299, "top3": ["Nakashima, Brandon"]})
    # Dedupe
    seen = {}
    for r in rounds:
        seen[r["list_id"]] = r
    rows = sorted(seen.values(), key=lambda d: d["list_id"])

    enriched = []
    for r in rows:
        # Look up the actual top-5 from saved HTML if available
        top5 = []
        for path in [
            OUT / f"tennislink-{r['list_id']}.html",
            Path("/home/user/USTAPortal/data/recon/2026-05-11-janav-browse") / f"tennislink-{r['list_id']}.html",
        ]:
            if path.exists():
                try:
                    parsed = parse_full_print(path.read_text(encoding="utf-8"))
                    top5 = [p["name"] for p in parsed["players"][:5]]
                    if not r.get("title"):
                        r["title"] = parsed.get("title")
                    r["n_rows"] = parsed.get("n_rows", r["n_rows"])
                    break
                except Exception:
                    continue
        if not top5:
            top5 = r.get("top3", [])
        klass, sigs = classify(top5)
        enriched.append({
            "list_id": r["list_id"],
            "title": r.get("title"),
            "n_rows": r.get("n_rows", 0),
            "top5": top5,
            "class": klass,
            "signals": sigs,
        })

    # Sort: current first, then by size desc
    enriched.sort(key=lambda d: (0 if d["class"] == "current" else (1 if d["class"] == "unknown" else 2), -d["n_rows"]))
    (OUT / "objA_classified.json").write_text(json.dumps(enriched, indent=2, ensure_ascii=False))

    print("\n=== CURRENT LISTS (top 50) ===")
    n_cur = sum(1 for d in enriched if d["class"] == "current")
    print(f"({n_cur} current total)")
    for d in enriched[:50]:
        if d["class"] != "current":
            break
        print(f"  {d['list_id']:8d} | n={d['n_rows']:5d} | {d['title']} | top1={d['top5'][0] if d['top5'] else ''}")
    print(f"\n=== UNKNOWN: {sum(1 for d in enriched if d['class'] == 'unknown')} ===")
    print(f"=== STALE: {sum(1 for d in enriched if d['class'] == 'stale')} ===")


if __name__ == "__main__":
    main()
