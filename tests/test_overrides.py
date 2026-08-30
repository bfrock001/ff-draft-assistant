"""Manual override overlay (Increment 2): persistence + board application."""
import pandas as pd

import overrides


def test_save_load_roundtrip(tmp_path):
    p = str(tmp_path / "ov.csv")
    ov = {"A": {"proj_points": 380.0},
          "B": {"consensus_rank": 12.0, "exclude": True},
          "C": {"exclude": True}}
    overrides.save(ov, p)
    assert overrides.load(p) == ov


def test_load_missing_is_empty(tmp_path):
    assert overrides.load(str(tmp_path / "nope.csv")) == {}


def test_excluded_ids():
    ov = {"A": {"proj_points": 1.0}, "B": {"exclude": True}, "C": {"exclude": True}}
    assert overrides.excluded_ids(ov) == {"B", "C"}


def test_apply_overrides_values_but_keeps_excluded_rows():
    board = pd.DataFrame({
        "canonical_id": ["A", "B", "C"],
        "proj_points": [100.0, 200.0, 300.0],
        "consensus_rank": [1.0, 2.0, 3.0],
    })
    ov = {"A": {"proj_points": 150.0}, "C": {"consensus_rank": 1.5, "exclude": True}}
    out = overrides.apply(board, ov)
    assert out["proj_points"].tolist() == [150.0, 200.0, 300.0]
    assert out["consensus_rank"].tolist() == [1.0, 2.0, 1.5]
    assert len(out) == 3          # exclusion never drops rows (engines handle it)


def test_apply_no_overrides_is_identity():
    board = pd.DataFrame({"canonical_id": ["A"], "proj_points": [1.0],
                          "consensus_rank": [1.0]})
    assert overrides.apply(board, {}) is board


def test_signature_changes_with_content(tmp_path):
    p = str(tmp_path / "ov.csv")
    assert overrides.signature(p) == "none"
    overrides.save({"A": {"exclude": True}}, p)
    s1 = overrides.signature(p)
    overrides.save({"A": {"exclude": True}, "B": {"proj_points": 5.0}}, p)
    assert overrides.signature(p) != s1 and s1 != "none"
