"""Phase 1 acceptance codified: a full 160-pick mock over the REAL board with
per-pick save + resume (spec §10, §11). Skips where board data is absent.
"""
import os

import pytest

pytest.importorskip("polars")

CROSSWALK = "data/cache/ff_playerids.parquet"
RANKINGS = "data/raw/2026-08-28/rankings_ppr_consensus_2026-08-28.csv"

pytestmark = pytest.mark.skipif(
    not (os.path.exists(CROSSWALK) and os.path.exists(RANKINGS)),
    reason="board data missing",
)


def test_full_mock_over_real_board_with_resume(tmp_path):
    from board import load_board
    from draft_state import DraftState

    board = load_board()
    pool, seen = [], set()
    for r in board.itertuples(index=False):
        cid = r.canonical_id
        if isinstance(cid, str) and cid not in seen:
            seen.add(cid)
            pool.append((cid, r.name, r.pos))
    assert len(pool) >= 160  # enough distinct draftable players

    ds = DraftState(my_slot=3, date="2026-09-09")
    path = str(tmp_path / "draft.json")
    for i in range(160):
        cid, name, pos = pool[i]
        ds.make_pick(cid, name, pos)   # default team = on the clock
        ds.save(path)                  # save after every pick (§10)

    assert ds.is_complete()
    assert len(ds.picks) == 160
    assert len(ds.my_roster()) == 16

    reloaded = DraftState.load(path)   # crash-recovery resume
    assert reloaded.picks == ds.picks
    slots, _ = reloaded.roster_slots()
    assert len(slots) == 9             # a full starting lineup structure
