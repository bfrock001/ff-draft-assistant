"""Draft-day heuristics / UI advice — kept pure (no Streamlit) so it's unit-
testable. Currently the round/roster-aware risk-dial suggestion (spec §8.3)."""
from __future__ import annotations


def suggest_risk(my_round: int | None, starters_open: int) -> tuple[str, str]:
    """Recommend a risk-dial setting from the draft context (round + roster fill).

    The driver is the cost of a bust: catastrophic on your early anchors, cheap
    on the bench — so protect the floor early, then chase ceiling once your
    starting lineup is set. Returns (setting, one-line reason).
    """
    if my_round is None:
        return "Balanced", "best expected value."
    if my_round <= 3:
        return "Balanced", "protect your anchors — elite picks are low-downside."
    if starters_open == 0:
        return "Upside", "your starters are set — swing for ceiling on the bench."
    if my_round >= 10:
        return "Upside", "late rounds — chase ceilings; floors barely matter now."
    return "Balanced", "building your starting core — best expected value."
