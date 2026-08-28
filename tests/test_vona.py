import pytest

from pool import PlayerPool
from vona import roster_factor, roster_openings, vona_recommend


def te_cliff_pool():
    """2 elite TEs + a steep TE drop, and 12 near-identical RBs (spec §12)."""
    recs = [
        {"id": "TE_A", "name": "TE_A", "pos": "TE", "proj_points": 200, "espn_adp": 16},
        {"id": "TE_B", "name": "TE_B", "pos": "TE", "proj_points": 195, "espn_adp": 18},
        {"id": "TE_C", "name": "TE_C", "pos": "TE", "proj_points": 120, "espn_adp": 60},
    ]
    for i in range(12):
        recs.append({"id": f"RB{i}", "name": f"RB{i}", "pos": "RB",
                     "proj_points": 150 - i, "espn_adp": 30 + i})
    return PlayerPool.from_records(recs)


def test_te_cliff_recommends_a_te_first():
    pool = te_cliff_pool()
    # I'm on the clock at 15; my next pick is 26 -> 10 opponents pick in between,
    # so both elite TEs are gone by then but plenty of RBs survive.
    recs = vona_recommend(pool, drafted=set(), current_pick=15, next_pick=26,
                          roster_positions=[], k=3)
    assert recs[0]["pos"] == "TE"
    assert recs[0]["name"] == "TE_A"
    # the TE drop-off (200 -> 120) dwarfs the RB drop-off
    assert recs[0]["vona"] == pytest.approx(80.0)
    assert "cliff" in recs[0]["reasoning"] or "drop" in recs[0]["reasoning"]


def test_no_scarcity_low_vona_and_best_value_leads():
    pool = te_cliff_pool()
    # gap_opp = 0 (consecutive picks) -> everyone survives -> nothing is scarce
    recs = vona_recommend(pool, drafted=set(), current_pick=10, next_pick=11,
                          roster_positions=[], k=3)
    assert max(r["vona"] for r in recs) == pytest.approx(0.0)
    # with no scarcity it degrades to best-player-available (highest proj)
    assert recs[0]["name"] == "TE_A"


def test_determinism():
    pool = te_cliff_pool()
    a = vona_recommend(pool, set(), 15, 26, [], k=3)
    b = vona_recommend(pool, set(), 15, 26, [], k=3)
    assert a == b


def test_last_pick_falls_back_to_best_value():
    pool = te_cliff_pool()
    recs = vona_recommend(pool, set(), current_pick=160, next_pick=None,
                          roster_positions=[], k=3)
    # no next pick -> vona equals the player's own value; the best overall leads
    assert recs[0]["vona"] == pytest.approx(recs[0]["proj_points"])


def test_roster_factor_downweights_filled_positions():
    empty = roster_openings([])
    assert roster_factor("RB", *empty) == 1.0
    assert roster_factor("QB", *empty) == 1.0
    # two RBs rostered: RB dedicated slots full -> FLEX-only (0.5); others 1.0
    two_rb = roster_openings(["RB", "RB"])
    assert roster_factor("RB", *two_rb) == 0.5
    assert roster_factor("WR", *two_rb) == 1.0
    assert roster_factor("TE", *two_rb) == 1.0
    # full 9-starter roster -> everything is bench depth
    full = roster_openings(["QB", "RB", "RB", "WR", "WR", "TE", "RB", "DST", "K"])
    assert roster_factor("RB", *full) == 0.25
    assert roster_factor("QB", *full) == 0.25


def roster_construction_pool():
    """RB has the steepest raw drop, but WR/TE also drop and QB is plentiful."""
    return PlayerPool.from_records([
        {"id": "RB_A", "name": "RB_A", "pos": "RB", "proj_points": 200, "espn_adp": 1},
        {"id": "RB_B", "name": "RB_B", "pos": "RB", "proj_points": 120, "espn_adp": 30},
        {"id": "WR_A", "name": "WR_A", "pos": "WR", "proj_points": 180, "espn_adp": 2},
        {"id": "WR_B", "name": "WR_B", "pos": "WR", "proj_points": 120, "espn_adp": 31},
        {"id": "TE_A", "name": "TE_A", "pos": "TE", "proj_points": 150, "espn_adp": 3},
        {"id": "TE_B", "name": "TE_B", "pos": "TE", "proj_points": 90, "espn_adp": 32},
        {"id": "QB_A", "name": "QB_A", "pos": "QB", "proj_points": 300, "espn_adp": 33},
    ])


def test_third_rb_deprioritized_when_two_already_rostered():
    pool = roster_construction_pool()
    # gap_opp = 3 -> RB_A/WR_A/TE_A gone; RB has the steepest drop-off
    empty = vona_recommend(pool, set(), 10, 14, [], k=3)
    assert empty[0]["pos"] == "RB"       # when I need RBs, the RB cliff leads
    # but with two RBs already, a 3rd (FLEX-only) must not lead over open slots
    two_rb = vona_recommend(pool, set(), 10, 14, ["RB", "RB"], k=3)
    assert two_rb[0]["pos"] != "RB"


def test_drafted_players_are_excluded():
    pool = te_cliff_pool()
    recs = vona_recommend(pool, drafted={"TE_A"}, current_pick=15, next_pick=26,
                          roster_positions=[], k=3)
    assert all(r["canonical_id"] != "TE_A" for r in recs)
    # TE_B is now the best-now TE
    te = next((r for r in recs if r["pos"] == "TE"), None)
    assert te is not None and te["name"] == "TE_B"
