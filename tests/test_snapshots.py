"""Snapshot discovery / selection / path helpers (spec §3.5)."""
import os

import snapshots


def _mk(root, date, files):
    d = os.path.join(root, date)
    os.makedirs(d)
    for fn in files:
        with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
            f.write("x\n")
    return d


def test_list_and_latest_newest_first(tmp_path):
    root = str(tmp_path)
    _mk(root, "2026-01-01", ["rankings.csv"])
    _mk(root, "2026-03-03", ["rankings.csv"])
    os.makedirs(os.path.join(root, "not-a-date"))  # ignored
    assert snapshots.list_snapshots(root) == ["2026-03-03", "2026-01-01"]
    assert snapshots.latest_snapshot(root) == "2026-03-03"


def test_active_defaults_to_newest_then_honors_override(tmp_path, monkeypatch):
    root = str(tmp_path)
    _mk(root, "2026-01-01", ["rankings.csv"])
    _mk(root, "2026-03-03", ["rankings.csv"])
    monkeypatch.setattr(snapshots, "ACTIVE_FILE", str(tmp_path / "active"))
    assert snapshots.active_snapshot(root) == "2026-03-03"  # newest by default
    snapshots.set_active_snapshot("2026-01-01", root)
    assert snapshots.active_snapshot(root) == "2026-01-01"  # honored override
    # a stale/unknown override falls back to newest
    with open(snapshots.ACTIVE_FILE, "w", encoding="utf-8") as f:
        f.write("2099-09-09\n")
    assert snapshots.active_snapshot(root) == "2026-03-03"


def test_path_helpers_prefer_standard_then_glob(tmp_path):
    root = str(tmp_path)
    # dated-name originals (like the 2026-08-28 folder)
    _mk(root, "2026-08-28", ["rankings_ppr_consensus_2026-08-28.csv",
                             "espn_ranks_2026-08-28.csv"])
    assert snapshots.rankings_path("2026-08-28", root).endswith(
        "rankings_ppr_consensus_2026-08-28.csv")
    assert snapshots.espn_raw_path("2026-08-28", root).endswith(
        "espn_ranks_2026-08-28.csv")
    # standardized names win when present
    _mk(root, "2026-09-09", ["rankings.csv", "espn_ranks.csv"])
    assert snapshots.rankings_path("2026-09-09", root).endswith("rankings.csv")
    assert snapshots.espn_raw_path("2026-09-09", root).endswith("espn_ranks.csv")


def test_age_days():
    import datetime
    today = datetime.date(2026, 9, 9)
    assert snapshots.age_days("2026-09-02", today) == 7
    assert snapshots.age_days("2026-09-09", today) == 0
