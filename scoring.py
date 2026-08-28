"""PPR scoring engine (spec §4).

Pure function ``score_stat_line(stat) -> float``. Used for BOTH historical points
and for converting projected stat lines into projected points, so the two are
always consistent. A source's precomputed fantasy points are never used (§3.3).

A stat line is a mapping of stat name -> value; every key is optional and
defaults to 0, so one function scores every position. Recognized keys:

  Passing:   pass_yds, pass_td, pass_int, pass_2pt
  Rush/Rec:  rush_yds, rush_td, rush_2pt, rec, rec_yds, rec_td, rec_2pt
  Misc:      two_pt (generic), fumbles_lost
  Kicking:   xpm; and EITHER fg_distances=[yards, ...] OR the banded counts
             fg_0_39 / fg_40_49 / fg_50_plus
  D/ST:      dst_sacks, dst_int, dst_fumble_rec, dst_safety, dst_blocked_kick,
             dst_td, dst_points_allowed
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

# --- Scoring constants (spec §4) ---
PASS_YDS_PER_PT = 0.04
PASS_TD = 4.0
PASS_INT = -2.0
RUSH_REC_YDS_PER_PT = 0.1
RECEPTION = 1.0
RUSH_REC_TD = 6.0
TWO_PT = 2.0
FUMBLE_LOST = -2.0
PAT = 1.0
FG_0_39 = 3.0
FG_40_49 = 4.0
FG_50_PLUS = 5.0
DST_SACK = 1.0
DST_INT = 2.0
DST_FUMBLE_REC = 2.0
DST_SAFETY = 2.0
DST_BLOCKED_KICK = 2.0
DST_TD = 6.0


def field_goal_points(distances: Sequence[float]) -> float:
    """Points for a sequence of *made* FG distances (yards), bucketed by band."""
    pts = 0.0
    for d in distances:
        if d >= 50:
            pts += FG_50_PLUS
        elif d >= 40:
            pts += FG_40_49
        else:
            pts += FG_0_39
    return pts


def dst_points_allowed_points(points_allowed: int) -> float:
    """Tiered D/ST points-allowed score (spec §4)."""
    pa = points_allowed
    if pa <= 0:
        return 5.0
    if pa <= 6:
        return 4.0
    if pa <= 13:
        return 3.0
    if pa <= 17:
        return 1.0
    if pa <= 27:
        return 0.0
    if pa <= 34:
        return -1.0
    return -3.0


def score_stat_line(stat: Mapping) -> float:
    """Convert one stat line into PPR points (spec §4). Missing keys count as 0."""
    def g(key: str) -> float:
        return stat.get(key, 0) or 0

    pts = 0.0

    # Passing
    pts += g("pass_yds") * PASS_YDS_PER_PT
    pts += g("pass_td") * PASS_TD
    pts += g("pass_int") * PASS_INT

    # Rushing + receiving
    pts += g("rush_yds") * RUSH_REC_YDS_PER_PT
    pts += g("rush_td") * RUSH_REC_TD
    pts += g("rec") * RECEPTION
    pts += g("rec_yds") * RUSH_REC_YDS_PER_PT
    pts += g("rec_td") * RUSH_REC_TD

    # Two-point conversions (passing / rushing / receiving all worth 2)
    pts += (g("pass_2pt") + g("rush_2pt") + g("rec_2pt") + g("two_pt")) * TWO_PT

    # Fumbles lost
    pts += g("fumbles_lost") * FUMBLE_LOST

    # Kicking
    pts += g("xpm") * PAT
    fg_distances = stat.get("fg_distances")
    if fg_distances:
        pts += field_goal_points(fg_distances)
    pts += g("fg_0_39") * FG_0_39
    pts += g("fg_40_49") * FG_40_49
    pts += g("fg_50_plus") * FG_50_PLUS

    # D/ST
    pts += g("dst_sacks") * DST_SACK
    pts += g("dst_int") * DST_INT
    pts += g("dst_fumble_rec") * DST_FUMBLE_REC
    pts += g("dst_safety") * DST_SAFETY
    pts += g("dst_blocked_kick") * DST_BLOCKED_KICK
    pts += g("dst_td") * DST_TD
    if stat.get("dst_points_allowed") is not None:
        pts += dst_points_allowed_points(stat["dst_points_allowed"])

    return pts
