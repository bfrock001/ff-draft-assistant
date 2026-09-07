"""projections._stat_line parses by column name, anchored on marker columns, so
it survives added columns (Team/CMP/ATT) and flipped block order across export
versions (spec §3.1 adapter). Pure — no data files needed."""
from projections import _stat_line


def test_qb_new_layout_with_cmp_and_team():
    h = ["PLAYER", "TEAM", "ATT", "CMP", "YDS", "TDS", "INTS", "ATT", "YDS", "TDS", "FL", "FPTS"]
    s = _stat_line("QB", h, ["Josh Allen", "BUF", "504", "341", "3889", "26", "11",
                             "115", "577", "11", "4", "367"])
    assert s["pass_yds"] == 3889 and s["pass_td"] == 26 and s["pass_int"] == 11
    assert s["rush_yds"] == 577 and s["rush_td"] == 11 and s["fumbles_lost"] == 4


def test_wr_rushing_first_layout():
    h = ["PLAYER", "TEAM", "ATT", "YDS", "TDS", "REC", "YDS", "TDS", "FL", "FPTS"]
    s = _stat_line("WR", h, ["X", "CIN", "2", "12", "0", "122", "1505", "11", "1", "338"])
    assert s["rush_yds"] == 12 and s["rec"] == 122
    assert s["rec_yds"] == 1505 and s["rec_td"] == 11


def test_wr_receiving_first_no_team_old_layout():
    h = ["PLAYER", "REC", "YDS", "TDS", "ATT", "YDS", "TDS", "FL", "FPTS"]
    s = _stat_line("WR", h, ["Puka LAR", "117", "1539", "9", "13", "85", "1", "1", "281"])
    assert s["rec"] == 117 and s["rec_yds"] == 1539 and s["rec_td"] == 9
    assert s["rush_yds"] == 85


def test_rb_rush_then_receiving():
    h = ["PLAYER", "TEAM", "ATT", "YDS", "TDS", "REC", "YDS", "TDS", "FL", "FPTS"]
    s = _stat_line("RB", h, ["Gibbs", "DET", "267", "1413", "13", "70", "566", "4", "1", "369"])
    assert s["rush_yds"] == 1413 and s["rush_td"] == 13
    assert s["rec"] == 70 and s["rec_yds"] == 566 and s["rec_td"] == 4


def test_dst_and_k_by_name():
    dst_h = ["PLAYER", "TEAM", "SACK", "INT", "FR", "FF", "TD", "SAFETY", "PA", "YDS_AGN", "FPTS"]
    d = _stat_line("DST", dst_h, ["Texans", "", "49", "14", "11", "18", "2", "1", "322", "5060", "120"])
    assert d["sack"] == 49 and d["int"] == 14 and d["pa"] == 322
    k_h = ["PLAYER", "TEAM", "FG", "FGA", "XPT", "FPTS"]
    k = _stat_line("K", k_h, ["Aubrey", "DAL", "35", "40", "44", "150"])
    assert k["fg"] == 35 and k["fga"] == 40 and k["xpm"] == 44
