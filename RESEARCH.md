# RESEARCH.md — Prior Art for the USTA Tournament Intelligence Platform

## Executive summary

The single most consequential finding from this research is that `playtennis.usta.com` is not a hand-rolled USTA application — it is a white-labeled deployment of **Clubspark**, the same ITF-owned platform that hosts the LTA, Tennis Australia, and the official **World Tennis Number** site. The tournaments surface speaks **GraphQL** at `https://prod-us-kube.clubspark.io/usta/tournaments/api/graphql` (queries like `EventList` and `TournamentData` are documented in a community gist), and the WTN site exposes an officially-documented GraphQL API at `https://prd-itf-kube.clubspark.pro/tods-gw-api/graphql`. This means our scraper should target GraphQL, not HTML — and that the same Clubspark stack underpins WTN, so the WTN payload may already be embedded in tournament/player responses rather than requiring a separate site entirely.

A second consequential finding: there is essentially **no maintained open-source prior art** that scrapes `playtennis.usta.com` for personal-use intelligence. Older work (`tdierks/tennisscrape`, `reubenbauer`'s gist, `lineville/usta-cli`) targets the legacy `tennislink.usta.com` ASP.NET stack which has been substantially deprecated for tournament discovery. We are mostly on greenfield. Below I lay out what was found per axis and what to do with it.

## Axis 1: Existing USTA scrapers and tournament tools

The OSS landscape for USTA-specific scraping is sparse, dated, and mostly aimed at the old TennisLink ASP.NET site. Nobody appears to have published a serious open scraper for the modern Clubspark-backed `playtennis.usta.com`. The only project that has come close in spirit is **joseph-mcallister/tennis-data-aggregator**, which aggregates *junior* tennis data — but notably it routes around USTA entirely, scraping ITF, Tennis Recruiting, and UTR instead. That avoidance is itself a finding: the next-most-motivated developer in this space concluded it was easier to pull from third parties than to fight USTA. The general tennis-stats OSS community (Sackmann, infotennis, eyeseast/tennis-rankings) is overwhelmingly focused on pro tour data, not amateur/junior.

On TennisLink specifically, the surviving artifacts are mostly half-finished. `reubenbauer`'s 2016 gist gets as far as parsing dropdown forms but never finishes the row extraction. `tdierks/tennisscrape` has the raw POST-and-VIEWSTATE plumbing but no README and unclear maintenance status. `lineville/usta-cli` (C#, last release Nov 2023) does work for legacy NTRP rankings but does not touch WTN or the new playtennis surface. A newer JavaScript project, `usta_tennislink_players_scraping` by user `ahmad`, was updated August 2025 and a sibling project `usta-analytics` (Next.js + Postgres) hints at the same author building a small dashboard — but both are 1-star repos with minimal documentation, so they are signal of intent more than reusable code.

### Key findings

- **lineville/usta-cli** — C# CLI that scrapes NTRP rankings; latest release v2.1.2 (Nov 2023); no WTN, no junior tournament logic, ASP.NET-era target. https://github.com/lineville/usta-cli
- **tdierks/tennisscrape** — Python scraper hitting `tennislink.usta.com/Tournaments/TournamentHome/Tournament.aspx?T={}`; no README, abandoned-looking. https://github.com/tdierks/tennisscrape
- **reubenbauer 2016 gist** — Half-finished BeautifulSoup scraper of `tennislink.usta.com/Tournaments/Rankings/RankingHome.aspx`; useful as a reference for the legacy form-submit pattern, not as working code. https://gist.github.com/reubenbauer/b784796793423a3fe8afe2de5e36b289
- **joseph-mcallister/tennis-data-aggregator** — TypeScript/Puppeteer/Sequelize/Postgres "passion project" for *junior* tennis data; pulls ITF + Tennis Recruiting + UTR but explicitly *not* USTA — strong implicit signal that USTA was deemed not worth scraping directly. https://github.com/joseph-mcallister/tennis-data-aggregator
- **ahmad/usta_tennislink_players_scraping** + **usta-analytics** — JS scraper updated Aug 2025 plus a TypeScript analytics dashboard; tiny, not battle-tested, but proves we are not the only ones currently attempting this. https://github.com/topics/usta
- **BlakeStevenson USTA PlayTennis GraphQL gist** — Community-documented GraphQL queries (`EventList`, `TournamentData`) against `prod-us-kube.clubspark.io/usta/tournaments/api/graphql`. This is the single most useful piece of prior art for our project. https://gist.github.com/BlakeStevenson/8d58c6f370778715aba5c4f768cc3838
- **Tennis Australia / LTA / ITF stacks** — All three share the Clubspark vendor (https://clubspark.com/), so reverse-engineering work done in the LTA or ITF community is likely to translate to USTA. https://www.lta.org.uk/roles-and-venues/venues/club-management/clubspark/

## Axis 2: World Tennis Number

WTN is a Glicko-2-derived rating in active deployment by ITF since 2020-2021, on a 40 (beginner) to 1 (elite pro) scale. Two things matter for us. First, **singles and doubles are independently calculated and exposed as separate numbers** — confirmed by ITF FAQ — so our schema must always store them as a pair, never a single field. Second, every WTN comes with a **Confidence Level** derived from Glicko-2's rating deviation, which is functionally a `(point_estimate, deviation, confidence_indicator)` triple — we should persist all three, not just the headline number, otherwise we are throwing away exactly the signal that distinguishes a "stable 17.4" opponent from a "shaky maybe-17.4-could-be-12" opponent.

There **is** an officially-documented WTN GraphQL API at `https://prd-itf-kube.clubspark.pro/tods-gw-api/graphql`, but the docs site (docs.worldtennisnumber.com/api-docs) returned HTTP 403 to anonymous requests, and access "must be issued by USTA prior to accessing the API" per scraped notes — so practically it is not a public API for our purposes. No community project has documented WTN-at-scale extraction; this is a gap. The WTN data is, however, consistently displayed *inside* the player profile UI on `playtennis.usta.com` and on `worldtennisnumber.com`'s own player-search pages, both of which are Clubspark-rendered SPAs, meaning the data is reachable via authenticated browser session and the GraphQL responses underpinning those pages.

### Key findings

- **ITF World Tennis Number FAQ** — Confirms separate singles/doubles numbers and Glicko-2-style confidence. https://worldtennisnumber.com/eng/faq
- **WTN Confidence Level explainer** — Documents the rating-deviation interpretation we need to preserve in our schema. https://worldtennisnumber.com/eng/news/wtn-your-confidence-level-explained
- **WTN GraphQL API docs (gated)** — Confirms a GraphQL endpoint exists and where it lives, but documentation requires credentials USTA must issue. https://docs.worldtennisnumber.com/api-docs/
- **USTA WTN landing page** — Confirms WTN is the strategic ITF/USTA rating going forward, integrated into Serve Tennis (Clubspark). https://www.usta.com/en/home/play/itf-world-tennis-number.html
- **No community WTN scraper found** — Multiple targeted searches turned up zero open-source WTN extraction projects. This is itself the finding: we will be writing the de facto reference implementation.

## Axis 3: Tennis stat platforms (commercial and OSS)

Three reference points should shape our intelligence layer.

**Jeff Sackmann's Tennis Abstract universe** (`tennis_atp`, `tennis_wta`, `tennis_MatchChartingProject`, `tennis_pointbypoint`) is the de facto OSS standard for tennis match data formats. The Match Charting Project — running since 2013 with 5,000+ user-charted matches — defines a shorthand notation for shot-by-shot recording that is the closest thing tennis has to a standard "scoresheet" format. We should not reinvent: when we parse score strings or store match-level rows, we should adopt his column conventions (winner/loser columns, score string with tiebreak parens like `7-6(4)`, etc.). The Match Charting data is CC-BY-NC-SA which limits redistribution but not borrowing the schema.

**UTR's player card** is the canonical "what does a player profile dashboard look like?" reference for our use case. Worth borrowing: separate singles vs doubles ratings prominently on top, win/loss record, min/max rating over a window, "highest-rated opponent defeated", an explicit "Stats" tab with 6/12-month toggle, "results that count for rating" vs "all results" toggle. UTR uses up to 30 most-recent matches with 12-month decay; we should mirror that windowing for our trend visuals so the user reads ours the way they already read UTR.

**TennisViz / MatchStat / Tennis Explorer** all use the same head-to-head metaphor: direct H2H plus *common opponents* analysis (how have both players done against the same third party?), filterable by surface/event/round, with opponent-difficulty tags ("Tough / Even / Favorable") derived from rating differential. WTN even publishes its own H2H widget — borrow that exact framing because it is what users already expect. The "common opponents" pattern in particular is high-value for junior tennis where direct H2H samples are sparse but the local circuit has a lot of overlap.

### Key findings

- **JeffSackmann/tennis_MatchChartingProject** — De facto OSS standard for shot-by-shot tennis notation; CC-BY-NC-SA. Use as schema reference. https://github.com/JeffSackmann/tennis_MatchChartingProject
- **JeffSackmann/tennis_atp + tennis_wta** — CSV column conventions for match rows (score strings, winner/loser, surface, round). https://github.com/JeffSackmann/tennis_atp
- **UTR Advanced Player Metrics** — Reference for player-card layout, time-window toggles, and metric definitions worth mirroring. https://support.universaltennis.com/en/support/solutions/articles/9000173631-advanced-player-metrics-singles-and-doubles
- **WTN Head-to-Head Explained** — Reference for the H2H UI metaphor users already know from the rating they care about. https://worldtennisnumber.com/eng/news/wtn-head-to-head-explained
- **TennisViz Performance Portal** — Pro-grade scouting UI; useful as a visual reference (score-range filters, opponent difficulty tags). https://tennisviz.com/performance-portal/
- **MatchStat H2H** — Established consumer pattern for H2H surface/event filtering. https://matchstat.com/tennis/head-to-head/

## Axis 4: SPA reverse-engineering technique writeups

Because the target is a Clubspark GraphQL SPA, the right shape of the scraper is well-established and not in dispute. The dominant pattern in the community is the **Playwright-for-auth, raw-HTTP-for-bulk** hybrid: drive a real Chromium with Playwright through the login and 2FA dance, persist the resulting browser context with `context.storageState()` to a JSON file, and then either (a) replay those cookies into an `httpx`/`requests` session for fast bulk GraphQL fetches, or (b) keep the Playwright context alive and use `page.request` (which inherits cookies and runs through the real browser) when TLS/JA3 fingerprinting matters. The Playwright `storageState` pattern is documented officially for exactly this use case.

For discovering the actual GraphQL queries the site fires, the canonical workflow is: open Chrome DevTools → Network tab → filter to Fetch/XHR → walk through the UI flow (login, view tournament, open player profile) → right-click each request → "Copy as cURL" or "Replay XHR". For a more systematic capture there are two good tools: the **`api-reverse-engineer`** Chrome extension (records every fetch+XHR with JSON export) and **`mitmproxy2swagger`** (turns mitmproxy captures into an OpenAPI spec automatically). Either is appropriate — the extension is simpler for a one-time mapping; mitmproxy is appropriate if we expect to map the API repeatedly as it evolves.

On anti-bot: USTA itself does not appear to deploy heavy bot-detection on the playtennis surface — there is no evidence in the community of Akamai/PerimeterX/DataDome challenges for authenticated personal browsing. This is the expected posture for a participation-management platform (vs. ticketing or pro-sports stats). However, Clubspark/Cloudflare *infrastructure-level* protections likely sit in front, and they detect TLS fingerprints (JA3/JA4) of stock `httpx`/`requests` even when cookies are valid. The mitigation when this becomes a problem is `curl-cffi` (curl with browser-like TLS impersonation) as a drop-in for `httpx`. Plan for it; don't preemptively use it unless we hit a wall.

For schema-drift handling — which we will hit, because Clubspark ships changes — the right pattern is **Pydantic v2 with `AliasChoices`** for field-name resilience plus a simple snapshot/diff loop on the GraphQL `__schema` introspection (or on the JSON shape if introspection is disabled). The DEV.to writeups from `withatte` and `deepak_mishra` lay this out. We should record a schema hash with every scrape and alert when it changes.

### Key findings

- **Playwright Authentication / storageState docs** — Official pattern for persisting login state across runs. https://playwright.dev/docs/auth
- **Scrapecrow: Reverse Engineering The Web** — Best single overview of SPA reverse-engineering for personal scraping. https://scrapecrow.com/reverse-engineering-intro.html
- **api-reverse-engineer (Chrome extension)** — Records fetch+XHR with JSON export, ideal for mapping Clubspark's GraphQL endpoints. https://github.com/ctala/api-reverse-engineer
- **mitmproxy2swagger** — Auto-generates OpenAPI spec from captured traffic; useful if we want a versioned record of the API surface over time. https://0x1.gitlab.io/reverse-engineering/mitmproxy2swagger/
- **0xdevalias's anti-bot notes gist** — Comprehensive reference for Cloudflare/Akamai/DataDome bypass patterns; stash for the day a fingerprint check triggers. https://gist.github.com/0xdevalias/b34feb567bd50b37161293694066dd53
- **Stop Silent Scraper Failures (Pydantic v2 AliasChoices)** — Pattern for field-rename resilience. https://dev.to/withatte/stop-silent-scraper-failures-using-pydantic-for-instant-layout-change-detection-4p1k
- **Estuary on schema drift** — Ops-level framing for snapshot/diff/version of scraped schemas. https://estuary.dev/blog/schema-drift/

## Axis 5: ToS and ethical posture

USTA's Terms of Use explicitly prohibit "spam, algorithms, automated systems, software, scripts, viruses, worms, Trojan horses, devices, robots or data extraction mechanisms" as well as use "for any competitive purpose," with discretion to suspend or terminate violators' access at any time without notice. This is the standard boilerplate language and it is not selectively enforced against personal-use scraping at our scale, but the contractual prohibition is real and is what carries legal weight post-`hiQ v. LinkedIn`.

The relevant principle from **hiQ v. LinkedIn** is now well-settled: scraping *publicly available* data does not violate the CFAA (Ninth Circuit), but contractual prohibitions against scraping *can* be enforced via breach-of-contract and unfair-competition theories — and authenticated/logged-in scraping in particular is much more legally exposed than scraping anonymous public pages, because the court treated the "behind login" line as significant when it ruled against hiQ on the "turkers" portion of its conduct. Our project sits behind login (the user's own USTA credentials) and is therefore in the "contractually risky but not CFAA-criminal" zone, and the user is operating as themselves.

The ethically defensible posture for personal-use authenticated scraping — and the one our system should be designed around — is the **"a normal user clicking around could generate this"** test: the scraper authenticates as the actual end user, fetches data the user is themselves entitled to see, paces requests at human-realistic intervals, does not redistribute, does not commercially compete with USTA, and does not scrape data of users who have not consented (i.e., we only fetch player profiles that appear in draws the user is themselves entered in — not the entire USTA database). A single-user dashboard run on the user's own account, with conservative pacing and no redistribution, fits comfortably inside this envelope. We should still document this posture in the project README so the design intent is obvious.

### Key findings

- **USTA Terms of Use** — Contractually prohibits automated access; "competitive purpose" clause is the operational risk. https://www.usta.com/en/home/about-usta/who-we-are/national/usta-terms-of-use.html
- **hiQ v. LinkedIn (Wikipedia)** — Public/authenticated distinction; CFAA narrowed but contract claims survive. https://en.wikipedia.org/wiki/HiQ_Labs_v._LinkedIn
- **EFF on hiQ ruling** — Plain-language reading of the public-data principle. https://www.eff.org/deeplinks/2019/09/victory-ruling-hiq-v-linkedin-protects-scraping-public-data
- **Zwillgen post-settlement analysis** — Practical lessons-learned framing post-2022 settlement (hiQ enjoined, $500K, source-code destruction). https://www.zwillgen.com/alternative-data/hiq-v-linkedin-wrapped-up-web-scraping-lessons-learned/

## Synthesis

Five concrete recommendations for the SPEC, in priority order:

1. **Target Clubspark's GraphQL endpoint, not HTML.** The community-documented endpoint at `https://prod-us-kube.clubspark.io/usta/tournaments/api/graphql` (with queries like `EventList` and `TournamentData`) is our primary surface. Spec the scraper as a GraphQL client from day one, not as an HTML parser. Confirm/extend the query catalog by capturing the SPA's actual XHR traffic with the `api-reverse-engineer` Chrome extension during a real login session. The BlakeStevenson gist is the starting point.

2. **Treat WTN as a `(singles_value, singles_confidence, doubles_value, doubles_confidence, captured_at)` tuple in the schema, not as a scalar.** ITF documentation makes clear singles and doubles are independent and that confidence (Glicko-2 rating deviation) is the second-most-important field after the value itself. Our schema, our UI, and our trend charts should always carry the confidence band. Also: assume WTN is delivered embedded in the same Clubspark GraphQL responses as player/tournament data (since both surfaces share infrastructure), and only fall back to scraping `worldtennisnumber.com` separately if probing shows the field is missing from the playtennis payload.

3. **Adopt Jeff Sackmann's column conventions for matches and the UTR player-card layout for the dashboard.** For the database: winner/loser columns, score string with tiebreak parenthetical (`7-6(4)`), surface/round/event-tier fields. For the UI: separate singles/doubles cards on top, 6/12-month window toggle, "highest-rated opponent defeated" tile, plus a TennisViz/MatchStat-style head-to-head + common-opponents view with Tough/Even/Favorable opponent-difficulty tags. Don't reinvent these; users already read this format from UTR and WTN.

4. **Architect the scraper as Playwright-for-auth + httpx-for-bulk, with `storageState` persisted to disk, Pydantic v2 with `AliasChoices` modeling every response, and a schema hash recorded on every run.** Plan for `curl-cffi` as a fallback if/when raw `httpx` calls start getting Cloudflare-fingerprinted, but do not adopt it preemptively. This is the patterns-confirmed-by-community shape and there is no need to deviate.

5. **Codify the ethical posture in the README and in the rate-limiter.** Single user, the user's own account, only data the user is entitled to see (draws they are entered in), human-realistic pacing (no parallel fan-out across hundreds of players in a burst), no redistribution, no commercial use. This is what makes our project both ethically and legally defensible under the post-hiQ landscape, and it doubles as our anti-bot strategy: the cheapest way to avoid bot detection is to actually behave like a user.