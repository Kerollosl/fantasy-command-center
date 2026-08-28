from ffcc.config import load_league


def test_snake_order_reverses_each_round():
    cfg = load_league()
    order = cfg.snake_order()
    assert order[: cfg.teams] == list(range(1, cfg.teams + 1))
    assert order[cfg.teams : 2 * cfg.teams] == list(range(cfg.teams, 0, -1))
    assert len(order) == cfg.total_picks


def test_my_picks_match_slot():
    cfg = load_league()
    picks = cfg.my_pick_numbers()
    assert len(picks) == cfg.rounds
    order = cfg.snake_order()
    assert all(order[p - 1] == cfg.my_draft_slot for p in picks)


def test_replacement_rank_uses_league_size_not_constants():
    cfg = load_league()
    # QB: one starter per team, no flex share.
    assert cfg.replacement_rank("QB") == cfg.teams
    # RB/WR absorb flex, so they must exceed their dedicated starter count.
    assert cfg.replacement_rank("RB") > cfg.roster["RB"] * cfg.teams
