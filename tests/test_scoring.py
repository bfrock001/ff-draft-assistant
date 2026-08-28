import math

from scoring import (
    dst_points_allowed_points,
    field_goal_points,
    score_stat_line,
)


def approx(a, b):
    assert math.isclose(a, b, abs_tol=1e-9), f"{a} != {b}"


def test_qb_line():
    # 300*0.04 + 3*4 + 1*-2 + 25*0.1 + 1*6 = 12 + 12 - 2 + 2.5 + 6
    approx(score_stat_line(
        {"pass_yds": 300, "pass_td": 3, "pass_int": 1, "rush_yds": 25, "rush_td": 1}
    ), 30.5)


def test_rb_ppr_line():
    # 95*0.1 + 6 + 5*1 + 40*0.1 + 1*-2 = 9.5 + 6 + 5 + 4 - 2
    approx(score_stat_line(
        {"rush_yds": 95, "rush_td": 1, "rec": 5, "rec_yds": 40, "fumbles_lost": 1}
    ), 22.5)


def test_wr_ppr_line():
    # 8*1 + 130*0.1 + 2*6 = 8 + 13 + 12
    approx(score_stat_line({"rec": 8, "rec_yds": 130, "rec_td": 2}), 33.0)


def test_two_point_conversions():
    approx(score_stat_line({"pass_2pt": 1}), 2.0)
    approx(score_stat_line({"rush_2pt": 1, "rec_2pt": 1}), 4.0)


def test_kicker_from_distances():
    # 3 PAT + FG 22->3, 45->4, 51->5
    approx(score_stat_line({"xpm": 3, "fg_distances": [22, 45, 51]}), 15.0)


def test_kicker_from_bands():
    # 4 PAT + 2*3 + 1*4 + 1*5
    approx(score_stat_line(
        {"xpm": 4, "fg_0_39": 2, "fg_40_49": 1, "fg_50_plus": 1}
    ), 19.0)


def test_fg_distance_band_boundaries():
    approx(field_goal_points([39]), 3.0)
    approx(field_goal_points([40]), 4.0)
    approx(field_goal_points([49]), 4.0)
    approx(field_goal_points([50]), 5.0)


def test_dst_full_line():
    # 3 sack + 2 int*2 + 1 fum*2 + 1 td*6 + 1 safety*2 + PA(10)->3
    approx(score_stat_line({
        "dst_sacks": 3, "dst_int": 2, "dst_fumble_rec": 1, "dst_td": 1,
        "dst_safety": 1, "dst_points_allowed": 10,
    }), 20.0)


def test_dst_shutout():
    # 1 sack + PA(0)->5
    approx(score_stat_line({"dst_sacks": 1, "dst_points_allowed": 0}), 6.0)


def test_dst_points_allowed_tiers():
    cases = [(0, 5), (1, 4), (6, 4), (7, 3), (13, 3), (14, 1), (17, 1),
             (18, 0), (27, 0), (28, -1), (34, -1), (35, -3), (50, -3)]
    for pa, expected in cases:
        approx(dst_points_allowed_points(pa), expected)


def test_non_dst_line_has_no_points_allowed_bonus():
    # No dst_points_allowed key -> must not receive the 0-allowed +5 tier.
    approx(score_stat_line({"rec": 5, "rec_yds": 50}), 10.0)


def test_empty_line_is_zero():
    approx(score_stat_line({}), 0.0)
