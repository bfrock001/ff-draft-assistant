import polars as pl

from history import _SRC_COLS, _ppr_expr, season_summary


def _weekly(rows):
    full = []
    for r in rows:
        d = {c: 0 for c in _SRC_COLS}
        d.update(r)
        full.append(d)
    return pl.DataFrame(full).with_columns(_ppr_expr())


def test_ppr_scores_a_wr_game():
    df = _weekly([{"player_id": "x", "season": 2024, "week": 1, "position": "WR",
                   "receptions": 8, "receiving_yards": 130, "receiving_tds": 2}])
    assert df["ppr"][0] == 33.0   # 8 + 13 + 12


def test_ppr_scores_a_kicker_game_by_distance():
    df = _weekly([{"player_id": "k", "season": 2024, "week": 1, "position": "K",
                   "fg_made_30_39": 1, "fg_made_40_49": 1, "fg_made_50_59": 1,
                   "pat_made": 3}])
    assert df["ppr"][0] == 15.0   # 3 + 4 + 5 + 3


def test_ppr_counts_interceptions_and_fumbles():
    df = _weekly([{"player_id": "qb", "season": 2024, "week": 1, "position": "QB",
                   "passing_yards": 300, "passing_tds": 3, "passing_interceptions": 1,
                   "rushing_yards": 25, "rushing_tds": 1, "rushing_fumbles_lost": 1}])
    # 12 + 12 - 2 + 2.5 + 6 - 2 = 28.5
    assert df["ppr"][0] == 28.5


def test_season_summary_totals_and_consistency():
    df = _weekly([
        {"player_id": "p", "season": 2024, "week": 1, "position": "RB", "rushing_yards": 250},  # 25
        {"player_id": "p", "season": 2024, "week": 2, "position": "RB", "rushing_yards": 30},    # 3
        {"player_id": "p", "season": 2024, "week": 3, "position": "RB", "rushing_yards": 100},   # 10
    ])
    s = {r["season"]: r for r in season_summary(df, "p")}[2024]
    assert s["total"] == 38.0
    assert s["games"] == 3
    assert s["boom_pct"] == 33   # 1 of 3 >= 20
    assert s["bust_pct"] == 33   # 1 of 3 <= 5
    assert s["missed"] == 14     # 17 - 3
