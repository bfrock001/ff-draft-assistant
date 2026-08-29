"""Data loaders (spec §3) and the Phase 0 player-ID resolution gate (§5).

Reads local snapshot files plus the cached nflreadpy crosswalk. The crosswalk is
fetched once (first run / refresh) and cached to data/cache/; nothing here needs
the network at app runtime.

Notes from the real data:
- Kickers are position "PK" in the crosswalk, "K" in our rankings.
- Team D/ST are not players and are absent from the crosswalk -> resolved by team.
- Crosswalk team codes differ from FantasyPros (GBP vs GB, JAC, LVR, ...), so
  the (name, pos, team) exact tier rarely hits; the (name, pos) fallback carries
  the load. That is expected and safe.
"""
from __future__ import annotations

import csv
import os

import polars as pl

from ids import PlayerResolver, load_overrides

CACHE_CROSSWALK = "data/cache/ff_playerids.parquet"
OVERRIDES_PATH = "data/manual_id_overrides.csv"
UNMATCHED_PATH = "data/unmatched.csv"

CROSSWALK_POS = ("QB", "RB", "WR", "TE", "PK")
# rankings position -> crosswalk position
POS_TO_CROSSWALK = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "PK"}


def ensure_crosswalk_cached(path: str = CACHE_CROSSWALK) -> None:
    """Fetch load_ff_playerids() and cache to parquet on first run only.

    This is the one network touch (dev/refresh time); every later run reads the
    local parquet, so the app runtime stays fully offline (spec §3.3).
    """
    if os.path.exists(path):
        return
    import nflreadpy as nfl  # imported lazily so pure-logic use needs no network dep
    os.makedirs(os.path.dirname(path), exist_ok=True)
    nfl.load_ff_playerids().write_parquet(path)


def load_crosswalk(path: str = CACHE_CROSSWALK) -> list[dict]:
    """Load the cached crosswalk as resolver rows (id=mfl_id, name, pos, team).

    Sorted most-recent-season-first so the current row wins first-writer-wins for
    a given (name, position).
    """
    ensure_crosswalk_cached(path)
    df = pl.read_parquet(path)
    if "db_season" in df.columns:
        df = df.sort("db_season", descending=True, nulls_last=True)
    df = df.filter(pl.col("position").is_in(list(CROSSWALK_POS)))
    players = []
    for r in df.iter_rows(named=True):
        if r["mfl_id"] is None or r["name"] is None:
            continue
        players.append({
            "id": str(r["mfl_id"]),
            "name": r["name"],
            "pos": r["position"],
            "team": r["team"],
        })
    return players


def load_rankings(path: str | None = None) -> list[dict]:
    """Load a consensus rankings snapshot, sorted by consensus rank (rank_ecr).

    Defaults to the active snapshot's rankings file.
    """
    if path is None:
        import snapshots
        path = snapshots.rankings_path(snapshots.active_snapshot())
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "rank": int(r["rank_ecr"]),
                "name": r["player"],
                "pos": r["pos"].upper(),
                "team": r["team"],
            })
    rows.sort(key=lambda x: x["rank"])
    return rows


def resolve_rankings(rankings: list[dict], resolver: PlayerResolver):
    """Resolve each ranking row -> canonical id. Returns (matched, unmatched)."""
    matched, unmatched = [], []
    for row in rankings:
        pos = row["pos"]
        if pos == "DST":
            # team defenses aren't in the player crosswalk; identify by team
            matched.append({**row, "canonical_id": f"DST_{row['team'].upper()}",
                            "method": "dst_team"})
            continue
        xpos = POS_TO_CROSSWALK.get(pos, pos)
        cid, method = resolver.resolve(row["name"], xpos, row["team"])
        if cid is None:
            unmatched.append(row)
        else:
            matched.append({**row, "canonical_id": cid, "method": method})
    return matched, unmatched


def write_unmatched(unmatched: list[dict], path: str = UNMATCHED_PATH) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "name", "pos", "team"])
        for r in unmatched:
            w.writerow([r["rank"], r["name"], r["pos"], r["team"]])


def gate_report(rankings_path: str | None = None, top_n: int = 200,
                write: bool = True) -> dict:
    """Resolve a rankings file against the crosswalk and summarize the ID gate.

    Returns a dict with counts, per-method breakdown for the top N, and the list
    of unmatched top-N players (the Phase 0 acceptance number — must be empty).
    Pure/programmatic (the refresh flow calls this); ``write`` controls whether
    data/unmatched.csv is (re)written.
    """
    overrides = load_overrides(OVERRIDES_PATH) if os.path.exists(OVERRIDES_PATH) else {}
    resolver = PlayerResolver(load_crosswalk(), overrides=overrides)
    rankings = load_rankings(rankings_path)
    matched, unmatched = resolve_rankings(rankings, resolver)
    if write:
        write_unmatched(unmatched)

    top_unmatched = [r for r in unmatched if r["rank"] <= top_n]
    methods: dict[str, int] = {}
    for m in matched:
        if m["rank"] <= top_n:
            methods[m["method"]] = methods.get(m["method"], 0) + 1
    return {
        "n_rankings": len(rankings), "n_matched": len(matched),
        "n_unmatched": len(unmatched), "top_n": top_n,
        "top_methods": methods, "top_unmatched": top_unmatched,
    }


def run_gate(top_n: int = 200) -> int:
    """CLI: resolve the active rankings, write data/unmatched.csv, print a report.

    Returns the count of unmatched players inside the top N (must be 0).
    """
    g = gate_report(top_n=top_n)
    print(f"rankings rows:        {g['n_rankings']}")
    print(f"matched (all):        {g['n_matched']}")
    print(f"unmatched (all):      {g['n_unmatched']}  -> {UNMATCHED_PATH}")
    print(f"top-{top_n} match methods:  {g['top_methods']}")
    print(f"UNMATCHED IN TOP {top_n}:   {len(g['top_unmatched'])}")
    for r in g["top_unmatched"]:
        print(f"    #{r['rank']:>3} {r['name']} ({r['pos']} {r['team']})")
    return len(g["top_unmatched"])


if __name__ == "__main__":
    import sys
    sys.exit(1 if run_gate() > 0 else 0)
