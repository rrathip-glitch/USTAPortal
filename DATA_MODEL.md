# DATA_MODEL.md — canonical entity definitions

This file is the single source of truth for what entities the system knows about and how they relate. The Pydantic models in `src/models/` and the SQLite schema in `src/store/db.py` mirror these definitions. When they drift, this doc is canonical and the code is wrong.

The model is intentionally conservative — only fields we are certain we need or expect from recon. Fields land here as recon confirms them.

## Primary entities

### Player

A USTA-registered tennis player. The user is one Player; every opponent in every draw the user enters is also a Player.

- `usta_id` — primary key. Conjectured to be a GUID based on the example URL pattern; recon to confirm. Never null. If the USTA exposes both a numeric ID and a GUID, we prefer the GUID.
- `full_name`, `first_name`, `last_name` — strings; full_name is required, the splits are best-effort.
- `gender` — `M | F | X`.
- `section`, `district` — USTA geographic taxonomy (Southern, Florida, etc.). Nullable until recon confirms exposure.
- `age_category` — text label like "Boys' 16s" or "Adult Open"; recon will tell us if a player has one canonical age category or a list (a junior may compete in multiple).
- `profile_url` — durable URL on playtennis.usta.com; useful for "open in USTA" links.
- `last_fetched_at` — staleness tracker; the UI shows a freshness badge.

### Tournament

A USTA-sanctioned competition. Has many Draws.

- `usta_id` — GUID.
- `name`, `level`, `sanction_body`.
- `start_date`, `end_date`, `entry_deadline`.
- `location_city`, `location_state`.
- `surface` — hard / clay / grass / indoor_hard / carpet / unknown.
- `ball` — text (manufacturer + model); useful for opponents who play differently on different balls.
- `status` — upcoming / in_progress / completed / cancelled.

### Draw

One bracket within a Tournament. A Tournament typically has multiple Draws (Boys 16s singles, Boys 16s doubles, Boys 18s singles, etc.).

- `usta_id` — GUID. The example URL `Tournaments/draws/<GUID>` suggests this GUID is the Draw ID, not the Tournament ID; recon confirms.
- `tournament_id` — FK.
- `format` — single_elimination / single_elimination_with_consolation / round_robin / compass / feed_in / unknown.
- `size`, `gender`, `age_group`, `division`, `status`.

### DrawEntry

A Player's appearance in a Draw. Composite primary key of (draw_id, player_id).

- `seed` — nullable integer; the seeded line number when seeded.
- `position` — 1-indexed line in the draw, used to reconstruct the bracket layout.
- `status` — entered / withdrawn / walkover_in / alternate / unknown. We never hard-delete withdrawn entries; they're informational.

### Match

One match in a Draw.

- `usta_id` — GUID, when USTA assigns one. Some matches (especially future-round projections) may not have an ID until they're scheduled.
- `draw_id` — FK.
- `round` — short label (R32, QF, SF, F).
- `scheduled_at`, `court`.
- `player_a_id`, `player_b_id` — order is the USTA-reported draw order, not "winner first".
- `score_raw` — verbatim USTA score string. Always preserved.
- `sets` — parsed `SetScore[]`; if parsing fails we keep `score_raw` and leave sets empty rather than guess.
- `outcome` — completed / retired / walkover / default / unfinished / unknown.
- `winner_id` — nullable until match completes.

## Snapshot entities

These are append-only — every observation is a new row, so we can plot trajectories.

### RankingSnapshot

- `(player_id, category, scope, as_of)` composite PK.
- `category` — e.g., "Boys 16 Singles".
- `scope` — national / sectional / district.
- `position`, `points` — both nullable; some categories show one but not the other.
- `as_of` — the date USTA stamped the ranking, not the date we fetched.

### WTNSnapshot

- `(player_id, type, as_of)` composite PK.
- `type` — singles / doubles. Singles and doubles are independent ratings.
- `value` — float, scale 1.0 (strongest) to 40.0 (weakest).
- `confidence` — 0-1; recon to confirm field name and scale. If WTN exposes a "rating reliability" indicator, that goes here.
- `as_of` — the date stamped on the WTN datum.

**Demo-dataset note.** `scripts/seed_dev_data.py` emits WTN values for the dev player and opponents so the UI is demoable today. Those values are **synthetic placeholders pending residential recon of `worldtennisnumber.com`** — the host is Cloudflare-blocked from every datacenter egress this project has access to, so real WTN payloads have not yet been captured. Once Q-011 resolves and a live capture lands, the seeder is updated to reflect realistic ranges, and any code paths that key off WTN should not assume the demo values match production scales.

## Derived entities

