"""read_rankings accepts both FantasyPros export layouts (spec §3.1 adapter)."""
import pytest

import loaders

FORMAT_A = (
    "rank_ecr,player,pos,team,bye,rank_avg,rank_best,rank_worst,rank_std,adp,tier,pos_rank\n"
    '1,"Ja\'Marr Chase",WR,CIN,6,1.52,1,4,0.92,3,1,WR1\n'
    '2,"Jahmyr Gibbs",RB,DET,8,2.4,2,5,1.1,1,1,RB1\n'
)

FORMAT_B = (
    '"RK",TIERS,"PLAYER NAME",TEAM,"POS","BEST","WORST","AVG.","STD.DEV","ECR VS. ADP"\n'
    '"1",1,"Ja\'Marr Chase",CIN,"WR1","1","1","1.0","0.0","+2"\n'
    '"",1\n'                                                   # blank tier separator
    '"2",1,"Jahmyr Gibbs",DET,"RB1","2","5","2.4","1.1","-1"\n'
    '"149",10,"Houston Texans",HOU,"DST1","151","161","152.4","3.5","-46"\n'
)


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_read_rankings_underscore_export(tmp_path):
    df = loaders.read_rankings(_write(tmp_path, "a.csv", FORMAT_A))
    assert list(df["pos"]) == ["WR", "RB"]
    assert df.iloc[0]["rank_ecr"] == 1 and df.iloc[0]["player"] == "Ja'Marr Chase"
    assert df.iloc[1]["rank_std"] == 1.1


def test_read_rankings_cheatsheet_export_normalizes(tmp_path):
    df = loaders.read_rankings(_write(tmp_path, "b.csv", FORMAT_B))
    assert list(df["rank_ecr"]) == [1, 2, 149]        # blank row dropped
    assert list(df["pos"]) == ["WR", "RB", "DST"]     # 'WR1' -> 'WR', DST kept
    assert df.iloc[2]["player"] == "Houston Texans" and df.iloc[2]["team"] == "HOU"
    assert df.iloc[0]["rank_avg"] == 1.0 and df.iloc[1]["rank_std"] == 1.1


def test_load_rankings_both_formats(tmp_path):
    a = loaders.load_rankings(_write(tmp_path, "a.csv", FORMAT_A))
    b = loaders.load_rankings(_write(tmp_path, "b.csv", FORMAT_B))
    assert a[0] == {"rank": 1, "name": "Ja'Marr Chase", "pos": "WR", "team": "CIN"}
    assert [r["pos"] for r in b] == ["WR", "RB", "DST"]


def test_read_rankings_rejects_unknown_csv(tmp_path):
    with pytest.raises(ValueError):
        loaders.read_rankings(_write(tmp_path, "x.csv", "foo,bar\n1,2\n"))
