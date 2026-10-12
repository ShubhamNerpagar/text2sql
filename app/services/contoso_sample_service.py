"""Optional local datasets; natural-language questions still require a verified LLM."""
from __future__ import annotations
from pathlib import Path
import json,sqlite3,time
from contextlib import closing
from app.config import BASE_DIR,get_settings
from app.services.contoso_import_service import DATASET_ID

SAMPLE_DIR=BASE_DIR/'sample-data'/'contoso'

def installed_datasets():
    """Only publish installed databases, with manifests required for additional IDs."""
    found=[]
    for path in sorted(SAMPLE_DIR.glob('contoso_*.sqlite3')):
        name=path.stem
        if not DATASET_ID.fullmatch(name) or path.is_symlink():continue
        manifest_path=SAMPLE_DIR/(name+'.manifest.json')
        manifest={}
        if manifest_path.is_file() and not manifest_path.is_symlink():
            try:
                manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
                if not isinstance(manifest,dict) or manifest.get('schema_version')!=1 or manifest.get('dataset_id')!=name or manifest.get('database')!=path.name:continue
            except (ValueError,OSError):continue
        elif name not in {'contoso_demo','contoso_official'}:continue
        found.append({'database':name,'label':name.replace('_',' '),
            'provenance':manifest.get('provenance') or ('bundled synthetic illustration' if name=='contoso_demo' else 'legacy official installer; see its verification manifest'),
            'total_rows':manifest.get('total_rows'),'upstream_checksum_verified':manifest.get('upstream_checksum_verified',False)})
    return found

class ContosoSampleService:
    def __init__(self):
        self.path=SAMPLE_DIR/'contoso_demo.sqlite3'
    def set_dataset(self,database):
        if database not in {item['database'] for item in installed_datasets()}:raise ValueError('Unknown/uninstalled local dataset')
        self.path=SAMPLE_DIR/(database+'.sqlite3')
        return self
    def _db(self):
        if not self.path.is_file(): raise ValueError('Local Contoso data unavailable; see sample-data/contoso/README.md')
        db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True)
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        return db
    def table_names(self):
        with closing(self._db()) as db:
            return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    def table_details(self,table,database='contoso_demo'):
        self.set_dataset(database)
        if table not in self.table_names(): raise ValueError('Unknown Contoso table')
        with closing(self._db()) as db:
            cols=[{'name':r[1],'type':r[2] or 'TEXT','nullable':not bool(r[3]),'primary_key':bool(r[5])} for r in db.execute(f'PRAGMA table_info("{table}")')]
            groups={}
            for r in db.execute(f'PRAGMA foreign_key_list("{table}")'):
                fk=groups.setdefault(r[0],{'name':f'fk_{table}_{r[0]}','referred_table':r[2], 'referred_schema':'public','constrained_columns':[],'referred_columns':[]})
                fk['constrained_columns'].append(r[3]);fk['referred_columns'].append(r[4])
        return {'source_id':'contoso','database':database,'schema':'public','table':table,'columns':cols,'foreign_keys':list(groups.values()),'sample_rows_used':False}
    def metadata(self):
        info=next((item for item in installed_datasets() if item['database']==self.path.stem),{})
        return {'package':info.get('label','Contoso dataset'),'source':info.get('provenance'),'tables':self.table_names(), 'sqlbi_download':'https://github.com/sql-bi/Contoso-Data-Generator-V2-Data/releases/tag/ready-to-use-data','sample_rows_used':False}
    def execute(self,sql,limit=5000,database=None,*,payload_limit=None):
        database=database or self.path.stem
        self.set_dataset(database)
        from app.services.sql_safety import validate_read_only_sql
        ok,msg=validate_read_only_sql(sql)
        if not ok:raise ValueError(msg)
        start=time.monotonic()
        timeout=get_settings().query_timeout_seconds
        with closing(self._db()) as db:
            db.execute('ATTACH DATABASE ? AS "'+database+'"',(self.path.resolve().as_uri()+'?mode=ro',))
            db.set_progress_handler(lambda:int(time.monotonic()-start>timeout),10000)
            try:
                cur=db.execute(sql); columns=[c[0] for c in (cur.description or [])]
                rows=[];payload=0
                while len(rows)<limit:
                    row=cur.fetchone()
                    if row is None:break
                    item=dict(zip(columns,row))
                    if payload_limit is not None:
                        payload+=len(json.dumps(item,default=str,ensure_ascii=False).encode())
                        if payload>payload_limit:raise ValueError('FEDERATION_LIMIT_EXCEEDED: Contoso payload exceeds snapshot budget')
                    rows.append(item)
            except sqlite3.OperationalError as exc:
                if str(exc)=='interrupted':raise ValueError('Contoso query exceeded configured timeout') from exc
                raise
        return {'query_id':'local-contoso','columns':columns,'rows':rows,'row_count':len(rows),'execution_ms':int((time.monotonic()-start)*1000),'bytes_scanned':None,'truncated':len(rows)==limit}
