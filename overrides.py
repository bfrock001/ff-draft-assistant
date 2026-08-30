"""Manual value overrides (Increment 2) — your own opinions layered over the
active source, so you can disagree with a ranking or exclude a player.

Global and keyed by canonical player id, so overrides carry across snapshot
refreshes (a new FantasyPros/ESPN pull doesn't wipe your tweaks). Load-time only
(csv/pandas fine): overrides are baked into the board/pool BEFORE the engines
run, never inside the sim hot path (§9).

- proj_points / consensus_rank overrides replace the source value (both engines
  then optimize on your number).
- exclude does NOT drop the player from the board/pool (opponents still draft
  him, and you still track the pick); the recommenders just skip him as one of
  *your* candidates — see excluded_ids() + the engines' `exclude` argument.
"""
from __future__ import annotations

import csv
import hashlib
import os

PATH = "data/manual_overrides.csv"
FIELDS = ["canonical_id", "proj_points", "consensus_rank", "exclude"]


def load(path: str = PATH) -> dict:
    out: dict[str, dict] = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            cid = (r.get("canonical_id") or "").strip()
            if not cid:
                continue
            o: dict = {}
            pp = (r.get("proj_points") or "").strip()
            cr = (r.get("consensus_rank") or "").strip()
            ex = (r.get("exclude") or "").strip().lower()
            if pp:
                o["proj_points"] = float(pp)
            if cr:
                o["consensus_rank"] = float(cr)
            if ex in ("1", "true", "yes"):
                o["exclude"] = True
            if o:
                out[cid] = o
    return out


def save(overrides: dict, path: str = PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for cid, o in sorted(overrides.items()):
            w.writerow({
                "canonical_id": cid,
                "proj_points": o.get("proj_points", ""),
                "consensus_rank": o.get("consensus_rank", ""),
                "exclude": "1" if o.get("exclude") else "",
            })


def excluded_ids(overrides: dict) -> set:
    return {cid for cid, o in overrides.items() if o.get("exclude")}


def apply(board, overrides: dict):
    """Return the board with proj_points / consensus_rank overrides applied by
    canonical_id. Exclusion is intentionally NOT applied here."""
    if not overrides:
        return board
    b = board.copy()
    ids = b["canonical_id"].tolist()
    for col in ("proj_points", "consensus_rank"):
        if col not in b.columns:
            continue
        vals = b[col].tolist()
        for i, cid in enumerate(ids):
            o = overrides.get(cid)
            if o and col in o:
                vals[i] = o[col]
        b[col] = vals
    return b


def signature(path: str = PATH) -> str:
    """Content hash for cache-keying — changes whenever the overrides change."""
    if not os.path.exists(path):
        return "none"
    with open(path, "rb") as f:
        return hashlib.sha1(f.read()).hexdigest()
