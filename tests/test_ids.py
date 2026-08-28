from ids import PlayerResolver, normalize_name

CROSSWALK = [
    {"id": "1", "name": "Ja'Marr Chase", "pos": "WR", "team": "CIN"},
    {"id": "2", "name": "Marvin Harrison Jr.", "pos": "WR", "team": "ARI"},
    {"id": "3", "name": "Jaxon Smith-Njigba", "pos": "WR", "team": "SEA"},
    {"id": "4", "name": "Houston Texans", "pos": "DST", "team": "HOU"},
]


def test_normalize_suffix_and_punct():
    assert normalize_name("Marvin Harrison Jr.") == "marvin harrison"
    assert normalize_name("Marvin Harrison Jr") == "marvin harrison"
    assert normalize_name("Ja'Marr Chase") == "jamarr chase"
    assert normalize_name("A.J. Brown") == "aj brown"
    assert normalize_name("Jaxon Smith-Njigba") == "jaxon smith njigba"
    assert normalize_name("Kenneth Walker III") == "kenneth walker"
    assert normalize_name("D'Andre Swift") == "dandre swift"
    assert normalize_name("  Kyle   Pitts   Sr. ") == "kyle pitts"


def test_exact_match_ignores_punctuation():
    r = PlayerResolver(CROSSWALK)
    assert r.resolve("JaMarr Chase", "WR", "CIN") == ("1", "exact")


def test_name_pos_fallback_when_team_differs():
    r = PlayerResolver(CROSSWALK)
    # right player, stale team on the source row -> still resolves
    assert r.resolve("Marvin Harrison", "WR", "CLE") == ("2", "name_pos")


def test_fuzzy_match_on_typo():
    r = PlayerResolver(CROSSWALK)
    pid, method = r.resolve("Jaxon Smith Njigbaa", "WR", "SEA")
    assert pid == "3"
    assert method in ("fuzzy", "name_pos")


def test_manual_override_wins():
    r = PlayerResolver(CROSSWALK, overrides={"Isaiah Williams": "999"})
    assert r.resolve("Isaiah Williams", "WR", "NYJ") == ("999", "override")


def test_unmatched_is_reported_not_dropped():
    r = PlayerResolver(CROSSWALK)
    assert r.resolve("Nobody Here", "WR", "XXX") == (None, "unmatched")


def test_dst_resolves_by_team_name():
    r = PlayerResolver(CROSSWALK)
    assert r.resolve("Houston Texans", "DST", "HOU") == ("4", "exact")
