"""Draft-state crash recovery: picks survive a server restart."""
from ffcc.draft import journal
from ffcc.draft.state import Pick


def _pick(overall, name="Player", pos="RB", slot=1):
    return Pick(overall=overall, team_slot=slot, player_key=f"{name.lower()}|{pos}",
                player_name=name, position=pos)


def test_append_then_load_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL", tmp_path / "draft_journal.jsonl")
    journal.append(_pick(1, "Alice"))
    journal.append(_pick(2, "Bob"))
    loaded = journal.load()
    assert [p.player_name for p in loaded] == ["Alice", "Bob"]
    assert loaded[0].overall == 1 and loaded[0].team_slot == 1


def test_load_with_no_journal_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL", tmp_path / "missing.jsonl")
    assert journal.load() == []


def test_rewrite_drops_the_undone_pick(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL", tmp_path / "draft_journal.jsonl")
    journal.append(_pick(1, "Alice"))
    journal.append(_pick(2, "Bob"))
    journal.rewrite([_pick(1, "Alice")])
    assert [p.player_name for p in journal.load()] == ["Alice"]


def test_clear_removes_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr(journal, "JOURNAL", tmp_path / "draft_journal.jsonl")
    journal.append(_pick(1, "Alice"))
    journal.clear()
    assert journal.load() == []
    assert not journal.JOURNAL.exists()
