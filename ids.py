"""Player identity resolution (spec §5).

Name normalization plus a resolver mapping source (name, position, team) rows to
canonical player ids. The canonical crosswalk itself (nflreadpy
``load_ff_playerids``) is loaded elsewhere (data loaders); this module is pure
logic so it can be unit-tested with a synthetic crosswalk and no network.

Resolution order: manual override -> exact (name, pos, team) -> (name, pos)
ignoring team -> fuzzy name within position -> unmatched. Nothing is ever
silently dropped; callers write every unmatched row to data/unmatched.csv.
"""
from __future__ import annotations

import csv
import difflib
import re
from collections.abc import Iterable, Mapping

SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def normalize_name(name: str | None) -> str:
    """Lowercase, drop punctuation, strip name suffixes, collapse whitespace.

    "Marvin Harrison Jr." / "Marvin Harrison Jr" / "A.J. Brown" all reduce to a
    stable key so one player never splits into two rows and corrupts the
    variance math.
    """
    if name is None:
        return ""
    s = str(name).lower().strip()
    s = s.replace("'", "").replace("’", "").replace(".", "")
    s = s.replace("-", " ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    tokens = [t for t in s.split() if t]
    while tokens and tokens[-1] in SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


class PlayerResolver:
    """Resolves source rows to canonical ids against a fixed crosswalk."""

    def __init__(self, players: Iterable[Mapping], overrides: Mapping | None = None,
                 fuzzy_threshold: float = 0.88):
        self.fuzzy_threshold = fuzzy_threshold
        self.overrides = {str(k): str(v) for k, v in (overrides or {}).items()}
        self._by_name_pos_team: dict[tuple[str, str, str], str] = {}
        self._by_name_pos: dict[tuple[str, str], str] = {}
        self._names_by_pos: dict[str, dict[str, str]] = {}
        for p in players:
            pid = str(p["id"])
            pos = (p.get("pos") or "").upper()
            team = (p.get("team") or "").upper()
            nn = normalize_name(p["name"])
            self._by_name_pos_team[(nn, pos, team)] = pid
            # first writer wins on the looser index so results stay deterministic
            self._by_name_pos.setdefault((nn, pos), pid)
            self._names_by_pos.setdefault(pos, {}).setdefault(nn, pid)

    def resolve(self, name, pos, team) -> tuple[str | None, str]:
        """Return (canonical_id, method) or (None, "unmatched")."""
        raw = str(name)
        if raw in self.overrides:
            return self.overrides[raw], "override"
        pos = (pos or "").upper()
        team = (team or "").upper()
        nn = normalize_name(name)
        hit = self._by_name_pos_team.get((nn, pos, team))
        if hit is not None:
            return hit, "exact"
        hit = self._by_name_pos.get((nn, pos))
        if hit is not None:
            return hit, "name_pos"
        pool = self._names_by_pos.get(pos, {})
        best = difflib.get_close_matches(nn, pool.keys(), n=1,
                                         cutoff=self.fuzzy_threshold)
        if best:
            return pool[best[0]], "fuzzy"
        return None, "unmatched"


def load_overrides(path) -> dict[str, str]:
    """Load data/manual_id_overrides.csv (source_name, canonical_id)."""
    out: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["source_name"]] = row["canonical_id"]
    return out
