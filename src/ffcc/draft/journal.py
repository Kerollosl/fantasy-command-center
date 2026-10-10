"""Atomic journal replacement and configuration-scoped recovery."""
from __future__ import annotations
import dataclasses,hashlib,json,os,tempfile,warnings
from pathlib import Path
from ..config import DATA_DIR
from .state import Pick
JOURNAL=DATA_DIR/"draft_journal.jsonl"

def configure(cfg,session="default"):
 global JOURNAL
 values=dataclasses.asdict(cfg);values.pop("my_draft_slot",None)
 key=hashlib.sha256(json.dumps({"league":values,"session":session},sort_keys=True).encode()).hexdigest()[:20]
 JOURNAL=DATA_DIR/f"draft_{key}.jsonl"
 legacy=DATA_DIR/"draft_journal.jsonl"
 if legacy.exists() and not JOURNAL.exists():
  scoped=JOURNAL
  try:
   JOURNAL=legacy; picks=load()
   if any(p.team_slot > cfg.teams for p in picks):
    raise ValueError("Legacy draft does not match league; original retained")
   JOURNAL=scoped; rewrite(picks)
   legacy.rename(DATA_DIR/"draft_journal.migrated.jsonl")
  finally: JOURNAL=scoped


def rewrite(picks):
 JOURNAL.parent.mkdir(parents=True,exist_ok=True)
 fd,name=tempfile.mkstemp(dir=JOURNAL.parent,prefix='.draft-',suffix='.tmp')
 try:
  with os.fdopen(fd,'w') as f:
   for pick in picks:f.write(json.dumps(dataclasses.asdict(pick))+'\n')
   f.flush();os.fsync(f.fileno())
  os.replace(name,JOURNAL)
 finally:
  if os.path.exists(name):os.unlink(name)

def append(pick):rewrite(load()+[pick])

def load():
 if not JOURNAL.exists():return []
 lines=JOURNAL.read_text().splitlines();picks=[];seen=set()
 for i,line in enumerate(lines):
  if not line.strip():continue
  try:p=Pick(**json.loads(line))
  except (ValueError,TypeError) as e:
   if i==len(lines)-1:
    warnings.warn('Ignored incomplete final draft record; valid picks recovered',RuntimeWarning);break
   raise ValueError(f'Corrupt draft journal at line {i+1}; original file retained') from e
  if p.overall!=len(picks)+1 or p.player_key in seen or type(p.team_slot) is not int or p.team_slot<1:raise ValueError('Invalid pick sequence in journal')
  seen.add(p.player_key);picks.append(p)
 return picks

def clear():
 rewrite([])
 JOURNAL.unlink(missing_ok=True)
