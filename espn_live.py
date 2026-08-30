"""Pre-draft ESPN board refresh (spec §3.2).

Pulls fresh ESPN PPR draft ranks + ADP from ESPN's league API and writes a raw
board CSV in exactly the schema ``espn_adp.build_espn_adp`` consumes, so the
opponent model can be refreshed with one click before draft day.

Why this works where the earlier in-browser attempt didn't: the ``X-Fantasy-
Filter`` header is stripped cross-origin from a page context, but here the
request is made SERVER-SIDE from Python (no CORS), so it goes through. The only
network touch is when the user presses the button — never during the draft.
Private-league access needs the session cookies in ``config/espn_cookies.json``
(git-ignored); failures raise with a clear message and never write a file.
"""
from __future__ import annotations

import csv
import json
import os
import urllib.error
import urllib.request

from config import ESPN_LEAGUE_ID, ESPN_SEASON

COOKIES_PATH = "config/espn_cookies.json"
_PLACEHOLDER = "PASTE"   # marker left in the example/placeholder cookie file

# ESPN defaultPositionId -> our position code
ESPN_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}

# ESPN proTeamId -> team abbreviation (build_espn_adp maps WSH->WAS, JAX->JAC).
ESPN_PROTEAM = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR",
    15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI",
    22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WSH",
    29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}

RAW_FIELDS = ["rank", "espn_id", "name", "team", "pos", "adp"]