These are computed on the fly from primary/snapshot entities. They are not persisted unless caching is required for performance (it isn't, at v1's data volume).

### HeadToHead

Inputs: `(player_a, player_b)`. Output: list of matches both played each other, aggregate record, last match summary, per-surface split.

**Walkover / default handling.** Matches with `outcome` of `walkover` or `default` are included in the returned `match_list` (they're part of the two players' history) but only contribute to the win/loss aggregate **when `winner_id` is set on the match**. A walkover or default that USTA recorded without a definitive winner appears in the list for completeness but does not move the aggregate record either way. Retirements always have a winner (per the score parser's invariants in `src/parse/matches.py`) and always count.

### FormWindow

Inputs: `(player, window_size_or_dates)`. Output: list of matches in window, win-loss, quality-adjusted score (opponent rating × win/loss).

### StrengthOfDraw

Inputs: `(draw, player_seed_or_position)`. Output: average opponent rating, hardest projected opponent on path to final, easiest path. Uses WTN as the rating axis where available, sectional ranking as fallback.

### ExpectedOutcome

Inputs: `(player_a_id, player_b_id, ratings, model_version="elo-wtn-1")`. Output: probability per side, echoed ratings, model version, confidence label. v1 uses a transparent Elo-style derivation from WTN; no ML.

**Algorithm (model_version="elo-wtn-1").** WTN is on a 1.0-40.0 scale where lower is stronger; Elo expects the opposite, so each rating is transformed via `elo(r) = (40.0 - r) * 50.0` (top-of-scale WTN 1.0 → Elo 1950, bottom WTN 40.0 → Elo 0). Win probability is the classical logistic `p_a = 1 / (1 + 10**((elo_b - elo_a) / 400))`. The 50.0 scale factor is a project constant — chosen as the smallest round number that yields probability_a > 0.7 at a 12-WTN gap, which is the "noticeably-stronger-than-club-level" threshold the unit tests pin.

**Confidence labelling.** Returned alongside the probability:
- `"high"` — both ratings are present (and, when an optional `confidences` dict is supplied, both snapshot confidences are >= 0.7).
- `"medium"` — both ratings are present but at least one snapshot's confidence is below 0.7, or the rating is a ranking-derived synthetic value rather than a real WTN snapshot. Only emitted when `confidences` is supplied to the function.
- `"low"` — exactly one rating is present. The probability falls back to 0.5 ("no signal").
- `"none"` — neither rating is present. Probability is 0.5.

**No-signal handling.** A missing rating on either side short-circuits to `probability_a = probability_b = 0.5` rather than imputing a default, matching the §"No silent imputation" normalization rule. The UI hides the probability bar entirely when confidence is `"none"` or `"low"`.

**Out-of-range ratings.** A rating outside the documented [1.0, 40.0] WTN range (negative, or > 40 — typically a misconfigured caller passing a raw Elo by mistake) logs a warning and is clamped to `[0.1, 40.0]` for the transform so the math stays finite. The original rating is echoed back unmodified in `rating_a` / `rating_b` so callers can see the input that triggered the clamp.

**Same-player guard.** `player_a_id == player_b_id` raises `ValueError`. A self-match has no scouting meaning and is never a valid input.

## Normalization rules

- **USTA ID is the universal join key.** Names collide; IDs don't. Two players with identical names in different sections are two different `usta_id`s and we never merge.
- **Soft delete only.** A withdrawn DrawEntry stays in the table with `status='withdrawn'`. The UI hides them by default but they exist for history.
- **Raw cache is canonical truth.** Every successful fetch writes `data/raw/<endpoint>/<sha256(request_signature)>.json` (or `.html`). Parsers read from cache, not from the wire, in normal operation. If the database is wiped, we re-parse from `data/raw/` and reconstruct every snapshot.
- **Timestamps in UTC.** ISO-8601 with `Z` suffix, stored as TEXT in SQLite (we don't trust SQLite's timezone handling on TIMESTAMP columns).
- **Strings are NFC-normalized.** Names with accents, hyphens, or apostrophes pass through `unicodedata.normalize("NFC", s)` on write.
- **No silent imputation.** If a field isn't in the response, it's null in our model — never zero, never empty string masquerading as missing.

## Open data-model questions

Tracked in QUESTIONS.md and resolved here as recon answers them. Initial set:

- Whether doubles WTN is in the same payload as singles WTN (research suggests yes, since the underlying Clubspark/GraphQL surface seems unified).
- Whether USTA exposes a stable "tournament series" concept for ranking points, or whether series membership must be inferred.
- Whether "section" is reliably present on every player profile or only on profiles whose owner has set a region.
- The exact identifier format for matches in the Clubspark GraphQL response (GUID? composite of draw + round + line?).
