"""Projection loader -> proj_points (spec §3.1, §4, §6).

Reads FantasyPros per-position projection snapshots (stat lines) and converts
each to our full-PPR proj_points via the §4 engine. We use the STAT columns and
compute points ourselves; the export's FPTS column is ignored (§3.3) because it
is half-PPR and uses FantasyPros' own INT / FG / points-allowed rules.

Documented approximations for the near-noise positions (§14.4):
- Kickers: the export gives total FGs made, not FG-by-distance, so we value each
  made FG at KICKER_FG_PTS (a blended average of the §4 distance bands 3/4/5)
  plus XP. Missed FGs score 0 (§4). Tunable; refine from FG-distance history later.
- D/ST: the export gives a SEASON points-allowed total; §4's PA tiers are
  per-game, so we apply the tier to PA/GAMES and scale back by GAMES. Blocked
  kicks / return TDs aren't projected (0). This reproduces FantasyPros' own D/ST
  FPTS closely, which confirms the column mapping.
"""
from __future__ import annotations

import csv
import os

from ids import PlayerResolver, load_overrides
from loaders import OVERRIDES_PATH, POS_TO_CROSSWALK, load_crosswalk
from scoring import dst_points_allowed_points, score_stat_line

# FantasyPros per-position projection exports. This module is the FantasyPros
# *adapter*: the column maps (COLS/FPTS_COL below) are specific to their export
# layout — a different source would supply its own adapter to the same schema.
FILES = {"QB": "proj_qb.csv", "RB": "proj_rb.csv", "WR": "proj_wr.csv",
         "TE": "proj_te.csv", "K": "proj_k.csv", "DST": "proj_dst.csv"}

KICKER_FG_PTS = 3.5   # blended value of one made FG across §4 bands; tunable
GAMES = 17

DST_NAME_TO_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAC",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "Seattle Seahawks": "SEA", "San Francisco 49ers": "SF", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


