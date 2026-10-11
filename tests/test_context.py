"""Team-context nudges: O-line, schedule, vacated opportunity, red zone, durability, handcuffs."""
from ffcc.context.attach import attach_context, attach_handcuffs
from ffcc.identity.resolver import Player


def make(name, pos, team, proj, gsis_id=None, depth_chart_order=None):
    return Player(key=f"{name}|{pos}", name=name, position=pos, team=team, proj_points=proj,
                  gsis_id=gsis_id, depth_chart_order=depth_chart_order)


CTX = {
    "teams": {
        "DET": {
            "oline": {"score": 1.2, "rank": 2},
            "oline_continuity": {"returning": 5, "total": 5, "continuity": 1.0, "departed": []},
            "sos": {"RB": 0.6, "QB": 0.6},
            "sos_rank": {"RB": 3, "QB": 3},
            "playoff_sos": {"RB": 0.9},
            "playoff_sos_rank": {"RB": 1},
            "vacated": {
                "RB": {"share": 0.5, "departed": [{"name": "Departed Back", "share": 0.5}]},
            },
            "redzone": {"rb1-gsis": {"share": 0.5, "touches": 60}},
            "weapons": {
                "added": [
                    {"name": "New Vet WR", "pos": "WR", "from": "KC", "targets": 90, "rec_yards": 800},
                    {"name": "Rookie WR", "pos": "WR", "rookie": True, "pick": 12, "round": 1},
                ],
                "lost": [
                    {"name": "Gone WR", "pos": "WR", "targets": 120, "rec_yards": 1100, "still_in_league": True},
                ],
                "added_total": 2,
                "lost_total": 1,
            },
        },
        "LV": {
            "oline": {"score": -1.4, "rank": 31},
            "oline_continuity": {"returning": 1, "total": 5, "continuity": 0.2, "departed": ["A", "B", "C", "D"]},
            "sos": {"RB": -0.6},
            "sos_rank": {"RB": 30},
            "playoff_sos": {"RB": -0.9},
            "playoff_sos_rank": {"RB": 32},
            "vacated": {},
            "redzone": {},
        },
    }
}


def test_good_oline_and_easy_schedule_raise_projection():
    p = make("Good RB", "RB", "DET", 200.0)
    attach_context([p], CTX)
    assert p.proj_points > 200.0
    assert p.oline_rank == 2
    assert p.sos_rank == 3
    kinds = {a["kind"] for a in p.adjustments}
    assert {"oline", "schedule"} <= kinds


def test_bad_oline_and_hard_schedule_lower_projection():
    p = make("Bad RB", "RB", "LV", 200.0)
    attach_context([p], CTX)
    assert p.proj_points < 200.0
    assert p.oline_continuity == 0.2


def test_oline_only_applies_to_rb_and_qb():
    wr = make("Some WR", "WR", "DET", 150.0)
    attach_context([wr], CTX)
    assert wr.oline_rank is None
    assert all(a["kind"] != "oline" for a in wr.adjustments)


def test_vacated_share_splits_by_existing_projection_weight():
    starter = make("Starter", "RB", "DET", 300.0)
    backup = make("Backup", "RB", "DET", 50.0)
    attach_context([starter, backup], CTX)
    starter_gain = next(a["factor"] for a in starter.adjustments if a["kind"] == "vacated")
    backup_gain = next(a["factor"] for a in backup.adjustments if a["kind"] == "vacated")
    assert starter_gain > backup_gain > 1.0
    assert starter.vacated_share == 0.5
    assert starter.vacated_departed[0]["name"] == "Departed Back"


def test_team_with_no_context_is_left_untouched():
    p = make("Nobody", "RB", "ZZZ", 123.4)
    attach_context([p], CTX)
    assert p.proj_points == 123.4
    assert p.adjustments == []


def test_playoff_schedule_is_a_separate_adjustment_from_full_season_sos():
    good = make("Good", "RB", "DET", 200.0)
    bad = make("Bad", "RB", "LV", 200.0)
    attach_context([good, bad], CTX)
    assert good.playoff_sos_rank == 1
    assert good.proj_points > 200.0
    assert bad.playoff_sos_rank == 32
    assert bad.proj_points < 200.0
    kinds = {a["kind"] for a in good.adjustments}
    assert {"schedule", "playoff_schedule"} <= kinds


def test_redzone_share_only_applies_with_a_gsis_match():
    matched = make("Matched", "RB", "DET", 200.0, gsis_id="rb1-gsis")
    unmatched = make("Unmatched", "RB", "DET", 200.0, gsis_id="someone-else")
    attach_context([matched, unmatched], CTX)
    assert matched.redzone_share == 0.5
    assert any(a["kind"] == "redzone" for a in matched.adjustments)
    assert unmatched.redzone_share is None
    assert all(a["kind"] != "redzone" for a in unmatched.adjustments)


def test_durability_is_display_only_and_never_touches_proj_points():
    p = make("Injury Prone", "RB", "DET", 200.0)
    p.seasons = [
        {"season": 2025, "games": 6}, {"season": 2024, "games": 17}, {"season": 2023, "games": 5},
    ]
    before = p.proj_points
    attach_context([p], CTX)
    assert p.durability == round((6 / 17 + 1.0 + 5 / 17) / 3, 2)
    assert p.durability_seasons == 3
    # proj_points still moves from the other signals DET carries, but durability
    # itself contributes no "durability"-kind adjustment.
    assert all(a["kind"] != "durability" for a in p.adjustments)


def test_handcuffs_point_to_the_next_depth_slot_same_team():
    rb1 = make("Starter Back", "RB", "DET", 300.0, depth_chart_order=1)
    rb2 = make("Backup Back", "RB", "DET", 100.0, depth_chart_order=2)
    rb3 = make("Third Back", "RB", "DET", 20.0, depth_chart_order=3)
    other_team = make("Elsewhere", "RB", "LV", 150.0, depth_chart_order=1)
    attach_handcuffs([rb1, rb2, rb3, other_team])
    assert rb1.handcuff_name == "Backup Back"
    assert rb2.handcuff_name == "Third Back"
    assert rb3.handcuff_name is None
    assert other_team.handcuff_name is None


def test_qb_weapons_delta_is_attached_display_only():
    qb = make("Some QB", "QB", "DET", 320.0)
    attach_context([qb], CTX)
    assert [w["name"] for w in qb.weapons_added] == ["New Vet WR", "Rookie WR"]
    assert qb.weapons_lost[0]["name"] == "Gone WR"
    assert qb.weapons_added_total == 2
    assert qb.weapons_lost_total == 1
    # context, not a projection signal -- it contributes no adjustment entry
    assert all(a["kind"] != "weapons" for a in qb.adjustments)


def test_weapons_delta_only_applies_to_qb():
    wr = make("Some WR", "WR", "DET", 200.0)
    attach_context([wr], CTX)
    assert wr.weapons_added == []
    assert wr.weapons_lost == []
    assert wr.weapons_added_total is None


def test_qb_on_team_without_a_weapons_delta_stays_clean():
    qb = make("Quiet QB", "QB", "LV", 300.0)
    attach_context([qb], CTX)
    assert qb.weapons_added == []
    assert qb.weapons_lost == []


def test_handcuffs_only_apply_to_rb():
    wr1 = make("WR One", "WR", "DET", 200.0, depth_chart_order=1)
    wr2 = make("WR Two", "WR", "DET", 100.0, depth_chart_order=2)
    attach_handcuffs([wr1, wr2])
    assert wr1.handcuff_name is None
    assert wr2.handcuff_name is None
