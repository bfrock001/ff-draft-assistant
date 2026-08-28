import pytest

from config import (
    N_ROUNDS,
    N_TEAMS,
    TOTAL_PICKS,
    pick_number,
    picks_for_slot,
    picks_until_next_turn,
)


def test_slot3_sequence():
    assert picks_for_slot(3) == [
        3, 18, 23, 38, 43, 58, 63, 78, 83, 98, 103, 118, 123, 138, 143, 158
    ]


def test_slot10_sequence():
    assert picks_for_slot(10) == [
        10, 11, 30, 31, 50, 51, 70, 71, 90, 91, 110, 111, 130, 131, 150, 151
    ]


def test_slot1_sequence():
    assert picks_for_slot(1) == [
        1, 20, 21, 40, 41, 60, 61, 80, 81, 100, 101, 120, 121, 140, 141, 160
    ]


def test_pick_number_basics():
    assert pick_number(3, 1) == 3
    assert pick_number(3, 2) == 18
    assert pick_number(1, 1) == 1
    assert pick_number(10, 1) == 10


def test_all_picks_are_a_permutation_of_1_to_160():
    seen: list[int] = []
    for slot in range(1, N_TEAMS + 1):
        seen.extend(picks_for_slot(slot))
    assert len(seen) == TOTAL_PICKS
    assert sorted(seen) == list(range(1, TOTAL_PICKS + 1))


def test_alternating_gaps_slot3():
    assert picks_until_next_turn(3, 3) == 15   # long gap
    assert picks_until_next_turn(3, 18) == 5   # short gap
    assert picks_until_next_turn(3, 158) is None  # no pick after the last


def test_each_slot_has_n_rounds_picks():
    for slot in range(1, N_TEAMS + 1):
        assert len(picks_for_slot(slot)) == N_ROUNDS


def test_invalid_slot_raises():
    with pytest.raises(ValueError):
        pick_number(0, 1)
    with pytest.raises(ValueError):
        pick_number(N_TEAMS + 1, 1)
