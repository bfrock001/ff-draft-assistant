"""Dated data snapshots (spec §3.5).

All raw + derived data lives under ``data/raw/<YYYY-MM-DD>/``. The app reads the
*active* snapshot — ``config/active_snapshot`` if set, else the most recent — so
no other module hardcodes a date. This module is the single source of truth for
snapshot discovery, selection, and file paths. Pure path logic: no network, no
heavy deps.

New snapshots are written with standardized filenames (``rankings.csv``,
``proj_<pos>.csv``, ``espn_ranks.csv``, plus derived ``projections.csv`` /
``espn_adp.csv``). The original 2026-08-28 folder uses dated names, so the path
helpers fall back to a glob — either layout resolves.
"""
from __future__ import annotations

import datetime
import glob
import os
import re

RAW_ROOT = "data/raw"
ACTIVE_FILE = "config/active_snapshot"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PROJECTIONS_FILE = "projections.csv"   # derived (§4-scored proj_points)
ESPN_ADP_FILE = "espn_adp.csv"         # derived (canonical-joined ESPN ranks/ADP)
MANIFEST_FILE = "manifest.json"
# raw FantasyPros per-position projection exports
PROJ_RAW = {"QB": "proj_qb.csv", "RB": "proj_rb.csv", "WR": "proj_wr.csv",
            "TE": "proj_te.csv", "K": "proj_k.csv", "DST": "proj_dst.csv"}


def list_snapshots(root: str = RAW_ROOT) -> list[str]:
    """All snapshot dates present, newest first."""
    if not os.path.isdir(root):
        return []
    dates = [d for d in os.listdir(root)
             if _DATE_RE.match(d) and os.path.isdir(os.path.join(root, d))]
    return sorted(dates, reverse=True)


def latest_snapshot(root: str = RAW_ROOT) -> str | None:
    snaps = list_snapshots(root)
    return snaps[0] if snaps else None


def active_snapshot(root: str = RAW_ROOT) -> str:
    """The snapshot the app should read: ``config/active_snapshot`` if it names a
    real one, otherwise the most recent."""
    snaps = list_snapshots(root)
    if not snaps:
        raise FileNotFoundError(f"no snapshots under {root}/")
    if os.path.exists(ACTIVE_FILE):
        want = _read(ACTIVE_FILE)
        if want in snaps:
            return want
    return snaps[0]


def set_active_snapshot(date: str, root: str = RAW_ROOT) -> None:
    if date not in list_snapshots(root):
        raise ValueError(f"unknown snapshot {date!r}")
    os.makedirs(os.path.dirname(ACTIVE_FILE), exist_ok=True)
    with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
        f.write(date.strip() + "\n")


def snapshot_dir(date: str, root: str = RAW_ROOT) -> str:
    return os.path.join(root, date)


def age_days(date: str, today: datetime.date | None = None) -> int:
    today = today or datetime.date.today()
    return (today - datetime.date.fromisoformat(date)).days


# --- file paths within a snapshot (standardized name, else dated-name glob) ---
def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def _resolve(date: str, standardized: str, pattern: str, root: str) -> str | None:
    d = snapshot_dir(date, root)
    std = os.path.join(d, standardized)
    if os.path.exists(std):
        return std
    hits = sorted(glob.glob(os.path.join(d, pattern)))
    return hits[0] if hits else None


def rankings_path(date: str, root: str = RAW_ROOT) -> str | None:
    return _resolve(date, "rankings.csv", "rankings*.csv", root)


def projections_path(date: str, root: str = RAW_ROOT) -> str:
    return os.path.join(snapshot_dir(date, root), PROJECTIONS_FILE)


def espn_adp_path(date: str, root: str = RAW_ROOT) -> str:
    return os.path.join(snapshot_dir(date, root), ESPN_ADP_FILE)


def espn_raw_path(date: str, root: str = RAW_ROOT) -> str | None:
    return _resolve(date, "espn_ranks.csv", "espn_ranks*.csv", root)


def proj_raw_path(date: str, pos: str, root: str = RAW_ROOT) -> str:
    return os.path.join(snapshot_dir(date, root), PROJ_RAW[pos])


def manifest_path(date: str, root: str = RAW_ROOT) -> str:
    return os.path.join(snapshot_dir(date, root), MANIFEST_FILE)
