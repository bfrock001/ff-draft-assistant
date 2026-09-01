# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local **Python + Streamlit** draft-day assistant for a fantasy football draft (~mid-September 2026). During a live 10-team PPR snake draft it recommends the top-3 picks that maximize the projected points of the user's final *starting lineup*, accounting for analyst disagreement and for what opponents are likely to do before the user's next turn.

The full specification is `DRAFT_ASSISTANT_REQUIREMENTS.md` — a newer, expanded version that **supersedes** the earlier `DRAFT_ASSISTANT_REQUIREMENTS.md.pdf` / `req_extracted.txt` (prefer the `.md`; it adds the per-position analyst panel in §3.1 and the dated-snapshot/refresh system in §3.5). **That document is the source of truth.** When this file and the requirements disagree, the requirements win — update this file to match. Section numbers below (§N) refer to that document.

The project is **pre-implementation**: no application code exists yet. Build order is phased and gated — see "Standing constraints" and §11.

## Standing constraints (do not violate)

1. **No pandas or Polars operations inside the simulation loop.** The player pool in the simulation/recommendation hot path must be **NumPy arrays indexed by integer player ID** (§9). pandas/Polars are fine for load-time prep and the UI, never inside the per-sim loop. This is the single most common way this kind of code ends up ~100× too slow.
2. **Build strictly one phase at a time (§11).** Do not start a phase until the user explicitly asks for it. Each phase must be working, tested against its acceptance criterion, and committed before the next begins. If time runs short, ship through Phase 2 and stop — a working simple app beats a half-finished clever one on draft day.

Other hard requirements from the spec:
- **No network dependency at run time (§3).** All data is downloaded once into `data/raw/` before draft day and committed; the app reads local snapshot files at launch. `nflreadpy` pulls are cached to `data/cache/*.parquet` on first run and never re-fetched. Draft day cannot depend on a scraper or API working.
- **Recommendation must return in under 3 seconds (§9)** — there is a draft clock. If it can't, drop `n_sims` to 250 and expose it as a setting rather than accepting slow.
- **Compute PPR points ourselves** from raw stat lines using the §4 rules. Never use any source's precomputed fantasy points — they won't match this scoring.

## League configuration (§1 — hard values; live in `config.py`)

| Setting | Value |
|---|---|
| Teams | 10 |
| Rounds | 16 (160 total picks) |
| Draft type | Snake |
| My draft slot | **Unknown until draft day** — a setting, selectable 1–10 at launch |
| Keepers | None |
| Roster size | 16 (9 starters + 7 bench) |
| Starting lineup | 1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX (RB/WR/TE), 1 D/ST, 1 K |
| Scoring | ESPN standard PPR (full detail in §4 / below) |

**Snake pick math** — for slot `s` (1-indexed) in a 10-team league, round `r`:
- odd round: `pick = (r-1)*10 + s`
- even round: `pick = (r-1)*10 + (11 - s)`

Example, slot 3: `3, 18, 23, 38, 43, 58, 63, 78, 83, 98, 103, 118, 123, 138, 143, 158`.
The gap between consecutive picks **alternates** (e.g. slot 3: 15 picks, then 5). The engine must use the *real* gap to each next turn, never an average — knowing who survives to the next turn is the whole point of the app.

## Scoring rules (§4 — implement as a pure function `stat_line -> points`)

Used for both historical points and for converting projected stat lines into projected points, so the two are consistent. **Unit-test this against 5–10 hand-calculated stat lines before building anything else.**

- **Passing:** 0.04 pts/yd · TD 4 · INT −2 · 2PC 2
- **Rushing/Receiving:** reception 1.0 · 0.1 pts/yd · TD 6 · 2PC 2 · fumble lost −2
- **Kicking:** PAT 1 · FG 0–39 = 3 · FG 40–49 = 4 · FG 50+ = 5 · misses 0
- **D/ST:** sack 1 · INT 2 · fumble rec 2 · safety 2 · blocked kick 2 · TD 6
- **D/ST points allowed:** 0 → 5 · 1–6 → 4 · 7–13 → 3 · 14–17 → 1 · 18–27 → 0 · 28–34 → −1 · 35+ → −3

