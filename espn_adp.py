"""Build the ESPN ADP snapshot for the opponent model (spec §3.2).

Input: an ESPN pre-draft ranking capture (rank, espn_id, name, team, pos) from
the league's edit-draft-strategy board (the order the league auto-drafts off).
Output: data/raw/<date>/espn_adp.csv, each row mapped to our canonical id
(crosswalk mfl_id, or DST_<team>) so the opponent model indexes ESPN's board by
the same player universe as everything else. ESPN rank is used as the ADP proxy.
"""
from __future__ import annotations

import csv
import os

import polars as pl

from ids import PlayerResolver, load_overrides
from loaders import CACHE_CROSSWALK, OVERRIDES_PATH, POS_TO_CROSSWALK, load_crosswalk


def _overrides() -> dict:
    return load_overrides(OVERRIDES_PATH) if os.path.exists(OVERRIDES_PATH) else {}

VALID_POS = {"QB", "RB", "WR", "TE", "K", "DST"}
# ESPN team codes -> the codes our rankings (FantasyPros) use, for D/ST joins.
ESPN_TEAM_FIX = {"WSH": "WAS", "JAX": "JAC"}


def espn_id_to_mfl(path: str = CACHE_CROSSWALK) -> dict[str, str]:
    df = pl.read_parquet(path)
    out: dict[str, str] = {}
    for eid, mfl in df.select(["espn_id", "mfl_id"]).iter_rows():
        if eid is None:
            continue
        key = str(int(eid)) if isinstance(eid, float) else str(eid)
        out[key] = str(mfl)
    return out


def _recover_dual_position(name: str, team: str, pos: str):
    """ESPN two-way players (e.g. 'Travis Hunter JAX WR CB') shift columns."""
    if pos in VALID_POS:
        return name, team, pos
    if team in {"QB", "RB", "WR", "TE", "K"}:
        toks = name.split()
        return " ".join(toks[:-1]), toks[-1], team  # name, real team, real pos
    return name, team, pos


def build_espn_adp(src: str, out: str):
    e2m = espn_id_to_mfl()
    resolver = PlayerResolver(load_crosswalk(), overrides=_overrides())
    rows, unresolved = [], []
    with open(src, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rank = int(r["rank"])
            eid = (r.get("espn_id") or "").strip()
            name, team, pos = _recover_dual_position(
                r["name"], r["team"], r["pos"].upper())
            if pos == "DST":
                team = ESPN_TEAM_FIX.get(team.upper(), team.upper())
                cid, method = f"DST_{team}", "dst_team"
            elif eid and eid in e2m:
                cid, method = e2m[eid], "espn_id"
            else:
                cid, method = resolver.resolve(
                    name, POS_TO_CROSSWALK.get(pos, pos), team)
                if cid is None:
                    unresolved.append((rank, name, pos, team))
            rows.append({"espn_rank": rank, "canonical_id": cid or "",
                         "espn_id": eid, "name": name, "team": team,
                         "pos": pos, "method": method})
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["espn_rank", "canonical_id", "espn_id",
                                          "name", "team", "pos", "method"])
        w.writeheader()
        w.writerows(rows)
    return rows, unresolved


if __name__ == "__main__":
    from collections import Counter

    from loaders import load_rankings, resolve_rankings

    SRC = "data/raw/2026-08-28/espn_ranks_2026-08-28.csv"
    OUT = "data/raw/2026-08-28/espn_adp.csv"
    rows, unresolved = build_espn_adp(SRC, OUT)
    print(f"espn rows:        {len(rows)}  -> {OUT}")
    print(f"resolve methods:  {dict(Counter(r['method'] for r in rows))}")
    print(f"unresolved:       {len(unresolved)}")
    for u in unresolved:
        print("    ", u)

    # Coverage: does every top-200 player in OUR rankings have an ESPN rank?
    resolver = PlayerResolver(load_crosswalk(), overrides=_overrides())
    matched, _ = resolve_rankings(load_rankings(), resolver)
    espn_ids = {r["canonical_id"] for r in rows if r["canonical_id"]}
    top200 = [m for m in matched if m["rank"] <= 200]
    missing = [m for m in top200 if m["canonical_id"] not in espn_ids]
    print(f"\nour top-200 with an ESPN rank: {len(top200) - len(missing)}/{len(top200)}")
    for m in missing:
        print(f"    our #{m['rank']:>3} {m['name']} ({m['pos']}) not in ESPN top-300")
