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


def test_carry_fantasypros_forward_copies_only_missing():
    src, dst = "2099-03-03", "2099-03-04"
    sd, dd = snapshots.snapshot_dir(src), snapshots.snapshot_dir(dst)
    for p in (sd, dd):
        if os.path.isdir(p):
            shutil.rmtree(p)
    os.makedirs(sd)
    with open(os.path.join(sd, "rankings.csv"), "w") as f:
        f.write("orig\n")
    for fn in snapshots.PROJ_RAW.values():
        with open(os.path.join(sd, fn), "w") as f:
            f.write("orig\n")
    try:
        # dst already has its own rankings -> must NOT be overwritten
        os.makedirs(dd)
        with open(os.path.join(dd, "rankings.csv"), "w") as f:
            f.write("keep\n")
        refresh.carry_fantasypros_forward(src, dst)
        with open(os.path.join(dd, "rankings.csv")) as f:
            assert f.read() == "keep\n"                 # not clobbered
        for pos in ("QB", "RB", "WR", "TE", "K", "DST"):
            assert os.path.exists(snapshots.proj_raw_path(dst, pos))  # carried
    finally:
        shutil.rmtree(sd, ignore_errors=True)
        shutil.rmtree(dd, ignore_errors=True)


CROSSWALK = "data/cache/ff_playerids.parquet"
RANKINGS = "data/raw/2026-08-28/rankings_ppr_consensus_2026-08-28.csv"


@pytest.mark.skipif(not (os.path.exists(CROSSWALK) and os.path.exists(RANKINGS)),
                    reason="board data missing")
def test_rebuild_reproduces_board(tmp_path):
    """Staging today's raw files under a fresh date and rebuilding must yield a
    board identical to the active one, with the ID gate clean (Increment-1
    acceptance)."""
    from board import load_board
    src, new = "2026-08-28", "2099-01-02"
    dst = snapshots.snapshot_dir(new)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(dst)
    try:
        # copy the snapshot's AUTHORITATIVE raws (robust to an ESPN refresh that
        # replaced the dated espn_ranks_*.csv with the standardized espn_ranks.csv)
        shutil.copy(snapshots.rankings_path(src), f"{dst}/rankings.csv")
        shutil.copy(snapshots.espn_raw_path(src), f"{dst}/espn_ranks.csv")
        for pos in ("QB", "RB", "WR", "TE", "K", "DST"):
            shutil.copy(snapshots.proj_raw_path(src, pos),
                        snapshots.proj_raw_path(new, pos))

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
