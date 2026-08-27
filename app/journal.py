import json
from pathlib import Path
from datetime import datetime,timezone
class Journal:
    def __init__(self,path='data/trade_journal.jsonl'): self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
    def write(self,record):
        x=dict(record); x.setdefault('logged_at',datetime.now(timezone.utc).isoformat())
        with self.path.open('a',encoding='utf8') as f:f.write(json.dumps(x,separators=(',',':'))+'\n')
