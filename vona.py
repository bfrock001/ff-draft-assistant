"""VONA recommender — the Phase 2 safety net (spec §8 fallback, §11).

Deterministic. No simulation, no randomness: for each position it compares the
best player available NOW against the best likely to still be available at my
next pick (from ADP survival), and ranks by that points drop-off. The TE-cliff
falls out — a steep positional drop that won't survive scores highest. This is
the guaranteed-working draft-day fallback.
"""
from __future__ import annotations

import numpy as np

from draft_state import fill_starting_slots
from pool import POSITIONS


def needed_positions(roster_positions: list[str]) -> set[str]:
    """Positions that can still fill an open starting slot (FLEX included).

    Empty set means every starter slot is filled (draft is now about bench
    depth), which the recommender treats as "all positions in play".
    """
    slots, _ = fill_starting_slots([{"pos": p} for p in roster_positions])
    needed: set[str] = set()
    for label, filled in slots:
        if filled is None:
            needed.update(("RB", "WR", "TE") if label == "FLEX" else (label,))
    return needed


def _reason(pool, pos, i, j, next_pick, vona) -> str:
    name = pool.names[i]
    if next_pick is None:
        return f"{name} is the best {pos} available — last pick, take the best."
    if j is None:
        return (f"{pos} cliff — {name} is the best {pos} left and none are likely "
                f"to survive to your pick {next_pick}.")
    return (f"{name} (proj {pool.proj_points[i]:.0f}); the best {pos} likely left "
            f"at pick {next_pick} is {pool.names[j]} (proj {pool.proj_points[j]:.0f})"
            f" — a {vona:.0f}-pt drop if you wait.")


def vona_recommend(pool, drafted: set, current_pick: int, next_pick: int | None,
                   roster_positions: list[str], k: int = 3) -> list[dict]:
    """Top-k positionally-diverse recommendations by VONA. Deterministic."""
    avail_idx = np.array([i for i, pid in enumerate(pool.ids) if pid not in drafted])
    if avail_idx.size == 0:
        return []

    # opponents picking between my current pick and my next pick
    gap_opp = len(pool) if next_pick is None else max(0, next_pick - current_pick - 1)
    order = avail_idx[np.argsort(pool.espn_adp[avail_idx], kind="stable")]
    survivors = set(order[gap_opp:].tolist())  # expected to last to my next pick

    needed = needed_positions(roster_positions)
    all_in_play = len(needed) == 0

    rows = []
    for pos in POSITIONS:
        idxs = [i for i in avail_idx.tolist() if pool.positions[i] == pos]
        if not idxs:
            continue
        best_now = max(idxs, key=lambda i: pool.proj_points[i])
        surv = [i for i in idxs if i in survivors]
        best_next = max(surv, key=lambda i: pool.proj_points[i]) if surv else None
        vona = pool.proj_points[best_now] - (
            pool.proj_points[best_next] if best_next is not None else 0.0)
        rows.append({"pos": pos, "now": best_now, "next": best_next,
                     "vona": float(vona), "proj": float(pool.proj_points[best_now]),
                     "needed": all_in_play or pos in needed})

    # needed positions first, then steepest drop-off, then best value available
    # (so with nothing scarce it degrades to best-player-available)
    rows.sort(key=lambda r: (not r["needed"], -r["vona"], -r["proj"]))

    out = []
    for r in rows[:k]:
        i, j = r["now"], r["next"]
        out.append({
            "canonical_id": pool.ids[i], "name": pool.names[i], "pos": r["pos"],
            "team": pool.teams[i], "proj_points": float(pool.proj_points[i]),
            "vona": r["vona"], "espn_adp": float(pool.espn_adp[i]),
            "next_name": pool.names[j] if j is not None else None,
            "next_proj": float(pool.proj_points[j]) if j is not None else None,
            "reasoning": _reason(pool, r["pos"], i, j, next_pick, r["vona"]),
        })
    return out