## Data model (§3)

**Snapshot files**, read locally at launch; no network at run time.

- **Raw snapshots are dated (§3.5):** `data/raw/YYYY-MM-DD/`, selected by `config/active_snapshot` (or `--snapshot`), default = most recent. Each folder carries a `manifest.json` (capture date, source URLs, checksums, row counts). UI shows "Data as of \<date\>" and warns if the active snapshot is >7 days old. **Never overwrite a snapshot in place**; `refresh.py` writes a *new* dated folder and prints a diff vs. the previous one (rank moves >10, new top-200 entrants, disappearances).
- **Analyst panel is config-driven (§3.1), not code:** `config/analyst_panel.csv` is the single source of truth for who is in the panel and at which positions. It is filtered **per position** via `use_qb/use_rb/use_wr/use_te/use_k/use_dst` flags — an expert contributes to a position only if their 2025 **draft/preseason** positional accuracy rank ≤ 60 (Seth Miller is #1 overall but `use_te=0`, ranked 187th at TE). Per-position consensus + `rank_sd` use only that position's flagged experts; the `weight` column makes it a weighted mean (SD weighted to match). **Validate on load and fail loudly** if a column is missing, a `rankings_file` is absent, or a position has < 3 contributors. Verified contributing counts: QB 15 · RB 20 · WR 19 · TE 13 · K 12 · D/ST 7 (28 experts total). Use per-expert `rankings_file`s if obtainable; otherwise set `panel_mode="consensus_fallback"` (FantasyPros Best/Worst/Avg/StdDev) and show a UI badge. Note: FantasyPros draft accuracy is scored in **half-PPR** and excludes K/D-ST — a good proxy for our full-PPR league, not perfect.
- **Points projections** — a projected-stat-line source (FantasyPros projections or FFToday); ranks alone can't produce a lineup total. Convert to points via §4.
- **`data/raw/espn_adp.csv`** — ESPN ranks/ADP, used **only** for the opponent model (the league auto-drafts off ESPN's board).
- **`data/cache/*.parquet`** — cached `nflreadpy` weekly stats (2023–2025) + `load_ff_playerids()` crosswalk (fetched once, then offline).
- **`data/unmatched.csv`, `data/manual_id_overrides.csv`** — player-identity resolution (§5), the highest-risk plumbing. Acceptance: **zero unmatched players in the top 200 by consensus rank.**
- **`state/draft_YYYYMMDD.json`** — full draft state written after every pick for crash recovery / resume (§10).

## Build phases (§11) — each gated by its acceptance test

- **Phase 0 — Foundation:** scoring function + unit tests · data loaders · player ID resolution · clean `data/unmatched.csv` for top 200. *Accept:* scoring tests pass; zero unmatched in top 200.
- **Phase 1 — Static board:** Streamlit UI, player table with consensus value + spread, click-off tracking, undo, state save/resume, my-roster panel. *Accept:* run a full 160-pick mock draft without the app breaking.
- **Phase 2 — VONA engine (the safety net):** best-available-now vs best-likely-available-at-next-pick, per position. *Accept:* sane top 3 instantly; this is the guaranteed-working draft-day fallback.
- **Phase 3 — Simulation engine:** Monte Carlo opponent model, full-roster simulation, risk dial, availability odds, reasoning strings. *Accept:* meets the 3-second budget; toggle compares against VONA.
- **Phase 4 — History drill-down:** 3-year totals, game logs, consistency metrics, charts.
- **Phase 5 — Polish:** reasoning wording, layout under time pressure, dry-run mock draft.

## Model architecture — two sources, two axes

**Two data sources, two roles (rankings ≠ projections).** Analysts publish *rank orders*, not point projections — "the panel's projected points" is not a real, downloadable thing (projections come from a separate, smaller set of stat-projectors). So the two sources do different jobs and the model bridges them:
- `proj_points` ← the **projection source** (one stat-line projection per player, scored via §4). Rankings never produce points.
- `points_sd` ← the **rankings** disagreement, mapped into points: `points_sd ≈ rank_std × |local slope of the position's points-vs-rank curve|`. This bridge is a modeling choice **beyond the spec's literal §6 wording — sanity-check it** once real numbers flow.
- Candidate selection (`top_k_available`) uses the **ranking** consensus; points only set magnitude. A player in the rankings but missing from projections gets `proj_points` by interpolating their `consensus_rank` off the position points-curve.

**Two independent random axes per simulation** (they only interact inside one sim):
- *Performance axis (points/value):* `perf[] ~ N(proj_points, points_sd)`. Drives future-me's greedy picks (§8.1) and the final lineup score (§8.2) — the **same** drawn vector for both, which is what keeps future-me self-consistent.
- *Opponent axis (availability):* `adp_s[] = espn_adp + N(0, sigma)`, drawn once per sim. Drives opponent picks only. `sigma=0` ⇒ strict ESPN order (the sanity check touches only this axis; determinism comes from the seed).

**Phase 2 (VONA)** uses the same top-of-pipeline metrics but skips both draws and the whole simulation — best consensus value available now vs. best likely still available at my next pick (from ADP survival). No randomness; the guaranteed draft-day fallback.

## Engine notes (for when those phases are reached)

- **Opponent model (§7):** perturb the board **once per simulation** (`adp_sim[i] = espn_adp[i] + N(0, sigma)`, sigma ≈ 8), not per pick. Each opponent pick takes the lowest `adp_sim` still available, subject to roster caps: max 2 QB, 2 TE, 1 K, 1 D/ST, 16 total; no K or D/ST before round 13. `sigma` is tunable and **`sigma=0` must exactly reproduce ESPN order** (required debug/sanity mode).
- **Recommendation (§8):** for each of the top-k available candidates, run `n_sims` full-draft futures (future-me picks greedily per §8.1; opponents per §7); score each candidate by the chosen percentile of final optimal-starting-lineup totals.
- **Lineup optimizer (§8.2):** greedy by position then best remaining RB/WR/TE into FLEX is provably optimal for this slot structure — no solver.
- **Risk dial (§8.3):** operates on the *team outcome distribution*, not individual players — Safe = 30th pct (floor), Balanced = 50th (median, default), Upside = 70th (ceiling).

## Testing (§12)

Key required tests: scoring (incl. D/ST tiers + FG distance bands) · snake pick math (slot 3 → `[3,18,23,38,...]`, slot 10 → `[10,11,30,31,...]`) · lineup optimizer · **the TE-cliff scenario** (synthetic board with 2 elite TEs, a steep TE dropoff, 12 near-identical RBs → engine must recommend a TE; this is the behavior the whole app exists for) · determinism under a fixed seed · `sigma=0` reproduces ESPN order · Phase 2 vs Phase 3 cross-check on a mock draft.

## Tooling / commands

Python 3.12 + Streamlit; historical data via `nflreadpy` (maintained port of nflreadr; `nfl_data_py` is the older package). Deps in `requirements.txt`; pytest configured in `pyproject.toml` (`pythonpath=["."]`, `testpaths=["tests"]`).
- Install: `pip install -r requirements.txt`
- Run tests: `pytest` (single test: `pytest tests/test_scoring.py::test_qb_line`)
- Close the ID gate / refresh: `python loaders.py` — resolves the rankings against the crosswalk, writes `data/unmatched.csv`, exits non-zero if any top-200 player is unmatched. Fetches + caches `data/cache/ff_playerids.parquet` on first run (the one network touch; runtime is offline thereafter).
- Rebuild a snapshot's derived data: `python refresh.py` — rebuilds `projections.csv` + `espn_adp.csv` for the active snapshot, runs the gate, writes `manifest.json`.
- Run the app: `streamlit run app.py` (or the `.claude/launch.json` "app" config).

Modules: `config.py` (§1), `scoring.py` (§4), `ids.py` (§5), `snapshots.py` (§3.5 dated-snapshot discovery/selection + file paths — single source of truth for which snapshot the app reads; `config/active_snapshot` else newest), `loaders.py` (§3 + §5 gate; `gate_report` is the programmatic gate), `espn_adp.py` / `projections.py` (§3 snapshots → espn_adp + proj_points; both date-parameterized, `projections.py` is the FantasyPros *adapter*), `board.py` (§6 unified table, reads the active snapshot), `refresh.py` (§3.5 rebuild derived files → gate → `manifest.json` → diff vs previous; `refresh_espn` pulls a fresh ESPN board), `espn_live.py` (§3.2 pre-draft ESPN board pull from ESPN's league API server-side, cookies in git-ignored `config/espn_cookies.json`), `pool.py` (§9 NumPy player pool + §6 points_sd bridge), `vona.py` (§8 fallback / Phase 2 VONA engine), `sim.py` (§7/§8 Monte Carlo engine — sim-vectorized), `explain.py` (Phase 5 offline "why" explainer), `history.py` (§3.3/§4 historical drill-down — nflreadpy weekly stats scored via §4, cached), `strategy.py` (round/roster-aware risk-dial suggestion, §8.3), `overrides.py` (Increment 2 manual value overlay — proj/rank edits + exclude, global by canonical_id), `draft_state.py` + `app.py` (§10 Streamlit board + VONA/Sim cards + engine toggle + "Why?" expanders + player-detail drill-down + snapshot picker + "Update data" upload panel + "Update ESPN board" button + per-round risk-dial suggestion w/ one-click apply + σ hint + editable board via data_editor). The sim runs ONLY when you're on the clock (off-turn shows an instant VONA preview, so clicking off a fast run stays snappy); the board supports multi-select **batch drafting** (tick several → one Draft, in board order) with the Draft control rendered both above and below the board. **Phases 0–4 complete + Phase 5 explainer + logo; Data-update Data-update Increments 1 (snapshots + FantasyPros upload), 2 (editable board / manual overrides) & 3 (ESPN button) all done** (Phase 2 tagged `v0.2.0`) — 84 tests pass; zero unmatched in top 200; full 160-pick dry-run mock with save/resume; VONA sane top-3 in ~1 ms; the sim returns in ~2 s for n_sims=500 (under the 3 s budget), `sigma=0` reproduces ESPN order, fixed seed → identical, TE-cliff test passes; the offline explainer regenerates the value/risk/scarcity/roster-fit narrative with no network; history drill-down gives 3-yr PPR totals, PPG, game logs + bar chart, and boom/bust/missed consistency for QB/RB/WR/TE/K (team D/ST game logs out of scope — not in the weekly player data). **Data-update: all three increments done.** Manual overrides (`overrides.py` → `data/manual_overrides.csv`, gitignored, keyed by canonical_id) layer proj/rank edits + exclusions over the active snapshot and carry across refreshes; proj/rank flow through the board→pool, `exclude` is passed to both recommenders (excluded players still get drafted by opponents and stay on the board to track). Remaining optional: decimal-ADP opponent-model upgrade. The ESPN button (`refresh_espn_smart`) pulls 300 players with real decimal ADP and writes into TODAY's snapshot — in place if today's is active, else it creates a new dated snapshot (FantasyPros carried forward) and activates it, so older dated snapshots stay pristine (§3.5); non-destructive (network fetch happens before any write). Validated live at 200/200 top-200 coverage. The opponent model still uses `espn_rank` as the ADP proxy (a decimal-ADP upgrade is available but not yet wired). `data/cache/*.parquet`, `state/*.json`, `config/espn_cookies.json`, `config/active_snapshot` are gitignored; `data/manual_id_overrides.csv` is hand-maintained input.
