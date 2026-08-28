# Fantasy Draft Assistant — Requirements

**Owner:** Blair
**Target:** Local Python + Streamlit app, run on draft day (~mid-September 2026)
**Purpose:** During a live 10-team PPR snake draft, recommend the top 3 picks that maximize the projected points of my final starting lineup, accounting for analyst disagreement and for what my opponents are likely to do before my next turn.

---

## 1. League configuration

These are hard values. Put them in `config.py` so they can be changed, but these are the defaults.

| Setting | Value |
|---|---|
| Teams | 10 |
| Rounds | 16 (160 total picks) |
| Draft type | Snake |
| My draft slot | **Unknown until draft day — must be a setting, selectable 1–10 at launch** |
| Keepers | None |
| Roster size | 16 (9 starters + 7 bench) |
| Starting lineup | 1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX (RB/WR/TE), 1 D/ST, 1 K |
| Scoring | ESPN standard PPR (full detail in §4) |

### Snake pick math

For slot `s` (1-indexed) in a 10-team league, round `r`:

```
odd round:   pick = (r - 1) * 10 + s
even round:  pick = (r - 1) * 10 + (11 - s)
```

Example, slot 3: picks 3, 18, 23, 38, 43, 58, 63, 78, 83, 98, 103, 118, 123, 138, 143, 158.

The gap between consecutive picks alternates (15 picks, then 5 picks, at slot 3). **The recommendation engine must use the real gap, not an average** — the whole point of the app is knowing who survives to the next turn.

---

## 2. Scope

### In scope (v1)
- Load analyst projections + rankings from local snapshot files
- Compute consensus value and analyst disagreement per player
- Manual click-off draft board tracking all 160 picks
- Monte Carlo simulation of the remaining draft
- Top-3 pick recommendation with plain-English reasoning
- 3 seasons of historical scoring per player with game-level drill-down
- Draft state auto-save / crash recovery

### Out of scope (v1) — do not build these
- Live ESPN API sync (manual board only)
- Bye-week optimization
- Injury status / news feeds
- Handcuff or stack logic
- Auction drafts, dynasty, keeper leagues
- Multi-user / hosted deployment

---

## 3. Data sources

**Acquisition model: snapshot files.** Everything is downloaded/exported once before draft day into `data/raw/` and committed. The app reads local files at launch. **No network calls are required for the app to run.** This is a hard requirement — draft day cannot depend on a scraper working.

### 3.1 Analyst projections & rankings

**The panel is defined in `config/analyst_panel.csv`, not in code.** The app reads that file at launch. Editing the CSV changes the panel — no code changes, no redeploy. See §3.5 for the refresh procedure.

Panel members are drawn from FantasyPros' **2025 draft (preseason) accuracy** leaderboard — *not* the in-season weekly accuracy leaderboard, which ranks a completely different set of people. Draft accuracy is what predicts draft-day rankings quality; in-season accuracy predicts start/sit advice. Using the wrong one is a real and easy mistake.

### Per-position inclusion — important

Overall accuracy rank hides blind spots. Seth Miller finished **#1 overall** for 2025 but ranked **187th of 213 at TE**. Feeding his TE opinion into a consensus would actively damage the exact calculation this app depends on — the TE cliff.

So the panel is filtered **per position**. `analyst_panel.csv` carries `use_qb`, `use_rb`, `use_wr`, `use_te`, `use_k`, `use_dst` flags, set to 1 when that expert's 2025 positional accuracy rank was ≤ 60. Each position's consensus and standard deviation are computed only from experts flagged for that position.

Current panel counts under that rule: QB 15 · RB 20 · WR 19 · TE 13 · K 12 · D/ST 7.

The most **balanced** analysts — strong at RB, WR, and TE with no blind spot — are the backbone of the panel:

