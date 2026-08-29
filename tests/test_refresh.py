"""Refresh core: snapshot diff logic (synthetic) + rebuild reproduces the board
(integration, skipped where the crosswalk/data are absent)."""
import os
import shutil

import pandas as pd
import pytest

import refresh
import snapshots


def test_diff_detects_movers_entrants_dropped(monkeypatch):
    old = pd.DataFrame({"canonical_id": ["A", "B", "C"],
                        "name": ["Al", "Bo", "Cy"], "rank": [1, 2, 3]})
    new = pd.DataFrame({"canonical_id": ["A", "C", "D", "B"],
                        "name": ["Al", "Cy", "Dee", "Bo"], "rank": [1, 2, 3, 20]})
    boards = {"old": old, "new": new}
    monkeypatch.setattr(refresh, "load_board", lambda date: boards[date])

    d = refresh.diff("old", "new", top_n=3)
    assert [m["name"] for m in d["movers"]] == ["Bo"]      # 2 -> 20
    assert d["movers"][0]["delta"] == 18
    assert d["entrants"] == ["Dee"]                        # entered top 3
    assert d["dropped"] == ["Bo"]                          # fell out of top 3


CROSSWALK = "data/cache/ff_playerids.parquet"
RANKINGS = "data/raw/2026-08-28/rankings_ppr_consensus_2026-08-28.csv"


@pytest.mark.skipif(not (os.path.exists(CROSSWALK) and os.path.exists(RANKINGS)),
                    reason="board data missing")
def test_rebuild_reproduces_board(tmp_path):
    """Staging today's raw files under a fresh date and rebuilding must yield a
    board identical to the active one, with the ID gate clean (Increment-1
    acceptance)."""
    from board import load_board
    src = "data/raw/2026-08-28"
    new = "2099-01-02"
    dst = snapshots.snapshot_dir(new)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(dst)
    try:
        shutil.copy(f"{src}/rankings_ppr_consensus_2026-08-28.csv", f"{dst}/rankings.csv")
        shutil.copy(f"{src}/espn_ranks_2026-08-28.csv", f"{dst}/espn_ranks.csv")
        for fn in ("proj_qb.csv", "proj_rb.csv", "proj_wr.csv", "proj_te.csv",
                   "proj_k.csv", "proj_dst.csv"):
            shutil.copy(f"{src}/{fn}", f"{dst}/{fn}")

        m = refresh.rebuild(new)
        assert m["gate"]["unmatched_top_n_count"] == 0
        assert m["coverage"]["proj_have"] == m["coverage"]["total"]

        a = load_board("2026-08-28").sort_values("rank").reset_index(drop=True)
        b = load_board(new).sort_values("rank").reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b)
        assert refresh.diff("2026-08-28", new) == {
            "old_date": "2026-08-28", "new_date": new,
            "movers": [], "entrants": [], "dropped": []}
    finally:
        shutil.rmtree(dst, ignore_errors=True)
