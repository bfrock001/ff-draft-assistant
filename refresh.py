"""Rebuild a snapshot's derived data, validate it, and diff it (spec §3.5).

Given a dated snapshot folder holding the RAW inputs — the FantasyPros consensus
rankings (``rankings*.csv``), the six per-position projection exports
(``proj_*.csv``), and optionally an ESPN board (``espn_ranks*.csv``) — this:

  1. rebuilds ``projections.csv`` (stat lines -> §4 proj_points) and, if an ESPN
     board is present, ``espn_adp.csv`` (canonical-joined ranks/ADP);
  2. runs the player-ID gate (zero unmatched in the top 200 is the acceptance);
  3. writes ``manifest.json`` (row counts, checksums, gate + coverage result);
  4. can diff two snapshots (rank movers, new / dropped top-N).

Load-time tooling only — pandas here is fine; never in the sim hot path (§9).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import shutil

import espn_adp
import espn_live
import projections
import snapshots
from board import load_board
from loaders import gate_report


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _data_rows(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        return max(0, sum(1 for _ in f) - 1)


def _present_files(date: str) -> dict[str, str]:
    d = snapshots.snapshot_dir(date)
    out: dict[str, str] = {}
    for logical, p in [("rankings", snapshots.rankings_path(date)),
                       ("projections", snapshots.projections_path(date)),
                       ("espn_adp", snapshots.espn_adp_path(date)),
                       ("espn_ranks", snapshots.espn_raw_path(date))]:
        if p and os.path.exists(p):
            out[logical] = p
    for pos, fn in snapshots.PROJ_RAW.items():
        p = os.path.join(d, fn)
        if os.path.exists(p):
            out[f"proj_{pos.lower()}"] = p
    return out


def carry_espn_forward(src_date: str, dst_date: str) -> bool:
    """Copy the ESPN board (raw + derived) from a prior snapshot into a new one
    that has none — so refreshing only FantasyPros still yields a complete board.
    Returns True if anything was copied."""
    dst = snapshots.snapshot_dir(dst_date)
    copied = False
    raw = snapshots.espn_raw_path(src_date)
    if raw and snapshots.espn_raw_path(dst_date) is None:
        shutil.copy(raw, os.path.join(dst, "espn_ranks.csv"))
        copied = True
    adp = snapshots.espn_adp_path(src_date)
    if os.path.exists(adp) and not os.path.exists(snapshots.espn_adp_path(dst_date)):
        shutil.copy(adp, snapshots.espn_adp_path(dst_date))
        copied = True
    return copied


def rebuild(date: str, top_n: int = 200) -> dict:
    """Rebuild derived files + gate + manifest for a snapshot. Returns the manifest."""
    d = snapshots.snapshot_dir(date)
    if not os.path.isdir(d):
        raise FileNotFoundError(f"no snapshot folder {d}")
    if snapshots.rankings_path(date) is None:
        raise FileNotFoundError(f"{d}: no rankings*.csv")

    # 1) projections.csv (FantasyPros stat lines -> §4 proj_points)
    proj_matched, proj_unmatched = projections.build(d)

    # 2) espn_adp.csv (only if a raw ESPN board is present in this snapshot)
    espn_src = snapshots.espn_raw_path(date)
    espn_rows, espn_unresolved = [], []
    if espn_src:
        espn_rows, espn_unresolved = espn_adp.build_espn_adp(
            espn_src, snapshots.espn_adp_path(date))

    # 3) player-ID gate on the rankings (acceptance: 0 unmatched in top N)
    g = gate_report(snapshots.rankings_path(date), top_n=top_n, write=True)

    # 4) coverage on the assembled board (needs projections + espn_adp present)
    coverage: dict = {}
    if os.path.exists(snapshots.espn_adp_path(date)):
        try:
            b = load_board(date)
            top = b[b["rank"] <= top_n]
            coverage = {"top_n": top_n, "total": int(len(top)),
                        "proj_have": int(top["proj_points"].notna().sum()),
                        "espn_have": int(top["espn_rank"].notna().sum())}
        except Exception as e:  # noqa: BLE001 - surfaced in the manifest, not fatal
            coverage = {"error": str(e)}
    else:
        coverage = {"error": "no espn_adp.csv (ESPN board missing / not carried)"}

    manifest = {
        "date": date,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "files": {name: {"rows": _data_rows(p), "sha256": _sha256(p)}
                  for name, p in _present_files(date).items()},
        "gate": {
            "top_n": top_n,
            "n_rankings": g["n_rankings"],
            "unmatched_top_n_count": len(g["top_unmatched"]),
            "unmatched_top_n": [f"#{r['rank']} {r['name']} ({r['pos']} {r['team']})"
                                for r in g["top_unmatched"]],
            "methods": g["top_methods"],
        },
        "projections": {"rows": len(proj_matched), "unmatched": len(proj_unmatched)},
        "espn": {"rows": len(espn_rows), "unresolved": len(espn_unresolved),
                 "source": os.path.basename(espn_src) if espn_src else None},
        "coverage": coverage,
    }
    with open(snapshots.manifest_path(date), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def refresh_espn(date: str) -> dict:
    """Pull a fresh ESPN board into ``date``'s snapshot, rebuild espn_adp.csv +
    the manifest, and return a coverage report.

    Non-destructive: the risky network fetch (and cookie/auth checks) happen
    BEFORE any file is written, so on failure the existing board is untouched.
    """
    cookies = espn_live.load_cookies()             # raises if missing/placeholder
    rows = espn_live.fetch_board(cookies)          # raises on network / auth error
    if len(rows) < 50:
        raise RuntimeError(f"ESPN returned only {len(rows)} players (expected a few "
                           "hundred) — the board was not changed.")
    d = snapshots.snapshot_dir(date)
    raw = os.path.join(d, "espn_ranks.csv")
    espn_live.write_raw(rows, raw + ".tmp")
    os.replace(raw + ".tmp", raw)                  # atomic swap of the raw board
    manifest = rebuild(date)                        # regenerates espn_adp + manifest
    manifest["espn_refreshed_at"] = datetime.datetime.now().isoformat(timespec="seconds")

    # which of OUR top-200 lack an ESPN rank after the refresh?
    missing = []
    try:
        top = load_board(date)
        top = top[top["rank"] <= 200]
        for r in top[top["espn_rank"].isna()].itertuples(index=False):
            missing.append({"rank": int(r.rank), "name": r.name, "pos": r.pos})
    except Exception:  # noqa: BLE001
        pass
    return {"rows": rows, "manifest": manifest, "missing": missing}


def _indexed(date: str):
    b = load_board(date)
    b = b[b["canonical_id"].apply(lambda c: isinstance(c, str))]
    return b.drop_duplicates("canonical_id").set_index("canonical_id")


def diff(old_date: str, new_date: str, top_n: int = 200,
         move_thresh: int = 10) -> dict:
    """Diff two snapshots' boards: big rank movers + new / dropped top-N."""
    old, new = _indexed(old_date), _indexed(new_date)
    movers = []
    for cid, nr in new.iterrows():
        if cid in old.index:
            o, n = int(old.loc[cid, "rank"]), int(nr["rank"])
            if abs(n - o) > move_thresh and min(o, n) <= 150:
                movers.append({"name": nr["name"], "old": o, "new": n, "delta": n - o})
    new_top = set(new[new["rank"] <= top_n].index)
    old_top = set(old[old["rank"] <= top_n].index)
    movers.sort(key=lambda m: -abs(m["delta"]))
    return {
        "old_date": old_date, "new_date": new_date,
        "movers": movers,
        "entrants": sorted(str(new.loc[c, "name"]) for c in (new_top - old_top)),
        "dropped": sorted(str(old.loc[c, "name"]) for c in (old_top - new_top)),
    }


if __name__ == "__main__":
    date = snapshots.active_snapshot()
    m = rebuild(date)
    print(json.dumps(m, indent=2))