def load_cookies(path: str = COOKIES_PATH) -> dict:
    """Read + validate the ESPN session cookies. Raises with a clear message if
    the file is missing or still holds the placeholder values."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} not found — copy config/espn_cookies.example.json to it and "
            "paste your espn_s2 + SWID.")
    with open(path, encoding="utf-8") as f:
        c = json.load(f)
    s2, swid = (c.get("espn_s2") or "").strip(), (c.get("SWID") or "").strip()
    if not s2 or not swid or _PLACEHOLDER in s2 or _PLACEHOLDER in swid:
        raise ValueError(
            "ESPN cookies aren't filled in yet — set espn_s2 and SWID in "
            f"{path} (they're still the placeholder values).")
    return {"espn_s2": s2, "SWID": swid}


def cookies_configured(path: str = COOKIES_PATH) -> bool:
    try:
        load_cookies(path)
        return True
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return False


def _filter(limit: int) -> str:
    return json.dumps({"players": {
        "limit": limit, "offset": 0,
        "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "PPR"}}})


def _get_json(url: str, cookies: dict, extra: dict | None = None) -> dict:
    req = urllib.request.Request(url)
    req.add_header("Cookie", f"espn_s2={cookies['espn_s2']}; SWID={cookies['SWID']}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    for k, v in (extra or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError(
                f"ESPN rejected the request ({e.code}) — your cookies have likely "
                "expired. Re-grab espn_s2 + SWID and update config/espn_cookies.json."
            ) from None
        raise RuntimeError(f"ESPN request failed (HTTP {e.code}).") from None
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Could not reach ESPN ({e.reason}). Check your connection.") from None


def parse_players(data: dict) -> list[dict]:
    """Map an ESPN kona_player_info payload -> raw board rows (offline-testable)."""
    rows = []
    for p in data.get("players", []):
        pl = p.get("player", {}) or {}
        pos = ESPN_POS.get(pl.get("defaultPositionId"))
        if pos is None:
            continue
        dr = (pl.get("draftRanksByRankType", {}) or {}).get("PPR", {}) or {}
        rank = dr.get("rank")
        if rank in (None, 0):
            continue
        adp = (pl.get("ownership", {}) or {}).get("averageDraftPosition")
        rows.append({
            "rank": int(rank),
            "espn_id": str(pl.get("id", "")),
            "name": pl.get("fullName", ""),
            "team": ESPN_PROTEAM.get(pl.get("proTeamId"), ""),
            "pos": pos,
            "adp": round(adp, 1) if isinstance(adp, (int, float)) and adp > 0 else "",
        })
    rows.sort(key=lambda r: r["rank"])
    return rows


def fetch_board(cookies: dict, league_id: int = ESPN_LEAGUE_ID,
                season: int = ESPN_SEASON, limit: int = 300) -> list[dict]:
    url = (f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/"
           f"seasons/{season}/segments/0/leagues/{league_id}?view=kona_player_info")
    data = _get_json(url, cookies, {"X-Fantasy-Filter": _filter(limit)})
    return parse_players(data)


def write_raw(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RAW_FIELDS)
        w.writeheader()
        w.writerows(rows)


# --- live draft sync (spec §3.2 stretch) --------------------------------------
# ESPN's mDraftDetail view pre-creates all N pick slots with playerId = -1; each
# slot's playerId fills in as that pick is made. Polling it and reading the
# filled-in slots is the live board. Optional and pre/in-draft only; the app
# always keeps manual entry as the fallback.

def parse_draft_picks(data: dict) -> dict:
    """Extract the picks MADE so far (playerId != -1) from an mDraftDetail
    payload, in overall-pick order. Offline / unit-testable."""
    dd = data.get("draftDetail", {}) or {}
    made = []
    for p in dd.get("picks", []) or []:
        pid = p.get("playerId", -1)
        if pid in (None, -1):
            continue
        made.append({
            "overall": p.get("overallPickNumber"),
            "round": p.get("roundId"),
            "round_pick": p.get("roundPickNumber"),
            "team_id": p.get("teamId"),
            "espn_id": str(pid),
        })
    made.sort(key=lambda x: x["overall"] or 0)
    return {"in_progress": bool(dd.get("inProgress")),
            "drafted": bool(dd.get("drafted")), "picks": made}


def fetch_draft_picks(cookies: dict, league_id: int,
                      season: int = ESPN_SEASON) -> dict:
    """Poll the live draft board for ``league_id``. Raises on network/auth error."""
    url = (f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/"
           f"seasons/{season}/segments/0/leagues/{league_id}?view=mDraftDetail")
    return parse_draft_picks(_get_json(url, cookies))


def load_espn_maps(date: str) -> tuple[dict, dict]:
    """(espn_id -> canonical_id, espn_id -> name) for resolving live picks.

    The crosswalk (all offense) overlaid by the active snapshot's espn_adp.csv
    (adds D/ST via team + player names). Same mapping the board uses, so a live
    pick resolves to exactly the same player."""
    from espn_adp import ESPN_TEAM_FIX, espn_id_to_mfl  # lazy: polars/ids only when syncing
    import snapshots

    id2c = espn_id_to_mfl()
    id2n: dict[str, str] = {}
    # D/ST aren't in the crosswalk; their live playerId is -16000 - proTeamId, so
    # map all 32 deterministically to DST_<team> (same canonical the board uses).
    for pid, abbr in ESPN_PROTEAM.items():
        eid = str(-16000 - pid)
        id2c[eid] = f"DST_{ESPN_TEAM_FIX.get(abbr, abbr)}"
        id2n[eid] = f"{abbr} D/ST"
    adp = snapshots.espn_adp_path(date)
    if os.path.exists(adp):
        with open(adp, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                eid = (r.get("espn_id") or "").strip()
                if not eid:
                    continue
                if (r.get("canonical_id") or "").strip():
                    id2c[eid] = r["canonical_id"].strip()
                if r.get("name"):
                    id2n[eid] = r["name"]
    return id2c, id2n


def resolve_draft_picks(cookies: dict, league_id: int, date: str,
                        season: int = ESPN_SEASON) -> dict:
    """Live draft state with each made pick mapped to our canonical player id.

    Returns {in_progress, drafted, picks: [{overall, round, round_pick, team_id,
    espn_id, canonical_id, name}], unmapped: [...]}. ``unmapped`` are picks whose
    ESPN id we couldn't resolve (rare — a deep player outside the pulled board);
    the caller surfaces those so nothing is silently dropped."""
    state = fetch_draft_picks(cookies, league_id, season)
    id2c, id2n = load_espn_maps(date)
    for p in state["picks"]:
        p["canonical_id"] = id2c.get(p["espn_id"])
        p["name"] = id2n.get(p["espn_id"], f"ESPN#{p['espn_id']}")
    state["unmapped"] = [p for p in state["picks"] if not p["canonical_id"]]
    return state
