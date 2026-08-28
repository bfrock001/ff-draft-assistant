"""Draft state model (spec §10).

Pure, UI-agnostic, and testable. Tracks all 160 picks, who took whom, my roster
and its starting-slot fill, supports undo, and persists to JSON after every pick
for crash recovery / resume.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from config import (
    FLEX_POSITIONS,
    N_ROUNDS,
    N_TEAMS,
    STARTERS,
    TOTAL_PICKS,
    picks_for_slot,
)

# Starting-lineup slots in display order (FLEX after the base RB/WR/TE).
STARTER_SLOTS: list[tuple[str, tuple[str, ...]]] = (
    [("QB", ("QB",))]
    + [("RB", ("RB",))] * STARTERS["RB"]
    + [("WR", ("WR",))] * STARTERS["WR"]
    + [("TE", ("TE",))]
    + [("FLEX", FLEX_POSITIONS)]
    + [("DST", ("DST",))]
    + [("K", ("K",))]
)


def team_on_clock(overall_pick: int, n_teams: int = N_TEAMS) -> int:
    """1-indexed team drafting at ``overall_pick`` in a snake draft."""
    rnd = (overall_pick - 1) // n_teams + 1
    pos_in_round = (overall_pick - 1) % n_teams  # 0-indexed
    if rnd % 2 == 1:
        return pos_in_round + 1
    return n_teams - pos_in_round


def fill_starting_slots(players: list[dict]):
    """Greedily fill the starting lineup from my picks (in draft order).

    Returns (slots, bench): slots is a list of (label, player_or_None) in
    STARTER_SLOTS order; bench is the overflow.
    """
    slots = [[label, elig, None] for label, elig in STARTER_SLOTS]
    bench = []
    for p in players:
        for slot in slots:
            if slot[2] is None and p["pos"] in slot[1]:
                slot[2] = p
                break
        else:
            bench.append(p)
    return [(s[0], s[2]) for s in slots], bench


@dataclass
class DraftState:
    my_slot: int
    date: str
    n_teams: int = N_TEAMS
    n_rounds: int = N_ROUNDS
    picks: list[dict] = field(default_factory=list)

    # --- derived views ---
    @property
    def total_picks(self) -> int:
        return self.n_teams * self.n_rounds

    @property
    def current_pick(self) -> int:  # overall pick number about to be made
        return len(self.picks) + 1

    @property
    def current_round(self) -> int:
        return (self.current_pick - 1) // self.n_teams + 1

    def is_complete(self) -> bool:
        return len(self.picks) >= self.total_picks

    def on_the_clock(self) -> int | None:
        if self.is_complete():
            return None
        return team_on_clock(self.current_pick, self.n_teams)

    def my_pick_numbers(self) -> list[int]:
        return picks_for_slot(self.my_slot, self.n_rounds, self.n_teams)

    def picks_until_my_turn(self) -> int | None:
        """0 if I'm on the clock; None if I have no picks left."""
        for p in self.my_pick_numbers():
            if p >= self.current_pick:
                return p - self.current_pick
        return None

    def drafted_ids(self) -> set:
        return {p["player_id"] for p in self.picks}

    def my_roster(self) -> list[dict]:
        return [p for p in self.picks if p["team"] == self.my_slot]

    def roster_slots(self):
        return fill_starting_slots(self.my_roster())

    # --- mutations ---
    def make_pick(self, player_id, player_name, pos, team: int | None = None) -> dict:
        if self.is_complete():
            raise ValueError("draft is already complete")
        if player_id in self.drafted_ids():
            raise ValueError(f"{player_name} is already drafted")
        pick = {
            "overall": self.current_pick,
            "round": self.current_round,
            "team": self.on_the_clock() if team is None else int(team),
            "player_id": player_id,
            "player_name": player_name,
            "pos": pos,
        }
        self.picks.append(pick)
        return pick

    def undo(self) -> dict | None:
        return self.picks.pop() if self.picks else None

    # --- persistence (spec §10) ---
    def to_dict(self) -> dict:
        return {
            "my_slot": self.my_slot, "date": self.date, "n_teams": self.n_teams,
            "n_rounds": self.n_rounds, "picks": self.picks,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DraftState":
        return cls(my_slot=d["my_slot"], date=d["date"], n_teams=d["n_teams"],
                   n_rounds=d["n_rounds"], picks=list(d["picks"]))

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
        os.replace(tmp, path)  # atomic; a crash mid-write never corrupts state

    @classmethod
    def load(cls, path: str) -> "DraftState":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


def state_path(date: str, directory: str = "state") -> str:
    return os.path.join(directory, f"draft_{date.replace('-', '')}.json")
