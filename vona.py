"""VONA recommender — the Phase 2 safety net (spec §8 fallback, §11).

Deterministic. No simulation, no randomness: for each position it compares the
best player available NOW against the best likely to still be available at my
next pick (from ADP survival), and ranks by that points drop-off — weighted by
how much the position actually helps my roster. The TE-cliff falls out; and a
3rd RB when I already start two is down-weighted (it only helps FLEX). This is
the guaranteed-working draft-day fallback.
"""
from __future__ import annotations

import numpy as np

from config import FLEX_POSITIONS
from draft_state import fill_starting_slots
from pool import POSITIONS

FLEX_FACTOR = 0.5    # position's dedicated starter slots full, but FLEX still open
BENCH_FACTOR = 0.25  # starting lineup full -> depth only


def roster_openings(roster_positions: list[str]):
    """(dedicated_open, flex_open): positions with an unfilled non-FLEX starter
    slot, and whether the FLEX slot is still open."""
    slots, _ = fill_starting_slots([{"pos": p} for p in roster_positions])
    dedicated_open, flex_open = set(), False
    for label, filled in slots:
        if filled is None:
            if label == "FLEX":
                flex_open = True
            else:
                dedicated_open.add(label)
    return dedicated_open, flex_open


def roster_factor(pos: str, dedicated_open: set, flex_open: bool) -> float:
    if pos in dedicated_open:
        return 1.0
    if flex_open and pos in FLEX_POSITIONS:
        return FLEX_FACTOR
    return BENCH_FACTOR


def _reason(pool, pos, i, j, next_pick, vona, factor) -> str:
    name = pool.names[i]
    if factor == FLEX_FACTOR:
        note = f" You already start your {pos}s — this only helps FLEX."
    elif factor == BENCH_FACTOR:
        note = " Your starting lineup is full — this is bench depth."
    else:
        note = ""
    if next_pick is None:
        return f"{name} is the best {pos} available — last pick, take the best.{note}"
    if j is None:
        return (f"{pos} cliff — {name} is the best {pos} left and none are likely "
                f"to survive to your pick {next_pick}.{note}")
    return (f"{name} (proj {pool.proj_points[i]:.0f}); the best {pos} likely left "
            f"at pick {next_pick} is {pool.names[j]} (proj {pool.proj_points[j]:.0f})"
            f" — a {vona:.0f}-pt drop if you wait.{note}")


def vona_recommend(pool, drafted: set, current_pick: int, next_pick: int | None,
                   roster_positions: list[str], k: int = 3,
                   exclude: set = frozenset()) -> list[dict]:
    """Top-k positionally-diverse recommendations by roster-weighted VONA.

    Deterministic. Ranked by (VONA x roster factor), then best value available.
    ``exclude`` (player ids) are skipped as *my* candidates — opponents still
    take them (they still leave the board), they're just never recommended.
    """
    avail_idx = np.array([i for i, pid in enumerate(pool.ids) if pid not in drafted])
    if avail_idx.size == 0:
        return []

    # opponents picking between my current pick and my next pick (excluded players
    # still count here — opponents can draft them, so they still leave the board)
    gap_opp = len(pool) if next_pick is None else max(0, next_pick - current_pick - 1)
    order = avail_idx[np.argsort(pool.espn_adp[avail_idx], kind="stable")]
    survivors = set(order[gap_opp:].tolist())  # expected to last to my next pick

    dedicated_open, flex_open = roster_openings(roster_positions)

    rows = []
    for pos in POSITIONS:
        idxs = [i for i in avail_idx.tolist()
                if pool.positions[i] == pos and pool.ids[i] not in exclude]
        if not idxs:
            continue
        best_now = max(idxs, key=lambda i: pool.proj_points[i])
        surv = [i for i in idxs if i in survivors]
        best_next = max(surv, key=lambda i: pool.proj_points[i]) if surv else None
        vona = pool.proj_points[best_now] - (
            pool.proj_points[best_next] if best_next is not None else 0.0)
        factor = roster_factor(pos, dedicated_open, flex_open)
        rows.append({"pos": pos, "now": best_now, "next": best_next,
                     "vona": float(vona), "proj": float(pool.proj_points[best_now]),
                     "factor": factor, "adj": float(vona) * factor})

    # roster-weighted urgency first, then best value available (BPA fallback)
    rows.sort(key=lambda r: (-r["adj"], -r["proj"]))

    out = []
    for r in rows[:k]:
        i, j = r["now"], r["next"]
        out.append({
            "canonical_id": pool.ids[i], "name": pool.names[i], "pos": r["pos"],
            "team": pool.teams[i], "proj_points": float(pool.proj_points[i]),
            "vona": r["vona"], "adj_vona": r["adj"], "espn_adp": float(pool.espn_adp[i]),
            "next_name": pool.names[j] if j is not None else None,
            "next_proj": float(pool.proj_points[j]) if j is not None else None,
            "reasoning": _reason(pool, r["pos"], i, j, next_pick, r["vona"], r["factor"]),
        })
    return out
