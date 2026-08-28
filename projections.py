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

from ids import PlayerResolver, load_overrides
from loaders import OVERRIDES_PATH, POS_TO_CROSSWALK, load_crosswalk
from scoring import dst_points_allowed_points, score_stat_line

SNAP = "data/raw/2026-08-28"
FILES = {"QB": "proj_qb.csv", "RB": "proj_rb.csv", "WR": "proj_wr.csv",
         "TE": "proj_te.csv", "K": "proj_k.csv", "DST": "proj_dst.csv"}
OUT = f"{SNAP}/projections.csv"

KICKER_FG_PTS = 3.5   # blended value of one made FG across §4 bands; tunable
GAMES = 17

# stat -> column index (Player is column 0) per position
COLS = {
    "QB": {"pass_yds": 3, "pass_td": 4, "pass_int": 5, "rush_yds": 7,
           "rush_td": 8, "fumbles_lost": 9},
    "RB": {"rush_yds": 2, "rush_td": 3, "rec": 4, "rec_yds": 5, "rec_td": 6,
           "fumbles_lost": 7},
    "WR": {"rec": 1, "rec_yds": 2, "rec_td": 3, "rush_yds": 5, "rush_td": 6,
           "fumbles_lost": 7},
    "TE": {"rec": 1, "rec_yds": 2, "rec_td": 3, "fumbles_lost": 4},
    "K":  {"fg": 1, "fga": 2, "xpm": 3},
    "DST": {"sack": 1, "int": 2, "fr": 3, "ff": 4, "td": 5, "safety": 6, "pa": 7},
}
FPTS_COL = {"QB": 10, "RB": 8, "WR": 8, "TE": 5, "K": 4, "DST": 9}

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


def _data_rows(path: str):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    hi = next(i for i, r in enumerate(rows) if r and r[0].strip() == "Player")
    return rows[hi + 1:]


def _stat_line(pos: str, cells: list[str]) -> dict:
    c = COLS[pos]
    return {k: _num(cells[i]) for k, i in c.items()}


def proj_points_for(pos: str, line: dict) -> float:
    if pos == "K":
        return line.get("fg", 0) * KICKER_FG_PTS + line.get("xpm", 0)
    if pos == "DST":
        pa_pts = dst_points_allowed_points(line.get("pa", 0) / GAMES) * GAMES
        return (line.get("sack", 0) + 2 * line.get("int", 0) + 2 * line.get("fr", 0)
                + 2 * line.get("safety", 0) + 6 * line.get("td", 0) + pa_pts)
    return score_stat_line(line)


def load_projections() -> list[dict]:
    out = []
    for pos, fn in FILES.items():
        for cells in _data_rows(f"{SNAP}/{fn}"):
            if not cells or not cells[0].strip():
                continue
            if "more rows removed" in cells[0]:
                continue
            player = cells[0].strip()
            if pos == "DST":
                name, team = player, DST_NAME_TO_ABBR.get(player, "")
            else:
                toks = player.split()
                name, team = " ".join(toks[:-1]), toks[-1]
            line = _stat_line(pos, cells)
            out.append({
                "name": name, "team": team, "pos": pos,
                "proj_points": round(proj_points_for(pos, line), 2),
                "file_fpts": _num(cells[FPTS_COL[pos]]) if len(cells) > FPTS_COL[pos] else 0.0,
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


def build(out: str = OUT):
    resolver = PlayerResolver(load_crosswalk(), overrides=load_overrides(OVERRIDES_PATH))
    projs = load_projections()
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

    from loaders import load_rankings, resolve_rankings

    matched, unmatched = build()
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
