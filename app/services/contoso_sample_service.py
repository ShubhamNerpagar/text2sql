"""Offline sample selector. Bundled SQLite is an *illustrative generated* retail dataset,
not an unmodified SQLBI release. Optional official SQLBI CSV installer replaces it.
"""
from __future__ import annotations
from pathlib import Path
import sqlite3
from app.config import BASE_DIR

SAMPLE_DIR=BASE_DIR/'sample-data'/'contoso'

class ContosoSampleService:
    def __init__(self):
        self.path=SAMPLE_DIR/'contoso_demo.sqlite3'
    def set_dataset(self,database):
        if database=='contoso_official' and (SAMPLE_DIR/'contoso_official.sqlite3').exists():self.path=SAMPLE_DIR/'contoso_official.sqlite3'
        elif database=='contoso_demo':self.path=SAMPLE_DIR/'contoso_demo.sqlite3'
        else:raise ValueError('Unknown/uninstalled local dataset')
        return self
    def _db(self):
        if not self.path.is_file(): raise ValueError('Local Contoso data unavailable; see sample-data/contoso/README.md')
        return sqlite3.connect(f'file:{self.path.as_posix()}?mode=ro',uri=True)
    def table_names(self):
        with self._db() as db:
            return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    def table_details(self,table,database='contoso_demo'):
        self.set_dataset(database)
        if table not in self.table_names(): raise ValueError('Unknown Contoso table')
        with self._db() as db:
            cols=[{'name':r[1],'type':r[2] or 'TEXT','nullable':not bool(r[3]),'primary_key':bool(r[5])} for r in db.execute(f'PRAGMA table_info("{table}")')]
            groups={}
            for r in db.execute(f'PRAGMA foreign_key_list("{table}")'):
                fk=groups.setdefault(r[0],{'name':f'fk_{table}_{r[0]}','referred_table':r[2], 'referred_schema':'public','constrained_columns':[],'referred_columns':[]})
                fk['constrained_columns'].append(r[3]);fk['referred_columns'].append(r[4])
        return {'source_id':'contoso','database':database,'schema':'public','table':table,'columns':cols,'foreign_keys':list(groups.values()),'sample_rows_used':False}
    def metadata(self):
        return {'package':'Contoso retail illustration','source':'bundled synthetic demonstration; NOT the official SQLBI dataset','tables':self.table_names(), 'sqlbi_download':'https://github.com/sql-bi/Contoso-Data-Generator-V2-Data/releases/tag/ready-to-use-data','sample_rows_used':False}
    def execute(self,sql,limit=5000,database=None):
        database=database or 'contoso_official' if self.path.name=='contoso_official.sqlite3' else database or 'contoso_demo'
        self.set_dataset(database)
        from app.services.sql_safety import validate_read_only_sql
        ok,msg=validate_read_only_sql(sql)
        if not ok:raise ValueError(msg)
        import time
        start=time.monotonic()
        with self._db() as db:
            db.execute('ATTACH DATABASE ? AS '+database,(str(self.path),))
            db.execute('PRAGMA query_only=ON')
            cur=db.execute(sql); columns=[c[0] for c in (cur.description or [])]
            rows=[dict(zip(columns,r)) for r in cur.fetchmany(limit)]
        return {'query_id':'local-contoso','columns':columns,'rows':rows,'row_count':len(rows),'execution_ms':int((time.monotonic()-start)*1000),'bytes_scanned':None,'truncated':len(rows)==limit}