def _num(s: str) -> float:
    s = (s or "").strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _header_and_rows(path: str):
    """(UPPERCASED header cells, data rows after it). FantasyPros exports carry a
    title/group row or two before the real 'Player,…' header."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    hi = next(i for i, r in enumerate(rows) if r and r[0].strip().lower() == "player")
    return [c.strip().upper() for c in rows[hi]], rows[hi + 1:]


def _stat_line(pos: str, header: list[str], cells: list[str]) -> dict:
    """Pull stats by column NAME, anchored on marker columns — survives added
    columns (Team/CMP/ATT) and block reordering across export versions. YDS/TDS
    repeat for passing/rushing/receiving: the passing block ends at INTS, and each
    rushing/receiving block starts at ATT/REC."""
    def val(i):
        return _num(cells[i]) if (i is not None and i < len(cells)) else 0.0

    def idx(name, after=-1):
        for i, h in enumerate(header):
            if h == name and i > after:
                return i
        return None

    if pos == "QB":
        it = idx("INTS")
        return {"pass_yds": val(idx("YDS")), "pass_td": val(idx("TDS")),
                "pass_int": val(it),
                "rush_yds": val(idx("YDS", it) if it is not None else None),
                "rush_td": val(idx("TDS", it) if it is not None else None),
                "fumbles_lost": val(idx("FL"))}
    if pos in ("RB", "WR"):
        a, r = idx("ATT"), idx("REC")
        return {"rush_yds": val(idx("YDS", a)), "rush_td": val(idx("TDS", a)),
                "rec": val(r), "rec_yds": val(idx("YDS", r)),
                "rec_td": val(idx("TDS", r)), "fumbles_lost": val(idx("FL"))}
    if pos == "TE":
        r = idx("REC")
        return {"rec": val(r), "rec_yds": val(idx("YDS", r)),
                "rec_td": val(idx("TDS", r)), "fumbles_lost": val(idx("FL"))}
    if pos == "K":
        return {"fg": val(idx("FG")), "fga": val(idx("FGA")), "xpm": val(idx("XPT"))}
    return {k: val(idx(nm)) for k, nm in (
        ("sack", "SACK"), ("int", "INT"), ("fr", "FR"), ("ff", "FF"),
        ("td", "TD"), ("safety", "SAFETY"), ("pa", "PA"))}


def proj_points_for(pos: str, line: dict) -> float:
    if pos == "K":
        return line.get("fg", 0) * KICKER_FG_PTS + line.get("xpm", 0)
    if pos == "DST":
        pa_pts = dst_points_allowed_points(line.get("pa", 0) / GAMES) * GAMES
        return (line.get("sack", 0) + 2 * line.get("int", 0) + 2 * line.get("fr", 0)
                + 2 * line.get("safety", 0) + 6 * line.get("td", 0) + pa_pts)
    return score_stat_line(line)


def load_projections(snap_dir: str) -> list[dict]:
    out = []
    for pos, fn in FILES.items():
        header, rows = _header_and_rows(os.path.join(snap_dir, fn))
        team_col = next((i for i, h in enumerate(header) if h == "TEAM"), None)
        fpts_col = next((i for i, h in enumerate(header) if h == "FPTS"), None)
        for cells in rows:
            if not cells or not cells[0].strip():
                continue
            if "more rows removed" in cells[0]:
                continue
            player = cells[0].strip()
            if team_col is not None and team_col < len(cells) and cells[team_col].strip():
                name, team = player, cells[team_col].strip()      # separate Team column
                if pos == "DST":
                    team = DST_NAME_TO_ABBR.get(player, team)
            elif pos == "DST":
                name, team = player, DST_NAME_TO_ABBR.get(player, "")
            else:                                                  # old export: "Name TEAM"
                toks = player.split()
                name, team = " ".join(toks[:-1]), toks[-1]
            line = _stat_line(pos, header, cells)
            out.append({
                "name": name, "team": team, "pos": pos,
                "proj_points": round(proj_points_for(pos, line), 2),
                "file_fpts": (_num(cells[fpts_col]) if fpts_col is not None
                              and fpts_col < len(cells) else 0.0),
                "rec": line.get("rec", 0.0),
            })
    return out


def resolve_projections(projs: list[dict], resolver: PlayerResolver):
    matched, unmatched = [], []
    for p in projs:
        if p["pos"] == "DST":
            cid, method = f"DST_{p['team']}", "dst_team"
        else:
            cid, method = resolver.resolve(
                p["name"], POS_TO_CROSSWALK.get(p["pos"], p["pos"]), p["team"])
        if cid is None:
            unmatched.append(p)
        else:
            matched.append({**p, "canonical_id": cid, "method": method})
    return matched, unmatched


def build(snap_dir: str, out: str | None = None):
    out = out or os.path.join(snap_dir, "projections.csv")
    resolver = PlayerResolver(load_crosswalk(), overrides=load_overrides(OVERRIDES_PATH))
    projs = load_projections(snap_dir)
    matched, unmatched = resolve_projections(projs, resolver)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["canonical_id", "name", "team", "pos",
                                          "proj_points", "method"])
        w.writeheader()
        for m in matched:
            w.writerow({k: m[k] for k in w.fieldnames})
    return matched, unmatched


if __name__ == "__main__":
    from collections import Counter

    import snapshots
    from loaders import load_rankings, resolve_rankings

    _date = snapshots.active_snapshot()
    snap_dir = snapshots.snapshot_dir(_date)
    OUT = snapshots.projections_path(_date)
    matched, unmatched = build(snap_dir, OUT)
    print(f"projection rows:  {len(matched)}  -> {OUT}")
    print(f"resolve methods:  {dict(Counter(m['method'] for m in matched))}")
    print(f"unmatched:        {len(unmatched)}")
    for u in unmatched[:20]:
        print("    ", u["name"], u["pos"], u["team"])

    # Parsing check: our half-PPR (full minus 0.5/rec) must match the export's
    # half-PPR FPTS for RB/WR/TE (no INT/FG differences there).
    worst = 0.0
    for m in matched:
        if m["pos"] in ("RB", "WR", "TE"):
            ours_half = m["proj_points"] - 0.5 * m["rec"]
            worst = max(worst, abs(ours_half - m["file_fpts"]))
    print(f"\nRB/WR/TE parse check: max |our half-PPR - export FPTS| = {worst:.2f}")

    dst_worst = max((abs(m["proj_points"] - m["file_fpts"])
                     for m in matched if m["pos"] == "DST"), default=0.0)
    print(f"D/ST check:           max |our §4 - export FPTS|      = {dst_worst:.2f}")

    anchors = {"Jahmyr Gibbs": 373.0, "Bijan Robinson": 357.0, "Derrick Henry": 273.8}
    print("\nfull-PPR anchors (our §4 vs known full-PPR):")
    for m in matched:
        if m["name"] in anchors:
            print(f"    {m['name']:16} {m['proj_points']:7.1f}  (ref {anchors[m['name']]})")

    # Coverage: every top-200 ranked player must have a projection.
    rank_res = PlayerResolver(load_crosswalk(), overrides=load_overrides(OVERRIDES_PATH))
    rmatched, _ = resolve_rankings(load_rankings(), rank_res)
    proj_ids = {m["canonical_id"] for m in matched}
    top200 = [m for m in rmatched if m["rank"] <= 200]
    missing = [m for m in top200 if m["canonical_id"] not in proj_ids]
    print(f"\nour top-200 with a projection: {len(top200) - len(missing)}/{len(top200)}")
    for m in missing:
        print(f"    our #{m['rank']:>3} {m['name']} ({m['pos']}) has no projection")
