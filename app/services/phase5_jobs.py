"""Phase 5 SQLite job broker: atomic cross-process claims, leases and retries.

Only safely bounded, explicitly allowlisted tasks are dispatched by the worker.
SQLite supports multiple processes on one shared *host*, not a networked cluster.
For multiple hosts deploy a tested transactional queue backend first.
"""
from __future__ import annotations
import json, sqlite3, time
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from app.config import get_settings

TYPES={'profile','golden_suite','connector_benchmark','search_snapshot'}
TERMINAL={'succeeded','dead','cancelled'}
def iso(t=None):return datetime.fromtimestamp(t or time.time(),timezone.utc).isoformat()

class JobStore:
    def __init__(self,path=None):
        s=get_settings(); self.path=Path(path or s.state_dir/'phase5-jobs.sqlite3')
        self.path.parent.mkdir(parents=True,exist_ok=True);self._initialize()
    def _connect(self):
        conn=sqlite3.connect(str(self.path),timeout=15,isolation_level=None)
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA busy_timeout=15000')
        return conn
    def _initialize(self):
        with self._connect() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript('''CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, workspace TEXT NOT NULL, task TEXT NOT NULL, payload TEXT NOT NULL,
              status TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 0,
              attempts INTEGER NOT NULL DEFAULT 0,max_attempts INTEGER NOT NULL DEFAULT 3,
              owner TEXT,lease_until REAL, available_at REAL NOT NULL,
              cancel_requested INTEGER NOT NULL DEFAULT 0,
              idem TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
              result TEXT,error TEXT);
              CREATE UNIQUE INDEX IF NOT EXISTS uq_p5_idem ON jobs(workspace,idem) WHERE idem IS NOT NULL;
              CREATE INDEX IF NOT EXISTS idx_p5_claim ON jobs(status,available_at,priority);
              CREATE INDEX IF NOT EXISTS idx_p5_workspace ON jobs(workspace,created_at);
              CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                at TEXT NOT NULL, level TEXT NOT NULL, event TEXT NOT NULL,detail TEXT);
              CREATE INDEX IF NOT EXISTS idx_p5_events ON events(job_id,id);''')
    @staticmethod
    def _row(r):
        if not r:return None
        d=dict(r);d['payload']=json.loads(d['payload']);d['result']=json.loads(d['result']) if d['result'] else None
        d['cancel_requested']=bool(d['cancel_requested']);return d
    @staticmethod
    def _event(c,jid,level,event,detail=None):
        c.execute('INSERT INTO events(job_id,at,level,event,detail) VALUES(?,?,?,?,?)',(jid,iso(),level,event,json.dumps(detail or {},default=str)))
    def enqueue(self,workspace,task,payload,actor,idem=None,priority=0,max_attempts=3):
        if task not in TYPES:raise ValueError('Job type not allowlisted')
        if not isinstance(payload,dict):raise ValueError('Job payload must be an object')
        if not 1<=max_attempts<=5 or not -5<=priority<=5:raise ValueError('Invalid retry/priority policy')
        if idem is not None and not 4<=len(idem)<=100:raise ValueError('Idempotency key must be 4–100 chars')
        job_id=uuid4().hex;now=iso()
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if idem:
                old=c.execute('SELECT * FROM jobs WHERE workspace=? AND idem=?',(workspace,idem)).fetchone()
                if old:
                    if old['task']!=task or json.loads(old['payload'])!=payload:
                        raise ValueError('Idempotency key already used for a different payload')
                    return self._row(old)
            c.execute('''INSERT INTO jobs(id,workspace,task,payload,status,priority,max_attempts,
                        available_at,idem,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                      (job_id,workspace,task,json.dumps(payload), 'queued',priority,max_attempts,time.time(),idem,now,now))
            self._event(c,job_id,'info','queued',{'actor':actor,'task':task})
            return self._row(c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone())
    def get(self,workspace,job_id):
        with self._connect() as c:
            r=c.execute('SELECT * FROM jobs WHERE workspace=? AND id=?',(workspace,job_id)).fetchone()
        if not r:raise KeyError('Job not found in workspace')
        return self._row(r)
    def list(self,workspace,limit=50,status=None):
        with self._connect() as c:
            if status:
                rows=c.execute('SELECT * FROM jobs WHERE workspace=? AND status=? ORDER BY created_at DESC LIMIT ?', (workspace,status,limit)).fetchall()
            else:
                rows=c.execute('SELECT * FROM jobs WHERE workspace=? ORDER BY created_at DESC LIMIT ?',(workspace,limit)).fetchall()
        return [self._row(r) for r in rows]
    def events(self,workspace,job_id,limit=100):
        self.get(workspace,job_id)
        with self._connect() as c:
            rows=c.execute('SELECT at,level,event,detail FROM events WHERE job_id=? ORDER BY id DESC LIMIT ?',(job_id,limit)).fetchall()
        return [{**dict(r),'detail':json.loads(r['detail'] or '{}')} for r in reversed(rows)]
    def claim(self,worker,lease_seconds=90):
        if not 10<=lease_seconds<=1800:raise ValueError('Lease must be 10–1800 seconds')
        now=time.time()
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            # Expired running leases are reclaimed; their attempts count remains.
            row=c.execute('''SELECT * FROM jobs WHERE
                 ((status IN ('queued','retry') AND available_at<=?) OR
                  (status='running' AND lease_until<=?))
                 ORDER BY priority DESC,available_at ASC,created_at ASC LIMIT 1''',(now,now)).fetchone()
            if not row:return None
            jid=row['id']
            if row['cancel_requested']:
                c.execute("UPDATE jobs SET status='cancelled',owner=NULL,lease_until=NULL,updated_at=? WHERE id=?",(iso(),jid))
                self._event(c,jid,'warn','cancelled_before_claim')
                return None
            if row['attempts']>=row['max_attempts']:
                c.execute("UPDATE jobs SET status='dead',owner=NULL,lease_until=NULL,updated_at=?,error=? WHERE id=?",(iso(),'Lease expired after final attempt',jid))
                self._event(c,jid,'error','dead_after_lease')
                return None
            c.execute('''UPDATE jobs SET status='running',attempts=attempts+1,
                owner=?,lease_until=?,updated_at=? WHERE id=?''',(worker,now+lease_seconds,iso(),jid))
            self._event(c,jid,'info','claimed',{'worker':worker,'attempt':row['attempts']+1})
            return self._row(c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
    def heartbeat(self,job,worker,attempt,lease_seconds=90,workspace=None):
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            n=c.execute('''UPDATE jobs SET lease_until=?,updated_at=? WHERE id=? AND status='running'
                AND owner=? AND attempts=? AND lease_until>=?''',(time.time()+lease_seconds,iso(),job,worker,attempt,time.time())).rowcount
            return bool(n)
    def finish(self,job,worker,attempt,result=None,error=None,workspace=None):
        now=time.time()
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
            if not row or row['owner']!=worker or row['status']!='running' or row['attempts']!=attempt or (row['lease_until'] or 0)<now:
                raise ValueError('Worker does not own a live job lease')
            cancelled=bool(row['cancel_requested'])
            if cancelled:status='cancelled';available=now;event='cancelled'
            elif error:
                status='retry' if attempt<row['max_attempts'] else 'dead'
                available=now+min(300,2**attempt);event='retry_scheduled' if status=='retry' else 'dead'
            else:status='succeeded';available=now;event='succeeded'
            c.execute('''UPDATE jobs SET status=?,available_at=?,owner=NULL,lease_until=NULL,
                result=?,error=?,updated_at=? WHERE id=?''',
                (status,available,json.dumps(result,default=str) if not error and not cancelled else None,str(error)[:500] if error else None,iso(),job))
            self._event(c,job,'error' if error else 'info',event,{'error':str(error)[:250] if error else '', 'attempt':attempt})
            return self._row(c.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone())
    def cancel(self,workspace,job,actor):
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM jobs WHERE id=? AND workspace=?',(job,workspace)).fetchone()
            if not row:raise KeyError('Job not found in workspace')
            if row['status'] in TERMINAL:return self._row(row)
            if row['status']=='running':
                c.execute('UPDATE jobs SET cancel_requested=1,updated_at=? WHERE id=?',(iso(),job))
            else:
                c.execute("UPDATE jobs SET status='cancelled',updated_at=? WHERE id=?",(iso(),job))
            self._event(c,job,'warn','cancel_requested',{'actor':actor})
            return self._row(c.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone())
    def retry(self,workspace,job,actor):
        with self._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM jobs WHERE id=? AND workspace=?',(job,workspace)).fetchone()
            if not row:raise KeyError('Job not found in workspace')
            if row['status'] not in {'dead','cancelled'}:raise ValueError('Only dead/cancelled jobs may be retried manually')
            c.execute("UPDATE jobs SET status='queued',attempts=0,owner=NULL,cancel_requested=0,lease_until=NULL,available_at=?,error=NULL,result=NULL,updated_at=? WHERE id=?",(time.time(),iso(),job))
            self._event(c,job,'info','requeued',{'actor':actor})
            return self._row(c.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone())
    def summary(self,workspace):
        with self._connect() as c:
            rows=c.execute('SELECT status,COUNT(*) AS n FROM jobs WHERE workspace=? GROUP BY status',(workspace,)).fetchall()
        return {r['status']:r['n'] for r in rows}
