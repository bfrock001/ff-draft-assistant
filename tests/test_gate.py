"""Phase 0 acceptance gate as a regression test (spec §11).

Integration test: needs the cached nflreadpy crosswalk and the rankings
snapshot. Skips cleanly where the crosswalk cache is absent (fresh clone) or
polars isn't installed, so the pure-logic suite always runs.
"""
import os

import pytest

pytest.importorskip("polars")

CROSSWALK = "data/cache/ff_playerids.parquet"


@pytest.mark.skipif(
    not os.path.exists(CROSSWALK),
    reason="crosswalk cache missing; run `python loaders.py` to fetch+cache it",
)
def test_zero_unmatched_in_top_200():
    from loaders import run_gate
    assert run_gate(top_n=200) == 0
