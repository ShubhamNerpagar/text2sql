"""Consistent online SQLite backup plus a point-in-time copy of JSON metadata."""
from pathlib import Path
from datetime import datetime,timezone
import json,shutil,sqlite3,hashlib
from app.config import get_settings

def backup():
    state=get_settings().state_dir
    if not state.exists():raise ValueError('Missing STATE_DIR')
    dst=state/'backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dst.mkdir(parents=True,exist_ok=False)
    source=state/'phase5-jobs.sqlite3'
    if source.exists():
        with sqlite3.connect(source) as s,sqlite3.connect(dst/'phase5-jobs.sqlite3') as d:s.backup(d)
    src=state/'control-plane.json'
    if src.exists():shutil.copy2(src,dst/'control-plane.json')
    manifest={'backup_type':'operator_initiated_local','at':datetime.now(timezone.utc).isoformat(),
             'files':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in dst.iterdir()}}
    (dst/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('✅',dst)
if __name__=='__main__':backup()
