from explain import explain_candidate
from pool import PlayerPool


def _pool():
    recs = [
        {"id": "wr1", "name": "WR One", "pos": "WR", "proj_points": 300,
         "consensus_rank": 3, "rank_sd": 1.0, "espn_adp": 3},
        {"id": "wr2", "name": "WR Two", "pos": "WR", "proj_points": 290,
         "consensus_rank": 6, "rank_sd": 1.2, "espn_adp": 6},
        {"id": "rbR", "name": "Risky RB", "pos": "RB", "proj_points": 295,
         "consensus_rank": 5, "rank_sd": 6.0, "espn_adp": 5},
        {"id": "wr3", "name": "WR Three", "pos": "WR", "proj_points": 280,
         "consensus_rank": 8, "rank_sd": 1.3, "espn_adp": 8},
        {"id": "wr4", "name": "WR Four", "pos": "WR", "proj_points": 270,
         "consensus_rank": 10, "rank_sd": 1.4, "espn_adp": 10},
        {"id": "qb1", "name": "QB One", "pos": "QB", "proj_points": 320,
         "consensus_rank": 20, "rank_sd": 2.0, "espn_adp": 40},
    ]
    return PlayerPool.from_records(recs)


def _lines(pool, pid, roster=(), my_pick=3, my_next=18):
    idx = pool.ids.index(pid)
    return explain_candidate(pool, idx, set(), list(roster), my_pick, my_next)["lines"]


def test_safe_player_flagged_safe():
    assert any("strongly agree" in L for L in _lines(_pool(), "wr1"))


def test_risky_player_flagged_boom_bust():
    lines = _lines(_pool(), "rbR")
    assert any("split" in L or "boom/bust" in L for L in lines)


def test_qb_early_gets_depth_caveat():
    assert any("deepest position" in L for L in _lines(_pool(), "qb1"))


def test_roster_fit_open_vs_flex():
    assert any("Fills your open WR slot" in L for L in _lines(_pool(), "wr1"))
    assert any("FLEX" in L for L in _lines(_pool(), "wr1", roster=("WR", "WR")))
