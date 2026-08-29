"""Projection loader regression tests (spec §3.1, §4, §6).

Integration: needs the crosswalk cache and the projection snapshot. Skips
cleanly where they're absent so the pure-logic suite always runs.
"""
import os

import pytest

pytest.importorskip("polars")

CROSSWALK = "data/cache/ff_playerids.parquet"
SNAP_DIR = "data/raw/2026-08-28"
PROJ = f"{SNAP_DIR}/proj_rb.csv"

pytestmark = pytest.mark.skipif(
    not (os.path.exists(CROSSWALK) and os.path.exists(PROJ)),
    reason="crosswalk cache or projection snapshot missing",
)


def test_our_scoring_reproduces_export_half_ppr():
    # For RB/WR/TE (no INT/FG differences), our §4 minus 0.5/reception must
    # reproduce FantasyPros' half-PPR FPTS -> proves the stat parsing is correct.
    from projections import build
    matched, _ = build(SNAP_DIR)
    worst = max(abs((m["proj_points"] - 0.5 * m["rec"]) - m["file_fpts"])
                for m in matched if m["pos"] in ("RB", "WR", "TE"))
    assert worst < 1.0, f"max half-PPR mismatch {worst}"


def test_top200_all_have_a_projection():
    from ids import PlayerResolver, load_overrides
    from loaders import (OVERRIDES_PATH, load_crosswalk, load_rankings,
                         resolve_rankings)
    from projections import build
    matched, _ = build(SNAP_DIR)
    proj_ids = {m["canonical_id"] for m in matched}
    resolver = PlayerResolver(load_crosswalk(),
                              overrides=load_overrides(OVERRIDES_PATH))
    rmatched, _ = resolve_rankings(load_rankings(), resolver)
    missing = [m for m in rmatched if m["rank"] <= 200
               and m["canonical_id"] not in proj_ids]
    assert missing == [], f"top-200 without a projection: {missing}"
