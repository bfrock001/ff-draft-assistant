"""ESPN board refresh — offline unit tests (no network).

Covers the payload->rows mapping, cookie validation, and that write_raw emits
exactly the columns espn_adp.build_espn_adp consumes.
"""
import csv

import pytest

import espn_live

PAYLOAD = {"players": [
    {"player": {"id": 111, "fullName": "Runner One", "defaultPositionId": 2,
                "proTeamId": 7, "draftRanksByRankType": {"PPR": {"rank": 3}},
                "ownership": {"averageDraftPosition": 4.2}}},
    {"player": {"id": 222, "fullName": "Passer Two", "defaultPositionId": 1,
                "proTeamId": 12, "draftRanksByRankType": {"PPR": {"rank": 1}},
                "ownership": {"averageDraftPosition": 1.1}}},
    {"player": {"id": 333, "fullName": "Punter Guy", "defaultPositionId": 7,  # unmapped
                "proTeamId": 9, "draftRanksByRankType": {"PPR": {"rank": 5}}}},
    {"player": {"id": 444, "fullName": "No Rank", "defaultPositionId": 3,
                "proTeamId": 9, "draftRanksByRankType": {"PPR": {"rank": 0}}}},  # skip
    {"player": {"id": 555, "fullName": "Broncos D/ST", "defaultPositionId": 16,
                "proTeamId": 7, "draftRanksByRankType": {"PPR": {"rank": 120}}}},
]}


def test_parse_players_maps_sorts_and_skips():
    rows = espn_live.parse_players(PAYLOAD)
    # punter (unmapped pos) and rank-0 row dropped; sorted by rank
    assert [r["espn_id"] for r in rows] == ["222", "111", "555"]
    assert rows[0] == {"rank": 1, "espn_id": "222", "name": "Passer Two",
                       "team": "KC", "pos": "QB", "adp": 1.1}
    assert rows[1]["pos"] == "RB" and rows[1]["team"] == "DEN" and rows[1]["adp"] == 4.2
    assert rows[2]["pos"] == "DST" and rows[2]["team"] == "DEN"  # proTeam 7 -> DEN
    assert rows[2]["adp"] == ""                                   # no ownership -> blank


def test_write_raw_matches_pipeline_schema(tmp_path):
    rows = espn_live.parse_players(PAYLOAD)
    out = str(tmp_path / "espn_ranks.csv")
    espn_live.write_raw(rows, out)
    with open(out, newline="", encoding="utf-8") as f:
        got = list(csv.DictReader(f))
    for col in ("rank", "espn_id", "name", "team", "pos"):   # build_espn_adp needs these
        assert col in got[0]
    assert got[0]["espn_id"] == "222" and got[0]["pos"] == "QB"


def test_load_cookies_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        espn_live.load_cookies(str(tmp_path / "nope.json"))


def test_cookies_reject_placeholder(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"espn_s2": "PASTE_YOUR_espn_s2_VALUE_HERE", "SWID": "{PASTE}"}')
    assert espn_live.cookies_configured(str(p)) is False
    with pytest.raises(ValueError):
        espn_live.load_cookies(str(p))


def test_cookies_ok(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"espn_s2": "realtoken", "SWID": "{ABC-123}"}')
    assert espn_live.cookies_configured(str(p)) is True
    c = espn_live.load_cookies(str(p))
    assert c == {"espn_s2": "realtoken", "SWID": "{ABC-123}"}


DRAFT_PAYLOAD = {"draftDetail": {"inProgress": True, "drafted": False, "picks": [
    {"overallPickNumber": 3, "roundId": 1, "roundPickNumber": 3, "teamId": 5, "playerId": 3117251},
    {"overallPickNumber": 1, "roundId": 1, "roundPickNumber": 1, "teamId": 3, "playerId": 4262921},
    {"overallPickNumber": 2, "roundId": 1, "roundPickNumber": 2, "teamId": 4, "playerId": -1},  # not made
]}}


def test_parse_draft_picks_only_made_and_sorted():
    st = espn_live.parse_draft_picks(DRAFT_PAYLOAD)
    assert st["in_progress"] is True and st["drafted"] is False
    assert [p["overall"] for p in st["picks"]] == [1, 3]          # -1 dropped, sorted
    assert st["picks"][0]["espn_id"] == "4262921" and st["picks"][0]["team_id"] == 3
    assert st["picks"][1]["espn_id"] == "3117251"


def test_parse_draft_picks_empty_before_draft():
    data = {"draftDetail": {"inProgress": False, "drafted": False,
                            "picks": [{"overallPickNumber": 1, "playerId": -1}]}}
    st = espn_live.parse_draft_picks(data)
    assert st["picks"] == [] and st["in_progress"] is False
