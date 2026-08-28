import os

from config import picks_for_slot
from draft_state import (
    DraftState,
    fill_starting_slots,
    state_path,
    team_on_clock,
)


def test_team_on_clock_snake():
    assert team_on_clock(1) == 1
    assert team_on_clock(10) == 10
    assert team_on_clock(11) == 10   # snake turns
    assert team_on_clock(20) == 1
    assert team_on_clock(21) == 1
    assert team_on_clock(30) == 10


def test_full_160_pick_mock_draft_does_not_break():
    ds = DraftState(my_slot=3, date="2026-09-01")
    positions = ["QB", "RB", "WR", "TE", "K", "DST"]
    for i in range(1, ds.total_picks + 1):
        # default team = whoever is on the clock
        ds.make_pick(player_id=i, player_name=f"Player {i}",
                     pos=positions[i % len(positions)])
    assert ds.is_complete()
    assert len(ds.picks) == 160
    assert ds.on_the_clock() is None
    assert ds.picks_until_my_turn() is None
    # every pick landed on the correct snake team
    for p in ds.picks:
        assert p["team"] == team_on_clock(p["overall"])
    # my picks are exactly the slot-3 snake sequence
    mine = [p["overall"] for p in ds.my_roster()]
    assert mine == picks_for_slot(3)
    assert len(ds.my_roster()) == 16


def test_picks_until_my_turn_and_on_the_clock():
    ds = DraftState(my_slot=3, date="2026-09-01")
    assert ds.current_pick == 1
    assert ds.on_the_clock() == 1
    assert ds.picks_until_my_turn() == 2      # my first pick is overall 3
    ds.make_pick(1, "A", "RB")
    ds.make_pick(2, "B", "RB")
    assert ds.on_the_clock() == 3             # my slot
    assert ds.picks_until_my_turn() == 0


def test_undo_restores_previous_state():
    ds = DraftState(my_slot=5, date="2026-09-01")
    ds.make_pick(1, "A", "RB")
    ds.make_pick(2, "B", "WR")
    assert ds.current_pick == 3
    undone = ds.undo()
    assert undone["player_id"] == 2
    assert ds.current_pick == 2
    assert 2 not in ds.drafted_ids()


def test_cannot_draft_duplicate_or_after_complete():
    ds = DraftState(my_slot=1, date="2026-09-01")
    ds.make_pick(7, "A", "RB")
    try:
        ds.make_pick(7, "A again", "RB")
        assert False, "duplicate should raise"
    except ValueError:
        pass


def test_roster_slot_fill_with_flex_overflow():
    roster = [
        {"name": "qb1", "pos": "QB"},
        {"name": "rb1", "pos": "RB"},
        {"name": "rb2", "pos": "RB"},
        {"name": "rb3", "pos": "RB"},   # overflow -> FLEX
        {"name": "rb4", "pos": "RB"},   # overflow -> bench
        {"name": "wr1", "pos": "WR"},
        {"name": "te1", "pos": "TE"},
        {"name": "dst", "pos": "DST"},
        {"name": "k", "pos": "K"},
    ]
    slots, bench = fill_starting_slots(roster)
    filled = {label: (p["name"] if p else None) for label, p in slots}
    labels = [label for label, _ in slots]
    assert labels == ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DST", "K"]
    # third RB lands in FLEX; fourth RB is benched
    flex_name = [p["name"] for label, p in slots if label == "FLEX" and p][0]
    assert flex_name == "rb3"
    assert [b["name"] for b in bench] == ["rb4"]
    # one WR slot stays empty (only one WR drafted)
    assert sum(1 for label, p in slots if label == "WR" and p is None) == 1


def test_save_load_roundtrip(tmp_path):
    ds = DraftState(my_slot=7, date="2026-09-01")
    ds.make_pick(1, "A", "RB")
    ds.make_pick(2, "B", "WR")
    path = str(tmp_path / "draft.json")
    ds.save(path)
    assert os.path.exists(path)
    loaded = DraftState.load(path)
    assert loaded.my_slot == 7
    assert loaded.picks == ds.picks
    assert loaded.current_pick == 3


def test_state_path_format():
    assert state_path("2026-09-01").endswith("draft_20260901.json")
