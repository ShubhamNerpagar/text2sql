"""Phase 1: lazy, scoped, paginated metadata discovery.

Never query business rows. Never enumerate columns for a whole database.
Postgres exposes only the database in the configured connection URL.
"""
from __future__ import annotations
import base64
import json
import re
from urllib.parse import urlsplit
# SQLAlchemy and SQL drivers are imported only when a configured connector is used
from app.config import get_settings
from app.adapters.aws import AwsAdapter

IDENT = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_\-$]*$')
SUPPORTED = ('athena', 'postgres', 'snowflake', 'databricks', 'contoso')


def safe_identifier(v):
    if not v or not IDENT.fullmatch(str(v)):
        raise ValueError('Invalid metadata identifier. Use a name from catalog discovery.')
    return str(v)


def _encode(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')


def _decode(value):
    if not value: return {}
    try:
        if len(value)>2048: raise ValueError()
        d=json.loads(base64.urlsafe_b64decode(value+'='*(-len(value)%4)).decode())
        if not isinstance(d,dict) or set(d)-{'token','offset'}: raise ValueError()
        return d
    except Exception: raise ValueError('Invalid pagination cursor')


class EnterpriseCatalogService:
    def __init__(self):
        self.s=get_settings()

    def _engine(self,source):
        u={'postgres':self.s.postgres_url,'snowflake':self.s.snowflake_url,'databricks':self.s.databricks_url}.get(source)
        if not u: raise ValueError(f'{source} connector is not configured; set its connection URL in .env')
        from sqlalchemy import create_engine
        return create_engine(u,pool_pre_ping=True)

    @staticmethod
    def _paginate(items,q,limit,cursor):
        limit=min(max(int(limit),1),100)
        items=[x for x in items if q.lower() in x.lower()] if q else items
        start=int(_decode(cursor).get('offset',0))
        if start<0 or start>len(items): raise ValueError('Invalid offset')
        page=items[start:start+limit]
        return {'items':[{'name':v} for v in page], 'next_cursor':_encode({'offset':start+limit}) if start+limit<len(items) else None,'returned':len(page),'total':len(items)}

    def catalogs(self,source, q='',limit=50,cursor=None):
        if source=='contoso': return self._paginate(['Bundled Sample'],q,limit,cursor)
        if source=='athena':
            if not self.s.is_aws: raise ValueError('APP_MODE=aws required for Athena')
            # Lake Formation and cross-account Glue catalogs require additional IAM and discovery support.
            catalogs=[self.s.athena_catalog]
            return self._paginate(catalogs,q,limit,cursor)
        if source=='postgres': return self._paginate(['PostgreSQL'],q,limit,cursor)
        if source=='snowflake':
            return self._show(source,'SHOW DATABASES',q,limit,cursor,('name','database_name'))
        if source=='databricks':
            return self._show(source,'SHOW CATALOGS',q,limit,cursor,('catalog','catalog_name'))
        raise ValueError('Unsupported data source')

    def databases(self,source,catalog='',q='',limit=50,cursor=None):
        if source=='contoso':
            from app.services.contoso_sample_service import SAMPLE_DIR
            names=['contoso_demo']
            if (SAMPLE_DIR/'contoso_official.sqlite3').is_file():names.append('contoso_official')
            return self._paginate(names,q,limit,cursor)
        if source=='athena':
            if catalog and catalog!=self.s.athena_catalog: raise ValueError('Only configured Glue catalog supported in this deployment')
            if not self.s.is_aws: raise ValueError('APP_MODE=aws required for Athena')
            return self._athena_dbs(q,limit,cursor)
        if source=='postgres':
            # SQLAlchemy connection is scoped to one database; changing databases requires another connection.
            engine=self._engine(source)
            try: name=engine.url.database
            finally: engine.dispose()
            return self._paginate([name] if name else [],q,limit,cursor)
        if source in {'snowflake','databricks'}: return self._paginate([catalog] if catalog else [],q,limit,cursor)
        raise ValueError('Unsupported data source')

    def schemas(self,source,catalog='',database='',q='',limit=50,cursor=None):
        if source in {'contoso','athena'}:
            return self._paginate(['public'] if source=='contoso' else [database] if database else [],q,limit,cursor)
        if source=='postgres':
            from sqlalchemy import inspect
            engine=self._engine(source)
            try: schemas=[s for s in inspect(engine).get_schema_names() if s not in ('pg_catalog','information_schema') and not s.startswith('pg_')]
            finally: engine.dispose()
            return self._paginate(sorted(schemas),q,limit,cursor)
        if source=='snowflake':
            db=safe_identifier(database or catalog)
            return self._show(source,f'SHOW SCHEMAS IN DATABASE "{db}"',q,limit,cursor,('name','schema_name'),exclude={'INFORMATION_SCHEMA'})
        if source=='databricks':
            cat=safe_identifier(catalog or database)
            return self._show(source,f'SHOW SCHEMAS IN `{cat}`',q,limit,cursor,('databaseName','namespace','schemaName'))
        raise ValueError('Unsupported data source')

    def tables(self,source,catalog='',database='',schema='',q='',limit=50,cursor=None):
        if source=='contoso':
            from app.services.contoso_sample_service import ContosoSampleService
            return self._paginate(ContosoSampleService().set_dataset(database or 'contoso_demo').table_names(),q,limit,cursor)
        if source=='athena':
            if catalog and catalog!=self.s.athena_catalog: raise ValueError('Unsupported Glue catalog')
            return self._athena_tables(safe_identifier(database),q,limit,cursor)
        if source=='postgres':
            from sqlalchemy import inspect
            engine=self._engine(source)
            try:
                ins=inspect(engine); tables=ins.get_table_names(schema=safe_identifier(schema)) + ins.get_view_names(schema=schema)
            finally: engine.dispose()
            return self._paginate(sorted(set(tables)),q,limit,cursor)
        if source=='snowflake':
            db=safe_identifier(database or catalog); sch=safe_identifier(schema)
            return self._show(source,f'SHOW TABLES IN SCHEMA "{db}"."{sch}"',q,limit,cursor,('name','table_name'))
        if source=='databricks':
            cat=safe_identifier(catalog or database); sch=safe_identifier(schema)
            return self._show(source,f'SHOW TABLES IN `{cat}`.`{sch}`',q,limit,cursor,('tableName','table_name'))
        raise ValueError('Unsupported data source')

    def table_details(self,source,catalog='',database='',schema='',table=''):
        safe_identifier(table)
        if source=='contoso':
            from app.services.contoso_sample_service import ContosoSampleService
            return ContosoSampleService().table_details(table,database or 'contoso_demo')
        if source=='athena':
            db=safe_identifier(database)
            cols=AwsAdapter().get_columns(db,table)
            return {'source_id':source,'catalog':catalog or self.s.athena_catalog,'database':db,'schema':db,'table':table,'columns':cols,'sample_rows_used':False}
        from sqlalchemy import inspect
        engine=self._engine(source)
        try:
            insp=inspect(engine)
            physical_schema=safe_identifier(schema)
            if source=='snowflake': physical_schema=f'{safe_identifier(database or catalog)}.{physical_schema}'
            if source=='databricks': physical_schema=f'{safe_identifier(catalog or database)}.{physical_schema}'
            cols=insp.get_columns(table,schema=physical_schema)
            try: pk=set((insp.get_pk_constraint(table,schema=physical_schema) or {}).get('constrained_columns') or [])
            except Exception: pk=set()
            mapped=[{'name':c['name'],'type':str(c.get('type','string')),'nullable':c.get('nullable',True),'primary_key':c['name'] in pk,'comment':c.get('comment') or ''} for c in cols]
            foreign_keys=insp.get_foreign_keys(table,schema=physical_schema) or []
            return {'source_id':source,'catalog':catalog,'database':database or catalog,'schema':schema,'table':table,'columns':mapped,'foreign_keys':foreign_keys,'sample_rows_used':False}
        finally: engine.dispose()

    def selected_discovery(self,scope):
        source=scope['source_id']; selection=scope['tables']
        if not selection: raise ValueError('Select at least one table')
        # A scope contains explicitly selected tables, never an entire unbounded database.
        found=[]
        for obj in selection:
            meta=self.table_details(source,obj.get('catalog',''),obj.get('database',''),obj.get('schema',''),obj['table'])
            # In legacy 7.0 semantic repository, database is the physical namespace.
            # Ambiguous schemas across databases are rejected until Phase 2's canonical asset IDs.
            meta['database']=obj.get('database') or obj.get('schema') or 'contoso_demo'
            meta['source_id']=source
            found.append(meta)
        pairs=[(x['database'],x['table']) for x in found]
        if len(set(pairs))!=len(pairs): raise ValueError('Scope contains conflicting database.table names (cross-schema collision)')
        return {'source_id':source,'objects':found,'count':len(found),'scope':[f"{o['database']}.{o['table']}" for o in found],'sample_rows_used':False}

    def _show(self,source,query,q,limit,cursor,keys,exclude=None):
        from sqlalchemy import text
        engine=self._engine(source)
        try:
            with engine.connect() as c:
                rows=c.execute(text(query)).mappings().all()
            names=[]
            for row in rows:
                lower={str(k).lower():v for k,v in row.items()}
                name=next((lower.get(k.lower()) for k in keys if lower.get(k.lower())),None)
                if name and str(name).upper() not in (exclude or set()): names.append(str(name))
            return self._paginate(sorted(set(names)),q,limit,cursor)
        finally: engine.dispose()

    def _athena_dbs(self,q,limit,cursor):
        # True Glue continuation token, not unbounded list_databases().
        args={'MaxResults':min(max(int(limit),1),100)}; tok=_decode(cursor).get('token')
        if tok: args['NextToken']=tok
        matched=[]; nxt=None
        for _ in range(30):
            args['MaxResults']=min(100,max(1,int(limit)-len(matched)))
            resp=AwsAdapter().glue.get_databases(**args)
            matched += [d['Name'] for d in resp.get('DatabaseList',[]) if (not q or q.lower() in d['Name'].lower()) and (not self.s.db_prefix or d['Name'].startswith(self.s.db_prefix))]
            nxt=resp.get('NextToken')
            if len(matched)>=limit or not nxt: break
            args['NextToken']=nxt
        return {'items':[{'name':x} for x in matched[:limit]],'next_cursor':_encode({'token':nxt}) if nxt else None,'returned':min(len(matched),limit),'total':None}

    def _athena_tables(self,database,q,limit,cursor):
        args={'DatabaseName':database,'MaxResults':min(max(int(limit),1),100)}; tok=_decode(cursor).get('token')
        if tok:args['NextToken']=tok
        matched=[];nxt=None
        for _ in range(30):
            args['MaxResults']=min(100,max(1,int(limit)-len(matched)))
            resp=AwsAdapter().glue.get_tables(**args)
            matched += [{'name':t['Name'],'type':t.get('TableType','TABLE'),'column_count':len((t.get('StorageDescriptor') or {}).get('Columns',[]))} for t in resp.get('TableList',[]) if not q or q.lower() in t['Name'].lower()]
            nxt=resp.get('NextToken')
            if len(matched)>=limit or not nxt:break
            args['NextToken']=nxt
        return {'items':matched[:limit],'next_cursor':_encode({'token':nxt}) if nxt else None,'returned':min(len(matched),limit),'total':None}
