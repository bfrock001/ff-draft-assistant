import numpy as np

from pool import PlayerPool
from sim import (
    QB, RB, WR, TE, K, DST,
    opponent_draft_order,
    optimal_lineup_points,
    recommend_sim,
)


def test_sigma0_reproduces_espn_order():
    """§12 sanity: with sigma=0 opponents draft in exact ESPN ADP order."""
    adp = [5, 2, 8, 1, 9, 3, 7, 4, 6, 10]
    recs = [{"id": f"P{i}", "name": f"P{i}", "pos": ("RB" if i % 2 else "WR"),
             "proj_points": 100 - i, "espn_adp": adp[i]} for i in range(10)]
    pool = PlayerPool.from_records(recs)
    order = opponent_draft_order(pool, drafted=set(), sigma=0, seed=0, n_picks=10)
    assert order == list(np.argsort(adp))


def test_lineup_optimizer_known_roster():
    """§12: hand-built roster with a known optimal starting lineup."""
    recs = [
        {"id": "qb", "name": "qb", "pos": "QB", "proj_points": 20, "espn_adp": 1},
        {"id": "rb1", "name": "rb1", "pos": "RB", "proj_points": 15, "espn_adp": 2},
        {"id": "rb2", "name": "rb2", "pos": "RB", "proj_points": 12, "espn_adp": 3},
        {"id": "rb3", "name": "rb3", "pos": "RB", "proj_points": 10, "espn_adp": 4},
        {"id": "wr1", "name": "wr1", "pos": "WR", "proj_points": 14, "espn_adp": 5},
        {"id": "wr2", "name": "wr2", "pos": "WR", "proj_points": 9, "espn_adp": 6},
        {"id": "te", "name": "te", "pos": "TE", "proj_points": 8, "espn_adp": 7},
        {"id": "k", "name": "k", "pos": "K", "proj_points": 5, "espn_adp": 8},
        {"id": "dst", "name": "dst", "pos": "DST", "proj_points": 7, "espn_adp": 9},
    ]
    pool = PlayerPool.from_records(recs)
    mine = np.ones((1, len(pool)), dtype=bool)
    perf = pool.proj_points[None, :].astype(float)
    # QB20 + RB15+RB12 + WR14+WR9 + TE8 + FLEX(rb3=10) + DST7 + K5 = 100
    assert optimal_lineup_points(mine, perf, pool.pos_code)[0] == 100.0


def _te_cliff_sim_pool():
    recs = [
        {"id": "QB1", "name": "QB1", "pos": "QB", "proj_points": 280, "espn_adp": 5},
        {"id": "QB2", "name": "QB2", "pos": "QB", "proj_points": 210, "espn_adp": 40},
        {"id": "TE_A", "name": "TE_A", "pos": "TE", "proj_points": 250, "espn_adp": 6},
        {"id": "TE_B", "name": "TE_B", "pos": "TE", "proj_points": 245, "espn_adp": 7},
    ]
    for i in range(4):  # TE cliff
        recs.append({"id": f"TEbad{i}", "name": f"TEbad{i}", "pos": "TE",
                     "proj_points": 60 - i, "espn_adp": 50 + i})
    for i in range(12):  # deep, flat RB pool
        recs.append({"id": f"RB{i}", "name": f"RB{i}", "pos": "RB",
                     "proj_points": 180 - i, "espn_adp": 8 + i})
    for i in range(8):
        recs.append({"id": f"WR{i}", "name": f"WR{i}", "pos": "WR",
                     "proj_points": 170 - i, "espn_adp": 9 + i})
    for i in range(2):
        recs.append({"id": f"K{i}", "name": f"K{i}", "pos": "K",
                     "proj_points": 130, "espn_adp": 100 + i})
        recs.append({"id": f"D{i}", "name": f"D{i}", "pos": "DST",
                     "proj_points": 100, "espn_adp": 110 + i})
    return PlayerPool.from_records(recs)


def test_te_cliff_sim_recommends_te():
    """The behavior the app exists for: 2 elite TEs + steep drop + deep RBs ->
    the sim recommends a TE (§12)."""
    pool = _te_cliff_sim_pool()
    recs = recommend_sim(pool, drafted=set(), my_slot=1, current_pick=1,
                         my_roster_ids=[], n_sims=150, sigma=8.0, seed=0,
                         n_teams=4, n_rounds=6)
    assert recs[0]["pos"] == "TE"


def test_determinism_same_seed():
    pool = _te_cliff_sim_pool()
    kw = dict(drafted=set(), my_slot=1, current_pick=1, my_roster_ids=[],
              n_sims=100, sigma=8.0, seed=7, n_teams=4, n_rounds=6)
    a = recommend_sim(pool, **kw)
    b = recommend_sim(pool, **kw)
    assert a == b
    # a different seed can differ, but must still be internally valid
    c = recommend_sim(pool, **{**kw, "seed": 8})
    assert len(c) == 3


def test_manual_exclude_keeps_players_out_of_recs():
    pool = _te_cliff_sim_pool()
    recs = recommend_sim(pool, drafted=set(), my_slot=1, current_pick=1,
                         my_roster_ids=[], n_sims=150, sigma=8.0, seed=0,
                         n_teams=4, n_rounds=6, exclude={"TE_A", "TE_B"})
    ids = {r["canonical_id"] for r in recs}
    assert "TE_A" not in ids and "TE_B" not in ids
