import pytest

from pool import POSITIONS, PlayerPool
from vona import needed_positions, vona_recommend


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


def test_needed_positions():
    assert needed_positions([]) == set(POSITIONS)
    # QB slot filled -> QB no longer needed
    assert "QB" not in needed_positions(["QB"])
    # a full 9-starter roster -> nothing needed
    full = ["QB", "RB", "RB", "WR", "WR", "TE", "RB", "DST", "K"]
    assert needed_positions(full) == set()


def test_drafted_players_are_excluded():
    pool = te_cliff_pool()
    recs = vona_recommend(pool, drafted={"TE_A"}, current_pick=15, next_pick=26,
                          roster_positions=[], k=3)
    assert all(r["canonical_id"] != "TE_A" for r in recs)
    # TE_B is now the best-now TE
    te = next((r for r in recs if r["pos"] == "TE"), None)
    assert te is not None and te["name"] == "TE_B"
