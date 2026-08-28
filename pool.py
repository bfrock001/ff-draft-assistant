"""Player pool as NumPy arrays indexed by integer id (spec §9).

Built once at load from the board (pandas is fine here). Everything the engines
touch per-candidate/per-sim is a plain NumPy array indexed 0..N-1 — no pandas or
Polars in the compute path. Phase 2 (VONA) and Phase 3 (simulation) share this.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")


@dataclass
class PlayerPool:
    ids: list           # index -> canonical_id
    names: list
    teams: list
    positions: np.ndarray   # dtype=object, per-player position string
    proj_points: np.ndarray  # float, missing values filled (see from_board)
    espn_adp: np.ndarray     # float rank; missing -> "late" so they survive
    consensus_rank: np.ndarray
    rank_sd: np.ndarray
    points_sd: np.ndarray   # §6 bridge: rank disagreement mapped into points
    id_to_idx: dict = field(init=False)
    pos_code: np.ndarray = field(init=False)  # int index into POSITIONS

    def __post_init__(self):
        self.id_to_idx = {pid: i for i, pid in enumerate(self.ids)}
        code = {p: i for i, p in enumerate(POSITIONS)}
        self.pos_code = np.array([code.get(p, -1) for p in self.positions], dtype=int)

    def __len__(self):
        return len(self.ids)

    @classmethod
    def from_records(cls, recs: list[dict]) -> "PlayerPool":
        """Build directly from a list of dicts (used by tests, no pandas)."""
        return cls(
            ids=[r["id"] for r in recs],
            names=[r.get("name", r["id"]) for r in recs],
            teams=[r.get("team", "") for r in recs],
            positions=np.array([r["pos"] for r in recs], dtype=object),
            proj_points=np.array([r["proj_points"] for r in recs], dtype=float),
            espn_adp=np.array([r["espn_adp"] for r in recs], dtype=float),
            consensus_rank=np.array(
                [r.get("consensus_rank", i + 1) for i, r in enumerate(recs)],
                dtype=float),
            rank_sd=np.array([r.get("rank_sd", 0.0) for r in recs], dtype=float),
            points_sd=np.array([r.get("points_sd", 0.0) for r in recs], dtype=float),
        )

    @classmethod
    def from_board(cls, board) -> "PlayerPool":
        import pandas as pd

        df = board.copy()
        # stable unique player id: canonical_id, else a name-based fallback
        df["pid"] = [c if isinstance(c, str) else f"NM_{n}"
                     for c, n in zip(df["canonical_id"], df["name"])]
        df = (df.sort_values("rank").drop_duplicates("pid", keep="first")
                .reset_index(drop=True))

        proj = df["proj_points"].to_numpy(dtype=float).copy()
        cons = df["consensus_rank"].to_numpy(dtype=float)
        pos = df["pos"].to_numpy(dtype=object)
        # fill missing proj by interpolating the position's points-vs-rank curve (§6)
        for P in np.unique(pos):
            m = pos == P
            known = m & ~np.isnan(proj)
            miss = m & np.isnan(proj)
            if miss.any() and known.sum() >= 2:
                xk, fk = cons[known], proj[known]
                o = np.argsort(xk)
                proj[miss] = np.interp(cons[miss], xk[o], fk[o])
            elif miss.any():
                proj[miss] = float(np.nanmin(proj[known])) if known.any() else 0.0
        proj = np.nan_to_num(proj, nan=0.0)

        adp = df["espn_rank"].to_numpy(dtype=float) if "espn_rank" in df else np.full(len(df), np.nan)
        adp = np.where(np.isnan(adp), 900.0 + cons, adp)  # missing -> late

        # points_sd (§6): map rank disagreement into points via the position's
        # points-vs-rank slope. MODELING CHOICE beyond the spec's literal words —
        # sanity-check the magnitudes against real spreads.
        sd_rank = (df["rank_sd"].to_numpy(dtype=float)
                   if "rank_sd" in df else np.zeros(len(df)))
        sd_rank = np.nan_to_num(sd_rank, nan=0.0)
        points_sd = np.zeros(len(df))
        for P in np.unique(pos):
            m = np.where(pos == P)[0]
            if m.size < 2:
                continue
            o = m[np.argsort(cons[m])]
            p_o, r_o = proj[o], cons[o]
            n, w = len(o), 3
            for j in range(n):
                lo, hi = max(0, j - w), min(n - 1, j + w)
                dr = r_o[hi] - r_o[lo]
                dr = dr if dr > 0 else max(hi - lo, 1)  # points-per-rank over the window
                points_sd[o[j]] = abs(p_o[lo] - p_o[hi]) / dr * sd_rank[o[j]]
        points_sd = np.clip(points_sd, 3.0, 60.0)   # floor + sane cap (season sd)

        return cls(
            ids=df["pid"].tolist(),
            names=df["name"].tolist(),
            teams=df["team"].tolist() if "team" in df else [""] * len(df),
            positions=pos,
            proj_points=proj,
            espn_adp=adp,
            consensus_rank=cons,
            rank_sd=sd_rank,
            points_sd=points_sd,
        )
