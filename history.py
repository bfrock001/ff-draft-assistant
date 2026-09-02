"""Historical scoring / drill-down (spec §3.3, §4, §10 player detail, Phase 4).

Weekly player stats (2023-2025) from nflreadpy, scored through our OWN §4 rules
(never a source's precomputed fantasy points, §3.3). Fetched once and cached to
data/cache/; every later read is offline. Kickers use the FG-by-distance bands.
Team D/ST are not in the weekly player table (no team rows, no points-allowed),
so game-level D/ST history is out of scope here — the UI says so.
"""
from __future__ import annotations

import os

import polars as pl

from scoring import (
    FG_0_39, FG_40_49, FG_50_PLUS, FUMBLE_LOST, PAT, PASS_INT, PASS_TD,
    PASS_YDS_PER_PT, RECEPTION, RUSH_REC_TD, RUSH_REC_YDS_PER_PT, TWO_PT,
)

WEEKLY_CACHE = "data/cache/weekly_ppr.parquet"
CROSSWALK_CACHE = "data/cache/ff_playerids.parquet"
SEASONS = [2023, 2024, 2025]
GAMES_PER_SEASON = 17

_SRC_COLS = [
    "player_id", "player_display_name", "position", "season", "week", "team",
    "opponent_team", "passing_yards", "passing_tds", "passing_interceptions",
    "passing_2pt_conversions", "rushing_yards", "rushing_tds",
    "rushing_2pt_conversions", "rushing_fumbles_lost", "receptions",
    "receiving_yards", "receiving_tds", "receiving_2pt_conversions",
    "receiving_fumbles_lost", "sack_fumbles_lost", "fg_made_0_19",
    "fg_made_20_29", "fg_made_30_39", "fg_made_40_49", "fg_made_50_59",
    "fg_made_60_", "pat_made",
]


def _ppr_expr() -> pl.Expr:
    """§4 PPR from a weekly stat row (offense + kicker distance bands)."""
    c = pl.col
    return (
        c("passing_yards") * PASS_YDS_PER_PT + c("passing_tds") * PASS_TD
        + c("passing_interceptions") * PASS_INT
        + c("rushing_yards") * RUSH_REC_YDS_PER_PT + c("rushing_tds") * RUSH_REC_TD
        + c("receptions") * RECEPTION + c("receiving_yards") * RUSH_REC_YDS_PER_PT
        + c("receiving_tds") * RUSH_REC_TD
        + (c("passing_2pt_conversions") + c("rushing_2pt_conversions")
           + c("receiving_2pt_conversions")) * TWO_PT
        + (c("rushing_fumbles_lost") + c("receiving_fumbles_lost")
           + c("sack_fumbles_lost")) * FUMBLE_LOST
        + (c("fg_made_0_19") + c("fg_made_20_29") + c("fg_made_30_39")) * FG_0_39
        + c("fg_made_40_49") * FG_40_49
        + (c("fg_made_50_59") + c("fg_made_60_")) * FG_50_PLUS
        + c("pat_made") * PAT
    ).round(2).alias("ppr")


def ensure_weekly_cached(path: str = WEEKLY_CACHE) -> None:
    """One-time fetch + §4 scoring, cached to parquet. Offline thereafter."""
    if os.path.exists(path):
        return
    import nflreadpy as nfl
    w = nfl.load_player_stats(seasons=SEASONS)
    w = (w.filter(pl.col("season_type") == "REG")
          .select(_SRC_COLS).fill_null(0)
          .with_columns(_ppr_expr())
          .select(["player_id", "player_display_name", "position", "season",
                   "week", "team", "opponent_team", "ppr"]))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    w.write_parquet(path)


def load_weekly(path: str = WEEKLY_CACHE) -> pl.DataFrame:
    ensure_weekly_cached(path)
    return pl.read_parquet(path)


def mfl_to_gsis(path: str = CROSSWALK_CACHE) -> dict[str, str]:
    df = pl.read_parquet(path)
    out = {}
    for mfl, gsis in df.select(["mfl_id", "gsis_id"]).iter_rows():
        if mfl is not None and gsis is not None:
            out[str(mfl)] = str(gsis)
    return out


def season_summary(weekly: pl.DataFrame, gsis_id: str) -> list[dict]:
    """Per-season totals, PPG, games, boom/bust rates, games missed (§10)."""
    p = weekly.filter(pl.col("player_id") == gsis_id)
    rows = []
    for season in SEASONS:
        s = p.filter(pl.col("season") == season)
        games = s.height
        if games == 0:
            rows.append({"season": season, "total": 0.0, "ppg": 0.0, "games": 0,
                         "boom_pct": None, "bust_pct": None, "missed": None})
            continue
        pts = s["ppr"]
        total = float(pts.sum())
        rows.append({
            "season": season, "total": round(total, 1),
            "ppg": round(total / games, 1), "games": games,
            "boom_pct": round(100 * (pts >= 20).sum() / games),
            "bust_pct": round(100 * (pts <= 5).sum() / games),
            "missed": max(0, GAMES_PER_SEASON - games),
        })
    return rows


def season_totals(weekly: pl.DataFrame) -> dict[str, dict[int, float]]:
    """{gsis player_id: {season: total PPR}} — one pass over the weekly data, so
    the cheat sheet can show prior-season points for the whole board at once."""
    g = (weekly.group_by(["player_id", "season"])
               .agg(pl.col("ppr").sum().alias("total")))
    out: dict[str, dict[int, float]] = {}
    for pid, season, total in g.select(["player_id", "season", "total"]).iter_rows():
        if pid is None:
            continue
        out.setdefault(str(pid), {})[int(season)] = round(float(total), 1)
    return out


def game_log(weekly: pl.DataFrame, gsis_id: str, season: int) -> pl.DataFrame:
    return (weekly.filter((pl.col("player_id") == gsis_id) & (pl.col("season") == season))
                  .select(["week", "opponent_team", "ppr"]).sort("week"))
