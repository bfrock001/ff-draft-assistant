"""League configuration and snake-draft pick math (spec §1).

Hard defaults for the league. Change values here to reconfigure. This module is
kept free of any data/IO so it is safe to import anywhere, including the
simulation hot path.
"""
from __future__ import annotations

# --- League (spec §1) ---
N_TEAMS = 10
N_ROUNDS = 16
TOTAL_PICKS = N_TEAMS * N_ROUNDS  # 160
DRAFT_TYPE = "snake"
KEEPERS = 0

ROSTER_SIZE = 16
N_BENCH = 7

# Starting lineup: 1 QB, 2 RB, 2 WR, 1 TE, 1 FLEX (RB/WR/TE), 1 D/ST, 1 K.
STARTERS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "DST": 1, "K": 1}
N_STARTERS = sum(STARTERS.values())  # 9
FLEX_POSITIONS = ("RB", "WR", "TE")

# Recognized positions. D/ST is spelled "DST" internally.
POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")

# Opponent-model roster sanity caps (spec §7), kept here so config is one place.
ROSTER_CAPS = {"QB": 2, "TE": 2, "K": 1, "DST": 1}
NO_KDST_BEFORE_ROUND = 13  # no K or D/ST may be drafted before this round

# ESPN league identity for the pre-draft ESPN board refresh (spec §3.2). Used
# only by the "Update ESPN" button — never during the draft itself.
ESPN_LEAGUE_ID = 840743625
ESPN_SEASON = 2026


def pick_number(slot: int, rnd: int, n_teams: int = N_TEAMS) -> int:
    """Overall pick number for a 1-indexed draft ``slot`` in round ``rnd`` (§1).

    odd round:  pick = (rnd-1)*n_teams + slot
    even round: pick = (rnd-1)*n_teams + (n_teams + 1 - slot)   # snake back
    """
    if not (1 <= slot <= n_teams):
        raise ValueError(f"slot must be in 1..{n_teams}, got {slot}")
    if rnd < 1:
        raise ValueError(f"round must be >= 1, got {rnd}")
    base = (rnd - 1) * n_teams
    if rnd % 2 == 1:
        return base + slot
    return base + (n_teams + 1 - slot)


def picks_for_slot(slot: int, n_rounds: int = N_ROUNDS,
                   n_teams: int = N_TEAMS) -> list[int]:
    """All of my overall pick numbers, in draft order, for a given slot."""
    return [pick_number(slot, r, n_teams) for r in range(1, n_rounds + 1)]


def picks_until_next_turn(slot: int, after_pick: int, n_rounds: int = N_ROUNDS,
                          n_teams: int = N_TEAMS) -> int | None:
    """Real gap (in overall picks) to my next turn strictly after ``after_pick``.

    This is the *actual* alternating snake gap (e.g. slot 3: 15 then 5), never an
    average — knowing exactly who survives to the next turn is the whole point of
    the app. Returns None if I have no remaining pick after ``after_pick``.
    """
    for p in picks_for_slot(slot, n_rounds, n_teams):
        if p > after_pick:
            return p - after_pick
    return None
