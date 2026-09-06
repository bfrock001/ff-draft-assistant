"""Assemble the unified player board (§6) from the active snapshot.

Load-time / UI prep only. pandas is fine here and MUST NOT be used in the
simulation hot path (§9). Joins the consensus rankings (value + disagreement)
to proj_points and the ESPN rank, all on canonical player id.
"""
from __future__ import annotations

import pandas as pd

import snapshots
from ids import PlayerResolver, load_overrides
from loaders import OVERRIDES_PATH, POS_TO_CROSSWALK, load_crosswalk, read_rankings


def _resolve_ids(df: pd.DataFrame, resolver: PlayerResolver) -> list:
    ids = []
    for r in df.itertuples(index=False):
        pos = str(r.pos).upper()
        if pos == "DST":
            ids.append(f"DST_{str(r.team).upper()}")
        else:
            cid, _ = resolver.resolve(r.player, POS_TO_CROSSWALK.get(pos, pos), r.team)
            ids.append(cid)
    return ids


def load_board(snap_date: str | None = None) -> pd.DataFrame:
    date = snap_date or snapshots.active_snapshot()
    resolver = PlayerResolver(load_crosswalk(),
                              overrides=load_overrides(OVERRIDES_PATH))
    rk = read_rankings(snapshots.rankings_path(date))
    rk["canonical_id"] = _resolve_ids(rk, resolver)
    rk = rk.rename(columns={
        "rank_ecr": "rank", "player": "name", "rank_avg": "consensus_rank",
        "rank_std": "rank_sd", "adp": "fp_adp",
    })
    proj = pd.read_csv(snapshots.projections_path(date))[["canonical_id", "proj_points"]]
    espn = pd.read_csv(snapshots.espn_adp_path(date))[
        ["canonical_id", "espn_rank"]].drop_duplicates("canonical_id")
    board = (rk.merge(proj, on="canonical_id", how="left")
               .merge(espn, on="canonical_id", how="left")
               .sort_values("rank").reset_index(drop=True))
    cols = ["rank", "name", "pos", "team", "bye", "tier", "pos_rank",
            "consensus_rank", "rank_sd", "rank_best", "rank_worst",
            "proj_points", "espn_rank", "fp_adp", "canonical_id"]
    return board[[c for c in cols if c in board.columns]]
