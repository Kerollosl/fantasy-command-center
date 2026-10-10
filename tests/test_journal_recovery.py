import json
import pytest
from ffcc.draft import journal
from ffcc.draft.state import Pick,DraftState
from ffcc.config import load_league

def test_truncated_final_record(tmp_path,monkeypatch):
 monkeypatch.setattr(journal,'JOURNAL',tmp_path/'journal.jsonl')
 journal.append(Pick(1,1,'alice','Alice','RB'))
 with journal.JOURNAL.open('a') as f:f.write('{"overall":2')
 with pytest.warns(RuntimeWarning):assert len(journal.load())==1

def test_failed_replace_preserves_old_file(tmp_path,monkeypatch):
 monkeypatch.setattr(journal,'JOURNAL',tmp_path/'journal.jsonl');journal.append(Pick(1,1,'alice','Alice','RB'))
 before=journal.JOURNAL.read_bytes()
 def fail(*a):raise OSError('disk unavailable')
 monkeypatch.setattr(journal.os,'replace',fail)
 with pytest.raises(OSError):journal.rewrite([])
 assert journal.JOURNAL.read_bytes()==before

def test_invalid_slot():
 state=DraftState(load_league())
 with pytest.raises(ValueError):state.record(type('P',(),{'key':'a','name':'A','position':'RB'})(),slot=999)
