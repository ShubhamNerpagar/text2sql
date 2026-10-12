from __future__ import annotations
import re, time
from app.config import get_settings
from app.adapters.aws import AwsAdapter

class DataSourceService:
    """Provider-neutral source registry, metadata discovery and governed execution."""
    def __init__(self): self.s=get_settings()

    def sources(self):
        return [
            {'id':'contoso','label':'Test fixture (disabled for normal use)','configured':self.s.enable_sample_execution,'mode':'local','dialect':'sqlite','metadata':'sqlite'},
            {'id':'athena','label':'Amazon Athena + Glue Catalog','configured':bool(self.s.is_aws and self.s.athena_output),'mode':'native','dialect':'athena','metadata':'glue'},
            {'id':'postgres','label':'PostgreSQL / Aurora','configured':bool(self.s.postgres_url),'mode':'sqlalchemy','dialect':'postgresql','metadata':'information_schema'},
            {'id':'snowflake','label':'Snowflake','configured':bool(self.s.snowflake_url),'mode':'sqlalchemy','dialect':'snowflake','metadata':'information_schema'},
            {'id':'databricks','label':'Databricks SQL','configured':bool(self.s.databricks_url),'mode':'sqlalchemy','dialect':'databricks','metadata':'information_schema'},
        ]
    def configured_ids(self): return [x['id'] for x in self.sources() if x['configured']]
    def _url(self,source_id): return {'postgres':self.s.postgres_url,'snowflake':self.s.snowflake_url,'databricks':self.s.databricks_url}.get(source_id)

    def discover(self,source_id,schemas=None):
        source_id=(source_id or '').strip().lower()
        if source_id=='contoso':
            from app.services.contoso_sample_service import ContosoSampleService
            sample=ContosoSampleService()
            objs=[sample.table_details(t) for t in sample.table_names()]
            return {'source_id':'contoso','objects':objs,'count':len(objs),'scope':['contoso_demo'],'sample_rows_used':False}
        if source_id=='athena':
            if not schemas:raise ValueError('Select databases/tables in Data → Enterprise Catalog instead of scanning every database')
            if not self.s.is_aws or not self.s.athena_output: raise RuntimeError('Athena is not configured. Set APP_MODE=aws and ATHENA_OUTPUT.')
            a=AwsAdapter(); dbs=a.list_databases(); out=[]
            for db in dbs:
                if schemas and db not in schemas: continue
                for t in a.list_tables(db):
                    out.append({'database':db,'schema':db,'table':t['name'],'description':t.get('description',''),'location':t.get('location',''),'columns':a.get_columns(db,t['name']),'source_id':'athena'})
            return {'source_id':'athena','objects':out,'count':len(out),'scope':schemas or dbs,'sample_rows_used':False}
        url=self._url(source_id)
        if not url: raise RuntimeError(f'{source_id} is not configured.')
        if not schemas:raise ValueError('Explicit schema scope required. Use Data → Enterprise Catalog')
        try:
            from sqlalchemy import create_engine, inspect
        except ImportError as e: raise RuntimeError('Install SQLAlchemy and the selected dialect driver to activate this connector.') from e
        engine=create_engine(url,pool_pre_ping=True); insp=inspect(engine); out=[]
        try:
            available=schemas or insp.get_schema_names()
            for schema in available:
                if str(schema).lower() in {'information_schema','pg_catalog','sys'}: continue
                for table in insp.get_table_names(schema=schema):
                    try: comment=(insp.get_table_comment(table,schema=schema) or {}).get('text') or ''
                    except Exception: comment=''
                    try: pk=set((insp.get_pk_constraint(table,schema=schema) or {}).get('constrained_columns') or [])
                    except Exception: pk=set()
                    cols=[]
                    for c in insp.get_columns(table,schema=schema):
                        cols.append({'name':c.get('name'),'type':str(c.get('type','')),'nullable':c.get('nullable',True),'comment':c.get('comment') or '','primary_key':c.get('name') in pk})
                    out.append({'database':schema,'schema':schema,'table':table,'description':comment,'columns':cols,'foreign_keys':insp.get_foreign_keys(table,schema=schema) or [],'source_id':source_id})
        finally: engine.dispose()
        return {'source_id':source_id,'objects':out,'count':len(out),'scope':schemas or [],'sample_rows_used':False}

    def health(self):
        out=[]
        for item in self.sources():
            row={'id':item['id'],'configured':item['configured'],'status':'not_configured' if not item['configured'] else 'configured'}
            if item['id']=='contoso':
                row['status']='healthy'
            elif item['id']=='athena' and item['configured']:
                try: AwsAdapter().athena.list_work_groups(MaxResults=1); row['status']='healthy'
                except Exception as e: row['status']='error'; row['detail']=str(e)[:180]
            elif item['configured']:
                try:
                    from sqlalchemy import create_engine, text
                    engine=create_engine(self._url(item['id']),pool_pre_ping=True)
                    with engine.connect() as conn: conn.execute(text('SELECT 1'))
                    engine.dispose(); row['status']='healthy'
                except Exception as e: row['status']='error'; row['detail']=str(e)[:180]
            out.append(row)
        return {'sources':out,'healthy':sum(1 for x in out if x['status']=='healthy'),'configured':sum(1 for x in out if x['configured'])}

    def execute(self,source_id,sql,database=None):
        from app.services.sql_safety import validate_read_only_sql
        ok,message=validate_read_only_sql(sql)
        if not ok:raise ValueError(message)
        source_id=(source_id or '').strip().lower()
        if source_id=='contoso':
            if not self.s.enable_sample_execution:raise ValueError('Synthetic execution is disabled; connect a live data source')
            from app.services.contoso_sample_service import ContosoSampleService
            return ContosoSampleService().execute(sql,self.s.max_result_rows,database)
        if source_id=='athena': return AwsAdapter().execute_query(sql,database)
        url=self._url(source_id)
        if not url: raise RuntimeError(f'{source_id} is not configured.')
        try:
            from sqlalchemy import create_engine, text
        except ImportError as e: raise RuntimeError('Install SQLAlchemy and the selected dialect driver to activate this connector.') from e
        started=time.time(); engine=create_engine(url,pool_pre_ping=True); cols=[]; rows=[]
        try:
            with engine.connect() as conn:
                r=conn.execute(text(sql)); cols=list(r.keys()); rows=[dict(zip(cols,row)) for row in r.fetchmany(self.s.max_result_rows)]
        finally: engine.dispose()
        return {'query_id':f'{source_id}-query','columns':cols,'rows':rows,'row_count':len(rows),'truncated':len(rows)>=self.s.max_result_rows,'bytes_scanned':None,'execution_ms':int((time.time()-started)*1000)}

    @staticmethod
    def _ident(value:str)->str:
        if not value or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',str(value)): raise ValueError(f'Unsafe SQL identifier: {value}')
        return f'"{value}"'

    def relationship_stats(self,source_id:str,relation:dict)->dict:
        """Compute aggregate FK evidence across all supported SQL connectors without returning sample values."""
        q=self._ident
        fdb,ft,fc=relation.get('from_db'),relation.get('from_table'),relation.get('from_column')
        tdb,tt,tc=relation.get('to_db'),relation.get('to_table'),relation.get('to_column')
        src=f'{q(fdb)}.{q(ft)}'; tgt=f'{q(tdb)}.{q(tt)}'; fcol=q(fc); tcol=q(tc)
        sql=(f'WITH src AS (SELECT DISTINCT CAST({fcol} AS VARCHAR) AS v FROM {src} WHERE {fcol} IS NOT NULL), '
             f'tgt AS (SELECT CAST({tcol} AS VARCHAR) AS v, COUNT(*) AS c FROM {tgt} WHERE {tcol} IS NOT NULL GROUP BY 1) '
             'SELECT (SELECT COUNT(*) FROM src) AS source_distinct, '
             '(SELECT COUNT(*) FROM tgt) AS target_distinct, '
             '(SELECT COALESCE(SUM(c),0) FROM tgt) AS target_non_null_rows, '
             '(SELECT COUNT(*) FROM src s JOIN tgt t ON s.v=t.v) AS matched_distinct')
        result=self.execute(source_id,sql,fdb if source_id=='athena' else None); rows=result.get('rows') or []
        if not rows: raise RuntimeError(f'{source_id} returned no validation statistics')
        row=rows[0]
        def num(k):
            try:return float(row.get(k) or 0)
            except:return 0.0
        return {'source_distinct':int(num('source_distinct')),'target_distinct':int(num('target_distinct')),'target_non_null_rows':int(num('target_non_null_rows')),'matched_distinct':int(num('matched_distinct')),'query_id':result.get('query_id'),'bytes_scanned':result.get('bytes_scanned'),'sample_rows_returned':False}
