"""Offline "why" explainer (Phase 5 polish, §11).

Turns the board's own numbers — projection, analyst disagreement (rank_sd),
positional scarcity (the VONA drop-off), roster fit, and ADP survival — into a
plain-English rationale for a pick. No network, instant: the draft-day narrative
you'd otherwise ask an LLM for, generated locally.
"""
from __future__ import annotations

import numpy as np

from config import N_TEAMS
from pool import POSITIONS
from vona import roster_openings

DEEP = {"QB", "K", "DST"}   # positions you can usually wait on


def _ordinal(n: int) -> str:
    n = int(round(n))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def position_dropoff(pool, avail_idx, pos_code_val, my_pick, my_next_pick):
    """(best_now_idx, best_next_idx|None, drop_pts) for a position, using ADP
    survival to my next pick — the same model VONA uses."""
    idxs = [i for i in avail_idx if pool.pos_code[i] == pos_code_val]
    if not idxs:
        return None, None, 0.0
    best_now = max(idxs, key=lambda i: pool.proj_points[i])
    if my_next_pick is None:
        return best_now, None, float(pool.proj_points[best_now])
    gap = max(0, my_next_pick - my_pick - 1)
    survivors = set(sorted(avail_idx, key=lambda i: pool.espn_adp[i])[gap:])
    surv = [i for i in idxs if i in survivors]
    best_next = max(surv, key=lambda i: pool.proj_points[i]) if surv else None
    drop = float(pool.proj_points[best_now]
                 - (pool.proj_points[best_next] if best_next is not None else 0.0))
    return best_now, best_next, drop


def explain_candidate(pool, idx, drafted, roster_positions, my_pick, my_next_pick):
    """Return {'pos','name','lines'}: the reasons to take (or wait on) this player."""
    avail_idx = [i for i, pid in enumerate(pool.ids) if pid not in drafted]
    pcode = int(pool.pos_code[idx])
    pos = POSITIONS[pcode]
    name, proj, sd = pool.names[idx], pool.proj_points[idx], pool.rank_sd[idx]
    lines: list[str] = []

    # 1. value / rank
    pos_avail = sorted((i for i in avail_idx if pool.pos_code[i] == pcode),
                       key=lambda i: -pool.proj_points[i])
    if pos_avail and idx == pos_avail[0]:
        lines.append(f"{name} is the best {pos} available and {_ordinal(pool.consensus_rank[idx])} "
                     f"on the board — projected {proj:.0f} pts.")
    else:
        lines.append(f"{name} — {_ordinal(pool.consensus_rank[idx])} on the board, "
                     f"projected {proj:.0f} pts.")

    # 2. risk from analyst disagreement. rank_sd grows deeper in the draft, so
    # judge it against the SAFEST options at similar value (the 20th-pct spread
    # in a rank band) — that's what flags a risky pick when a safer, similar-
    # value option is on the board.
    cr = pool.consensus_rank[idx]
    band = [pool.rank_sd[i] for i in avail_idx if abs(pool.consensus_rank[i] - cr) <= 12]
    safe_ref = float(np.percentile(band, 20)) if band else sd
    if sd <= max(1.5, safe_ref * 1.4):
        lines.append("The analysts strongly agree on him — a safe, high-floor pick.")
    elif sd >= max(3.0, safe_ref * 2.2):
        lines.append(f"The analysts are split on him (rank spread ±{sd:.0f}) — "
                     "more boom/bust than the safer picks going around here.")

    # 3. positional scarcity (the VONA drop-off)
    _, best_next, drop = position_dropoff(pool, avail_idx, pcode, my_pick, my_next_pick)
    if my_next_pick is not None:
        if drop >= 25:
            bn = pool.names[best_next] if best_next is not None else "nobody comparable"
            lines.append(f"{pos} is thinning — wait to pick {my_next_pick} and the best {pos} "
                         f"left is ~{bn}, about {drop:.0f} pts less.")
        elif drop <= 12:
            lines.append(f"{pos} is deep right now — similar value should still be there at "
                         f"pick {my_next_pick} (only ~{drop:.0f} pts of drop-off).")

    # 4. roster fit
    dedicated_open, flex_open = roster_openings(roster_positions)
    if pos in dedicated_open:
        lines.append(f"Fills your open {pos} slot.")
    elif flex_open and pos in ("RB", "WR", "TE"):
        lines.append(f"You already start your {pos}s, so he'd go to FLEX rather than fill a "
                     "new starter.")
    else:
        lines.append("Your starters here are set — this would be bench depth.")

    # 5. positional-value caveat (why not a QB/K/DST early)
    round_now = (my_pick - 1) // N_TEAMS + 1
    if pos in DEEP and round_now <= 8:
        if pos == "QB":
            lines.append("Heads-up: QB is the deepest position — you can usually get a comparable "
                         "starter several rounds later, so an early pick here is a luxury.")
        else:
            lines.append(f"Heads-up: don't spend an early pick on {pos} — wait for the last rounds.")

    return {"pos": pos, "name": name, "lines": lines}
