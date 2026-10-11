"""Grading a single pick.

The trap this guards against: value-above-slot is not comparable across
rounds. The VOR curve is steep early and flat late, so a round-15 pick
routinely posts a bigger delta than a perfect round-1 pick can. Grading on
the whole draft therefore rates a last-round kicker above the first player
off the board, which is not a judgment anyone would defend.
"""
from dataclasses import dataclass, replace

from ffcc.config import load_league
from ffcc.draft.grade import pick_report
from ffcc.draft.state import DraftState


@dataclass
class P:
    key: str
    name: str
    position: str
    proj_points: float = 100.0
    vor: float = 0.0
    adp: float | None = None
    bye: int | None = None


def mk(n, pos, vor, adp):
    return P(key=f"{n}|{pos}", name=n, position=pos, vor=vor, adp=adp)


def pool(cfg):
    """A market whose value falls off steeply and then flattens, like a real one."""
    out = []
    for i in range(cfg.total_picks + 20):
        pos = ("RB", "WR", "TE", "QB")[i % 4]
        out.append(mk(f"p{i:03d}", pos, vor=max(200.0 - 1.6 * i, -30.0), adp=float(i + 1)))
    return out


def draft_in_order(cfg, players, n=None):
    st = DraftState(cfg)
    for p in players[: n if n is not None else cfg.total_picks]:
        st.record(p)
    return st


def test_no_report_for_a_pick_that_was_never_made():
    cfg = load_league()
    players = pool(cfg)
    st = draft_in_order(cfg, players, n=5)
    assert pick_report(st, players, cfg, 9) is None


def test_taking_the_best_player_left_is_never_graded_below_an_a():
    """At pick 1 the curve IS the best player's VOR, so value there is capped
    at zero and the raw z-score reads as a reach. Taking the best player on
    the board is the most this board can ask of a pick."""
    cfg = load_league()
    players = pool(cfg)
    st = draft_in_order(cfg, players)

    r = pick_report(st, players, cfg, 1)
    assert r["took_best"] is True
    # He was the best on the board, by the margin to the next man up.
    assert r["left_on_board"] > 0
    assert r["value"] == 0.0          # the artefact the floor exists to cover
    assert r["letter"] in ("A+", "A")


def test_reaching_past_a_better_player_is_charged_for_it():
    cfg = load_league()
    players = pool(cfg)
    # Take the 40th-best player first; everyone better is still on the board.
    reach = players[39]
    st = DraftState(cfg)
    st.record(reach)
    for p in players:
        if p.key != reach.key and len(st.picks) < cfg.total_picks:
            st.record(p)

    r = pick_report(st, players, cfg, 1)
    assert r["took_best"] is False
    assert r["left_on_board"] < 0
    assert r["best_available"]["name"] == players[0].name


def test_grade_is_windowed_by_round_not_the_whole_draft():
    """A late pick's raw value can exceed an early pick's by construction. The
    letter must not simply follow raw value, or the last round wins the draft.
    """
    cfg = load_league()
    players = pool(cfg)
    st = draft_in_order(cfg, players)

    last = pick_report(st, players, cfg, cfg.total_picks)
    first_round = [pick_report(st, players, cfg, o) for o in range(1, cfg.teams + 1)]

    # Compared only against its own neighbourhood, not all 210 picks.
    assert last["compared_to"] < cfg.total_picks
    assert last["of"] == cfg.teams
    assert all(r["of"] == cfg.teams for r in first_round)
    # Rank is within the round, so it can never exceed the number of teams.
    assert 1 <= last["rank"] <= cfg.teams


def test_pick_coordinates_match_the_snake():
    cfg = load_league()
    players = pool(cfg)
    st = draft_in_order(cfg, players)

    first = pick_report(st, players, cfg, 1)
    assert (first["round"], first["pick_in_round"]) == (1, 1)

    turn = pick_report(st, players, cfg, cfg.teams + 1)
    assert (turn["round"], turn["pick_in_round"]) == (2, 1)
    # Round 2 reverses: its first pick belongs to the team that picked last.
    assert turn["slot"] == cfg.teams


def test_adp_delta_is_positive_when_a_player_lasts_past_his_adp():
    """Sign matters: this drives the words "fell to you" vs "taken early", and
    reading it backwards praises a reach and calls a steal a mistake."""
    cfg = load_league()
    players = pool(cfg)
    # p000 has adp 1.0; drafting him 3rd means he lasted two picks longer.
    order = [players[1], players[2], players[0]] + players[3:]
    st = draft_in_order(cfg, order)
    assert pick_report(st, players, cfg, 3)["adp_delta"] == 2.0

    # And the other direction: p002 has adp 3.0, taken at pick 2.
    assert pick_report(st, players, cfg, 2)["adp_delta"] == -1.0


def test_position_rank_counts_only_players_already_gone():
    cfg = load_league()
    players = pool(cfg)
    st = draft_in_order(cfg, players)

    rbs = [o for o, pk in enumerate(st.picks, start=1) if pk.position == "RB"]
    assert pick_report(st, players, cfg, rbs[0])["pos_rank"] == 1
    assert pick_report(st, players, cfg, rbs[3])["pos_rank"] == 4


def test_my_own_picks_are_flagged():
    cfg = replace(load_league(), my_draft_slot=1)
    players = pool(cfg)
    st = draft_in_order(cfg, players)
    assert pick_report(st, players, cfg, 1)["mine"] is True
    assert pick_report(st, players, cfg, 2)["mine"] is False
