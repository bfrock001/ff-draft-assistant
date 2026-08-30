"""Round/roster-aware risk-dial suggestion (spec §8.3)."""
from strategy import suggest_risk


def test_early_rounds_balanced():
    assert suggest_risk(1, 9)[0] == "Balanced"   # protect the anchors
    assert suggest_risk(3, 7)[0] == "Balanced"


def test_full_starters_go_upside_even_midround():
    # once the 9 starters are set, every pick is a bench swing -> ceiling
    assert suggest_risk(6, 0)[0] == "Upside"


def test_late_rounds_upside():
    assert suggest_risk(10, 1)[0] == "Upside"
    assert suggest_risk(14, 3)[0] == "Upside"


def test_midrounds_building_starters_balanced():
    assert suggest_risk(5, 3)[0] == "Balanced"
    assert suggest_risk(9, 2)[0] == "Balanced"


def test_none_round_defaults_balanced():
    assert suggest_risk(None, 5)[0] == "Balanced"


def test_reason_is_nonempty():
    assert all(suggest_risk(r, o)[1] for r, o in [(1, 9), (6, 0), (12, 1), (5, 3)])
