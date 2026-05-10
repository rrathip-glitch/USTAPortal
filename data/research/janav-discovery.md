# Janav Thasen — open-web discovery
Captured: 2026-05-10
Egress: Claude Code (Anthropic-routed WebFetch + WebSearch)
Query budget used: 7 of 20

## Confirmed facts

Confidence: HIGH. These three facts appear consistently across two independent
public sources (Tennis Recruiting Network and CoreTennis), each retrieved via
WebSearch result snippets (direct WebFetch on TRN returned 403 — TRN appears
to gate logged-out clients; CoreTennis WebFetch succeeded).

- **Hometown:** Weston, FL. Source: tennisrecruiting.net player page 1065914
  (visible in WebSearch result snippet, retrieved 2026-05-10).
- **Class year / grade:** Class of 2032 — currently a 5th grader.
  Source: same TRN page snippet. This places him in the **Boys' 12s** age
  category (not Boys' 16s as the spec hypothesised), since 5th graders are
  typically 10-11 years old. CoreTennis independently corroborates: profile
  is filed under "12 & under, Boys".
- **USTA section:** Florida (inferred with HIGH confidence from Weston FL
  hometown + activity on USTA Florida-run tournaments + USTA section/state
  alignment for FL). Not directly stated on any source we could read.

## Probable facts (single source, plausible)

Confidence: MEDIUM. One source each; no independent corroboration.

- **TRN national ranking:** ~146th nationally in his class (Boys 2032).
  Source: TRN snippet retrieved 2026-05-10. Snapshot date unknown — TRN
  rankings update weekly so this is a 2026-05-ish value.
- **TRN year W-L record:** 31 wins, 36 losses (~46% win rate). Source: TRN
  snippet retrieved 2026-05-10. Window appears to be "past year".
- **2026 tournament activity (CoreTennis):** Played at least one USTA
  National Level 3 tournament in Wesley Chapel, FL on 2026-01-17, reaching
  Round of 32 (1/32) with a 1-0 record at the event. Source: coretennis.net
  profile id 203938, fetched 2026-05-10 (direct WebFetch succeeded).
- **UTR profile exists:** UTR Sports profile id 3059480 for Janav Thasen.
  Source: WebSearch result link. Rating values not extractable — UTR Sports
  requires JS to render the rating and WebFetch returned an empty page body.
  Direct fetch needs auth or a real browser.

## Tritennis0 tournament series — what we know

Confidence: MEDIUM-HIGH for series identity; LOW for Janav's participation.

- **TriTennis** is the tournament organizer behind the `tritennis0` URL
  prefix on playtennis.usta.com (the URL pattern shown in our example draw
  URL in the project). Based in Delray Beach, FL per Google snippet for
  `playtennis.usta.com/tritennis0`.
- **Confirmed TriTennis tournaments** discovered via search:
  - "Level 6: Broward Turkey Bowl Singles Classic" — GUID
    `3C76B712-C29A-47F0-A06E-D49452D5AC32`, event GUID
    `61B9B268-467C-47CC-B60D-5A3D381AED22`. Held annually around US
    Thanksgiving (late November). Direct fetch of the event page returned
    Cloudflare 403, consistent with RECON.md findings.
  - "TriTennis Turkey Bowl National Open" — TennisLink tournament ID 193920.
    Listed as Level 7, Tennis Recruiting Showcase Series, with Boys'/Girls'
    18/16/14/12 singles divisions.
  - "Level 5 Open: Broward Prize Money Open & NTRP Classic" — GUID
    `9E6D70E5-4AD8-4584-ADD1-ACC8B5E3DBAB`. January event at Tennis Center
    of Coral Springs.
- **Format and audience:** Tennis Recruiting Network Showcase Series Level
  7 events with Boys'/Girls' 18, 16, 14, 12 singles divisions; entry open
  to all USTA members; players manually selected by the tournament director
  after registration close.
- **Likely venue:** Tennis Center of Coral Springs, 2575 Sportplex Drive,
  Coral Springs, FL 33065 (Broward County). Boys 12s and Girls 12s on clay
  courts per the USTA Florida youth tennis page.
- **Janav's participation in TriTennis events:** NOT directly confirmed by
  any source we could read. Cloudflare blocks the actual draw pages where
  this would be verifiable. The example draw URL the project starts from
  has the `tritennis0` prefix, which is the project's working assumption
  that Janav plays in this series. Treat as a working hypothesis, not a
  confirmed fact, until residential-egress recon can fetch the draws.

## TennisLink ID

TennisLink ID: **unknown** — none of our searches surfaced an exact USTA
TennisLink player ID (the legacy 7-digit number, distinct from the GUID
used on playtennis.usta.com). TRN ID is `1065914`; CoreTennis ID is
`203938`; UTR Sports ID is `3059480`. None of these are TennisLink/USTA
identifiers. Residential-egress recon on playtennis.usta.com or
tennislink.usta.com is required to recover the canonical USTA GUID.

## Searches that came back empty

- `"Janav Thasen" UTR rating` — found the UTR Sports profile URL but no
  numeric rating in any snippet.
- `"TriTennis" Coral Springs junior boys 12 tournament 2026` — surfaced
  general TriTennis info but no junior Boys 12s event Janav was entered in.
- `"Janav Thasen" Weston Florida tennis ranking` — same TRN/CoreTennis
  pages, no new data.

WebFetch returned 403 on:
- tennisrecruiting.net (consistent with TRN's logged-out gate)
- playtennis.usta.com TriTennis pages (consistent with Cloudflare block
  documented in RECON.md / DECISIONS.md ADR-001)
- UTR profile (rendered client-side; WebFetch saw empty body)

These 403s are themselves data: they corroborate the recon finding that
the playtennis.usta.com data plane is unreachable from this egress IP.

## Sources

- [Tennis Recruiting Network — Janav Thasen player 1065914](https://www.tennisrecruiting.net/player.asp?id=1065914) (snippet only; WebFetch 403)
- [CoreTennis — Janav Thasen profile 203938](https://www.coretennis.net/tennis-player/janav-thasen/203938/profile.html) (WebFetch succeeded)
- [UTR Sports — Janav Thasen profile 3059480](https://app.utrsports.net/profiles/3059480) (snippet only; WebFetch empty)
- [TriTennis tournaments index](https://playtennis.usta.com/tritennis0/Tournaments) (WebFetch 403)
- [TriTennis Broward Turkey Bowl Singles Classic — Level 6](https://playtennis.usta.com/tritennis0/Tournaments/eventDetails/3C76B712-C29A-47F0-A06E-D49452D5AC32/61B9B268-467C-47CC-B60D-5A3D381AED22) (WebFetch 403)
- [TriTennis Turkey Bowl National Open — TennisLink T=193920](https://tennislink.usta.com/tournaments/tournamenthome/tournament.aspx?T=193920) (snippet only)
- [TriTennis Broward Prize Money Open & NTRP Classic — Level 5](https://playtennis.usta.com/tritennis0/Tournaments/overview/9E6D70E5-4AD8-4584-ADD1-ACC8B5E3DBAB) (snippet only)
- [USTA Florida junior tennis tournaments](https://www.ustaflorida.com/youth-tennis/junior-tournaments/) (referenced)