| Overall | Expert | Site | QB | RB | WR | TE |
|---|---|---|---|---|---|---|
| 9 | Jody Smith | Draft Sharks | 66 | 19 | 21 | 23 |
| 6 | Joey Wright | Footballguys | 74 | 4 | 61 | 25 |
| 5 | Marc Shannep | Fantasy Knockout | 19 | 54 | 4 | 39 |
| 28 | Kyle Krajewski | First Seed Sports | 129 | 23 | 65 | 27 |
| 27 | Lee Wehry | FantasyPros | 126 | 35 | 77 | **8** |
| 26 | Kev Wheeler | Wheel Route FF | 91 | 44 | 35 | 50 |
| 8 | Kevin Steele | The Fantasy Authority | 33 | 10 | 45 | 78 |
| 16 | Justin Weigal | Fantasy Sharks | 77 | 26 | 39 | 67 |

(Numbers are 2025 positional accuracy ranks out of ~213 analysts. Lower is better.)

**Caveat to record in the UI:** FantasyPros scores draft accuracy using **half-PPR**, and excludes K and D/ST from the overall ranking. Our league is full PPR, so the leaderboard is a good proxy but not a perfect one — it modestly under-weights reception volume.

**Fallback if per-expert rankings aren't individually exportable:** FantasyPros' consensus rankings pages already publish `Best`, `Worst`, `Avg`, and `Std Dev` columns per player across their full expert panel. Those four columns satisfy the entire disagreement requirement with one file. Use per-expert files if obtainable; otherwise use the consensus file's spread columns and set `panel_mode = "consensus_fallback"` in config, which must display a badge in the UI so I know which mode I'm in.

