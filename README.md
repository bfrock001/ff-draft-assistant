# Who's Your Daddy? — Fantasy Football Draft Assistant

A local **Python + Streamlit** draft-day assistant for a 10-team PPR snake draft.
During a live draft it recommends the top-3 picks that maximize the projected
points of your final **starting lineup** — accounting for analyst disagreement
and for what your opponents are likely to do before your next turn.

> Personal project. Not affiliated with ESPN or FantasyPros. Fantasy points are
> computed from raw stat lines using this league's scoring, never a source's
> precomputed totals.

## What it does

- **Two recommendation engines**
  - **VONA** (instant): best value available now vs. best likely to survive to
    your next pick, weighted by what your roster still needs — the guaranteed,
    dependency-free fallback.
  - **Monte Carlo simulation**: runs hundreds of full-draft futures per candidate
    (opponent model + your greedy future picks) and scores each by a percentile
    of your final starting-lineup points. Returns in under 3 seconds.
- **Draft-aware coaching** — a per-round **risk-dial** suggestion (protect your
  anchors early, chase ceiling on the bench) and an opponent-randomness (σ) hint.
- **Editable board** — disagree with a ranking? Edit a player's projection or
  consensus rank, or exclude a player; both engines respect it, and your edits
  survive data refreshes.
- **Dated data snapshots** — refresh **FantasyPros** rankings/projections (in-app
  upload) and the **ESPN ADP** board (one-click pull) into new dated snapshots; a
  picker switches between them, with a staleness warning.
- **History drill-down** — 3-year PPR totals, per-game logs, and boom/bust
  consistency, scored through this league's rules from `nflreadpy` weekly data.
- **Offline "Why?" explainer**, full pick tracking with **undo** and
  **save/resume**, and a roster panel.

## Setup

Requires **Python 3.12**.

```bash
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

The first run fetches historical player data via `nflreadpy` and caches it to
`data/cache/` (the one network touch); every later run is fully offline, so the
app never depends on a scraper or API mid-draft.

## Configuration

- **League settings** live in `config.py` (teams, rounds, roster, scoring).
- **Your draft slot** is picked in the sidebar at launch.
- **ESPN ADP refresh** (optional): copy `config/espn_cookies.example.json` to
  `config/espn_cookies.json` and paste your ESPN session cookies (`espn_s2`,
  `SWID`). This file is git-ignored — treat those cookies like a password.

## Data

- `data/raw/<YYYY-MM-DD>/` — committed dated snapshots (rankings, projections,
  ESPN board) the app reads at launch.
- `data/cache/*.parquet` — cached `nflreadpy` pulls (git-ignored, regenerated).
- `state/*.json` — per-pick draft save for crash recovery (git-ignored).

## Tests

```bash
pytest
```

Covers scoring (incl. D/ST tiers + FG bands), snake-pick math, the lineup
optimizer, the TE-cliff scenario, determinism, `sigma=0` reproducing ESPN order,
and the data pipeline.