**Also needed:** a points-projection source (ranks alone can't produce a lineup total). FantasyPros projections pages and FFToday both publish projected stat lines. At minimum we need projected PPR points per player.

### 3.2 Opponent behavior model
ESPN's own player rankings / ADP — correct source because the league auto-drafts off ESPN's board. Export to `data/raw/espn_adp.csv`.

### 3.3 Historical scoring
Use **`nflreadpy`** (the maintained Python port of nflreadr; `nfl_data_py` is the older package).

```python
import nflreadpy as nfl
weekly = nfl.load_player_stats(seasons=[2023, 2024, 2025])  # returns Polars
ids    = nfl.load_ff_playerids()                            # cross-platform ID map
```

Cache both to `data/cache/*.parquet` on first run so the app never needs the network again.

**Important:** compute PPR points ourselves from the raw stat lines using §4 rules. Do not use any source's precomputed fantasy points — they won't match our exact scoring.

### 3.5 Refreshing data before draft day

Rankings and projections will change between now and the draft — injuries, holdouts, depth-chart news, preseason performance. The app must make refreshing trivial and must never leave me guessing which vintage of data I'm looking at.

**Requirements:**

1. **Dated snapshot folders.** Raw files live in `data/raw/YYYY-MM-DD/`. A `config/active_snapshot` file (or a `--snapshot` flag) selects which one the app loads. Default: the most recent folder.
2. **Manifest per snapshot.** Each folder gets `manifest.json` recording the capture date, source URLs, file checksums, and row counts. The app displays "Data as of `<date>`" prominently in the UI header. If the active snapshot is more than 7 days old, show a warning banner.
3. **Panel edits require no code changes.** `config/analyst_panel.csv` is the single source of truth for who is in the panel and at which positions. Adding, removing, or re-weighting an expert = edit the CSV, relaunch. The app must validate the file on load and fail loudly with a readable message if a column is missing, a `rankings_file` doesn't exist, or a position ends up with fewer than 3 contributing experts.
4. **`weight` column is honored.** Default 1.0 for everyone. If I want to trust one analyst more, I set 1.5 and the consensus becomes a weighted mean, with the standard deviation weighted to match.
5. **A `refresh.py` script** that re-downloads what can be re-downloaded, writes a new dated folder, and prints a diff summary versus the previous snapshot: players whose consensus rank moved more than 10 spots, new entrants to the top 200, and anyone who disappeared. Big movers are exactly what I want to see before draft day.
6. **Never overwrite a snapshot in place.** Old folders stay. If a refresh produces something broken, I roll back by changing one line.
7. **Re-running a refresh must not require the app to be rebuilt or the state file to be discarded.**

Acceptance: I can add a new analyst to the panel, run `refresh.py`, relaunch, and see the new consensus and spread reflected — without touching a `.py` file.

---

## 4. Scoring engine

Implement as a pure function: `stat_line -> points`. This is used for historical points AND for converting projected stat lines into projected points, so both are consistent.

**Passing:** 0.04 pts/yd · TD 4 · INT −2 · 2PC 2
**Rushing/Receiving:** reception 1.0 · 0.1 pts/yd · TD 6 · 2PC 2 · fumble lost −2
**Kicking:** PAT 1 · FG 0–39 = 3 · FG 40–49 = 4 · FG 50+ = 5 · misses 0
**D/ST:** sack 1 · INT 2 · fumble rec 2 · safety 2 · blocked kick 2 · TD 6
**D/ST points allowed:** 0 → 5 · 1–6 → 4 · 7–13 → 3 · 14–17 → 1 · 18–27 → 0 · 28–34 → −1 · 35+ → −3

Unit-test this function against 5–10 hand-calculated stat lines before anything else is built.

---

## 5. Player identity resolution

The highest-risk plumbing in the project. "Marvin Harrison Jr." vs "Marvin Harrison Jr" vs "M. Harrison" will silently corrupt the variance math by splitting one player into two rows.

Requirements:
- Use `nfl.load_ff_playerids()` as the canonical crosswalk (it carries ESPN, Sleeper, FantasyPros, and other platform IDs)
- Normalize: lowercase, strip punctuation and suffixes (Jr/Sr/II/III), collapse whitespace
- Match on `(normalized_name, position, team)`, fall back to fuzzy match with a similarity threshold
- **Every unmatched player must be reported, not silently dropped.** Write `data/unmatched.csv` and show a warning banner in the UI with the count
- Support `data/manual_id_overrides.csv` (`source_name, canonical_id`) for hand-fixing stragglers
- Acceptance: after loading all sources, unmatched players in the top 200 by consensus rank must be **zero**

---

## 6. Core player metrics

Per player, compute:

| Field | Definition |
|---|---|
| `proj_points` | Consensus projected PPR points for the season |
| `consensus_rank` | Average rank across the analyst panel |
| `rank_sd` | Standard deviation of ranks across the panel — the disagreement measure |
| `rank_best` / `rank_worst` | Range across the panel |
| `points_sd` | Projected-points standard deviation. If only ranks are available, derive it by mapping the rank range onto the points curve at that position |
| `espn_adp` | ESPN rank/ADP, used only for the opponent model |
| `hist_3yr` | Total PPR points and points-per-game for 2023, 2024, 2025 |

Your example — a player at 1,3,2,2,3 vs one at 1,8,2,2,3 — is exactly `rank_sd`. Both have similar averages; the second has a much wider spread and should be treated as riskier.

---

## 7. Opponent model (Monte Carlo)

Each simulated draft:

1. Perturb the board once per simulation: `adp_sim[i] = espn_adp[i] + N(0, sigma)`, sigma ≈ 8 picks. Perturbing once per sim (not once per pick) models "this year's board leans a particular way," which is more realistic than independent per-pick noise.
2. Each opponent pick takes the lowest `adp_sim` player still available, subject to roster sanity caps: max 2 QB, max 2 TE, max 1 K, max 1 D/ST, max 16 total; no K or D/ST before round 13.
3. Opponents do not model need beyond those caps. Keep it simple — the caps prevent the obviously-wrong outcomes and nothing else is worth the complexity.

Sigma must be a tunable setting. A `sigma = 0` mode (strict ESPN order) is required as a debugging and comparison view.

---

## 8. Recommendation engine — full roster simulation

This is the heart of the app. It answers the literal question: *which available player leads to the best final starting lineup?*

```
def recommend(board, my_roster, my_remaining_picks, n_sims=500, k=10, risk_pct=50):
    candidates = top_k_available(board, k)          # by consensus value, positionally diverse
    results = {}
    for c in candidates:
        outcomes = []
        for _ in range(n_sims):
            proj  = draw_projections(board)          # N(proj_points, points_sd) per player
            adp_s = perturb_adp(board)               # §7 step 1
            avail = board - {c}
            roster = my_roster + [c]
            for pick_no in remaining_picks_in_order:
                if pick_no in my_remaining_picks:
                    p = greedy_my_pick(avail, roster, proj)   # §8.1
                else:
                    p = opponent_pick(avail, adp_s)           # §7 step 2
                avail.remove(p)
                if mine: roster.append(p)
            outcomes.append(optimal_starting_lineup_points(roster, proj))   # §8.2
        results[c] = percentile(outcomes, risk_pct)
    return sorted(results, reverse=True)[:3]
```

The TE-cliff scenario you described falls out of this automatically. No hand-coded scarcity rules — if taking a TE now produces better final rosters across 500 simulated futures, it ranks first.

### 8.1 Future-me policy
Simulated future-me picks greedily: highest projected points among players that can still fill an unfilled starting slot; once starters are filled, best available at RB/WR/TE. Deliberately simple and self-consistent — do **not** make this recursive.

### 8.2 Lineup optimizer
Given 16 players and their simulated point totals, fill 1 QB / 2 RB / 2 WR / 1 TE / 1 FLEX / 1 D/ST / 1 K to maximize total. Greedy by position then best remaining RB/WR/TE into FLEX is provably optimal for this slot structure — no solver needed.

### 8.3 Risk dial
The variance slider operates on the **team outcome distribution**, not on individual players:

- **Safe (30th percentile):** optimize the floor
- **Balanced (50th):** optimize the median — default
- **Upside (70th):** optimize the ceiling

Rationale: a boom/bust WR4 barely moves your team; a boom/bust RB1 moves it a lot. Applying risk at the team level captures that; a per-player penalty does not.

### 8.4 Also display
- **Availability odds:** for each candidate and each position, P(a player of this tier survives to my next pick), straight from the simulations
- **Separation:** my projected starting lineup total vs the average simulated opponent's

---

## 9. Performance requirements

- **Recommendation must return in under 3 seconds.** Non-negotiable — there is a draft clock.
- Represent the player pool as **NumPy arrays indexed by integer player ID**. No pandas or Polars operations inside the simulation loop. This is the single most common way this kind of code ends up 100× too slow.
- Precompute everything possible at load: position masks, sorted ADP order, projection arrays
- Vectorize across simulations where possible (run all `n_sims` for a candidate as array operations rather than a Python loop)
- If it can't hit 3 seconds, reduce `n_sims` to 250 and expose it as a setting rather than accepting slow

---

## 10. UI (Streamlit)

Single main screen, optimized for reading fast under a clock.

### Top: recommendation cards (3, side by side)
Each shows: player name, position, team · recommendation score · availability odds at my next pick · **one sentence of plain-English reasoning**, e.g.
> "TE cliff — 88% chance no top-3 TE survives to pick 38, and the gap to TE7 is 41 points."

### Middle: draft board
- Search box + position filters
- Click a player to mark drafted; a dropdown assigns which team took him (defaults to whoever is on the clock)
- Current pick number, round, whose turn, and picks until my next turn always visible
- **Undo last pick** button — mis-clicks will happen
- My roster panel showing filled and unfilled starting slots

### Bottom / expandable: player detail
- 2023 / 2024 / 2025 total PPR points and points per game
- Game-by-game log for any selected season, as a table and a bar chart
- Consistency: % of games ≥ 20 pts (boom) and ≤ 5 pts (bust), games missed
- Analyst detail: each analyst's rank, plus best/worst/avg/std dev

### Sidebar: settings
Draft slot (1–10) · risk dial (Safe / Balanced / Upside) · sigma · n_sims · engine toggle (Simulation vs VONA, see §11)

### Persistence
Write full draft state to `state/draft_YYYYMMDD.json` after **every** pick. On launch, offer to resume if a state file exists. If the app crashes at pick 90, nothing is lost.

---

## 11. Build phases

Build in this order. Each phase must be working and committed before the next starts.

**Phase 0 — Foundation**
Scoring function + unit tests · data loaders · player ID resolution · `data/unmatched.csv` clean for top 200
*Accept:* scoring tests pass; zero unmatched in top 200

**Phase 1 — Static board**
Streamlit UI, player table with consensus value and spread, click-off tracking, undo, state save/resume, my-roster panel
*Accept:* can manually run a full 160-pick mock draft without the app breaking

**Phase 2 — VONA engine (the safety net)**
Simple recommendation: best available now vs best likely available at my next pick, per position
*Accept:* returns sane top 3 instantly; **this is the guaranteed-working draft-day fallback**

**Phase 3 — Simulation engine**
Monte Carlo opponent model, full roster simulation, risk dial, availability odds, reasoning strings
*Accept:* meets the 3-second budget; toggle lets me compare against VONA

**Phase 4 — History drill-down**
3-year totals, game logs, consistency metrics, charts

**Phase 5 — Polish**
Reasoning wording, layout under time pressure, dry-run mock draft

If time runs short, **ship through Phase 2 and stop.** A working simple app beats a half-finished clever one on draft day.

---

## 12. Testing & verification

- **Scoring unit tests** — hand-calculated stat lines, including D/ST tiers and FG distance bands
- **Snake pick math test** — assert slot 3 yields picks [3, 18, 23, 38, ...] and slot 10 yields [10, 11, 30, 31, ...]
- **Lineup optimizer test** — hand-built roster with a known optimal lineup
- **The TE-cliff scenario test** — construct a synthetic board with 2 elite TEs, a steep TE dropoff, and 12 near-identical RBs. Assert the engine recommends a TE. *This is the behavior the whole app exists for; it deserves a test.*
- **Determinism** — fixed random seed produces identical recommendations, so results are debuggable
- **Sanity check** — with `sigma = 0`, opponent picks must exactly reproduce ESPN order
- **Cross-check** — run Phase 2 and Phase 3 engines side by side on a mock draft. Large disagreements mean a bug in one of them; investigate before draft day
- **Full dry run** — complete a mock draft end to end at least 3 days before the real one

---

## 13. Known risks

| Risk | Mitigation |
|---|---|
| ADP model is wrong → confidently wrong recommendations | Sigma is tunable; show availability odds so I can apply judgment |
| Simulation too slow under the clock | Phase 2 VONA fallback always available; `n_sims` adjustable |
| Name matching silently splits players | Unmatched report + manual override file + zero-unmatched acceptance test |
| Projections themselves are noisy | Risk dial; disagreement shown, not hidden |
| Mis-click during live draft | Undo button + per-pick state save |
| Source site changes format before draft day | Snapshot files are frozen locally; no live dependency |

---

## 14. Open items

1. Confirm whether per-expert rankings for the named analysts can actually be exported, or whether we fall back to FantasyPros' consensus Best/Worst/Avg/StdDev columns (`panel_mode = "consensus_fallback"`). Several panel members are independent analysts whose individual boards may only exist inside FantasyPros' aggregate.
2. Confirm the points-projection source (needed for lineup totals, not just ranks)
3. Decide `sigma` default by back-testing against a real 2025 draft board if one is available
4. Kicker and D/ST projections are close to noise — consider treating them as fixed late-round filler rather than simulating them

---

## Sources

- [2025's Most Accurate Fantasy Football Draft Rankings — FantasyPros](https://www.fantasypros.com/2026/07/2025s-most-accurate-fantasy-football-draft-rankings/)
- [FantasyPros Draft Accuracy Scores](https://www.fantasypros.com/nfl/accuracy/draft.php)
- [FantasyPros PPR Cheat Sheet](https://www.fantasypros.com/nfl/cheatsheets/top-ppr-players.php)
- [ESPN Fantasy Projections](https://fantasy.espn.com/football/players/projections)
- [FFToday Rankings](https://www.fftoday.com/rankings/)
- [nflreadpy load functions](https://nflreadpy.nflverse.com/api/load_functions/)
- [nflverse/nflreadpy on GitHub](https://github.com/nflverse/nflreadpy)
