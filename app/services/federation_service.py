"""Bounded, transient cross-connector snapshots; rows never enter LLM prompts."""
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
import json
import re
import threading
import time
from app.config import get_settings


def quote(name):
    if not isinstance(name,str) or not name or '\x00' in name:
        raise ValueError('Invalid federated identifier')
    return '"'+name.replace('"','""')+'"'


class FederationService:
    def __init__(self,p2):
        self.p2=p2;self.s=get_settings()

    @staticmethod
    def table_name(asset):
        ident=asset['asset_id'].split(':')[-1]
        if not re.fullmatch(r'[a-f0-9]{24}',ident):raise ValueError('Invalid scoped asset identity')
        return 'f_'+ident

    @staticmethod
    def required(assets):
        return len({(a['source_id'],a['database']) for a in assets})>1

    @staticmethod
    def relationship_sql(source,target,source_keys,target_keys):
        sc=', '.join(quote(c)+f' AS k{i}' for i,c in enumerate(source_keys))
        tc=', '.join(quote(c)+f' AS k{i}' for i,c in enumerate(target_keys))
        sg=', '.join(quote(c) for c in source_keys);tg=', '.join(quote(c) for c in target_keys)
        sn=' AND '.join(quote(c)+' IS NOT NULL' for c in source_keys)
        tn=' AND '.join(quote(c)+' IS NOT NULL' for c in target_keys)
        on=' AND '.join(f's.k{i}=t.k{i}' for i in range(len(source_keys)))
        return (f'WITH src AS (SELECT {sc}, COUNT(*) AS n FROM {source} WHERE {sn} GROUP BY {sg}), '
            f'tgt AS (SELECT {tc}, COUNT(*) AS n FROM {target} WHERE {tn} GROUP BY {tg}) '
            'SELECT (SELECT COUNT(*) FROM src) AS source_distinct, '
            '(SELECT COALESCE(SUM(n),0) FROM src) AS source_non_null_rows, '
            '(SELECT COUNT(*) FROM tgt) AS target_distinct, '
            '(SELECT COALESCE(SUM(n),0) FROM tgt) AS target_non_null_rows, '
            '(SELECT COALESCE(SUM(n-1),0) FROM tgt) AS target_duplicate_rows, '
            f'(SELECT COUNT(*) FROM src s JOIN tgt t ON {on}) AS matched_distinct, '
            f'(SELECT COALESCE(SUM(s.n),0) FROM src s JOIN tgt t ON {on}) AS matched_rows')

    @staticmethod
    def dtype(typ):
        typ=str(typ).lower()
        if 'bool' in typ:return 'BOOLEAN'
        if any(v in typ for v in ('int','bigint')):return 'BIGINT'
        if any(v in typ for v in ('decimal','numeric','number')):
            match=re.search(r'\((\d+)(?:\s*,\s*(\d+))?\)',typ)
            p=min(int(match[1]),38) if match else 38;s=int(match[2] or 0) if match else 10
            if s>p:raise ValueError('Unsupported numeric precision in federation')
            return f'DECIMAL({p},{s})'
        if any(v in typ for v in ('real','float','double')):return 'DOUBLE'
        if 'timestamp' in typ or 'datetime' in typ:return 'TIMESTAMPTZ' if 'zone' in typ or 'tz' in typ else 'TIMESTAMP'
        if typ=='date':return 'DATE'
        if typ=='time':return 'TIME'
        if any(v in typ for v in ('char','text','string','uuid')):return 'VARCHAR'
        raise ValueError('Unsupported physical type in federation: '+typ)

    @staticmethod
    def value(value,typ):
        if value is None:return None
        if typ=='VARCHAR':return str(value)
        if typ=='BOOLEAN':
            if isinstance(value,bool):return value
            if str(value).lower() in {'true','1'}:return True
            if str(value).lower() in {'false','0'}:return False
            raise ValueError('Invalid boolean from a connector')
        if typ=='BIGINT':
            number=Decimal(str(value))
            if not number.is_finite() or number!=number.to_integral_value():raise ValueError('Lossy integer conversion refused')
            return int(number)
        if typ.startswith('DECIMAL'):return Decimal(str(value))
        if typ=='DOUBLE':return float(value)
        return value

    @contextmanager
    def snapshot(self,workspace,assets,projection=None):
        import duckdb
        if not 1<=len(assets)<=16 or len({a['asset_id'] for a in assets})!=len(assets):
            raise ValueError('Federation requires 1–16 distinct scoped datasets')
        settings=self.s
        if not (1<=settings.federation_max_rows_per_asset<=1000000 and
                1<=settings.federation_max_total_rows<=4000000 and
                1024<=settings.federation_max_payload_bytes<=536870912):
            raise ValueError('Invalid federation resource limits')
        con=duckdb.connect(':memory:',config={'memory_limit':'256MB','threads':'2',
            'temp_directory':'','autoinstall_known_extensions':'false','autoload_known_extensions':'false'})
        con.execute('SET enable_external_access=false')
        evidence=[];total_rows=0;payload=0
        try:
            for a in assets:
                # Re-resolve every identity through the workspace allowlist.
                actual=self.p2.asset(workspace,a['asset_id'])
                if actual!=a:raise ValueError('Federation asset changed before execution')
                meta=self.p2.metadata(workspace,a['asset_id'])
                wanted=set((projection or {}).get(a['asset_id'],[c['name'] for c in meta['columns']]))
                columns=[c for c in meta['columns'] if c['name'] in wanted]
                if not columns or len(columns)!=len(wanted):raise ValueError('Federation projection is outside scoped metadata')
                physical=self.p2._table_sql(a)
                count,_=self.p2._aggregate(a,'SELECT COUNT(*) AS n FROM '+physical)
                n=int(count['n']);cap=settings.federation_max_rows_per_asset
                if n>cap or total_rows+n>settings.federation_max_total_rows:
                    raise ValueError('FEDERATION_LIMIT_EXCEEDED: Narrow the selected datasets or use a warehouse federation layer')
                q=(lambda c:'`'+c.replace('`','``')+'`') if a['source_id']=='databricks' else quote
                sql='SELECT '+', '.join(q(c['name']) for c in columns)+' FROM '+physical+f' LIMIT {cap+1}'
                result=self.p2.sources.execute(a['source_id'],sql,a['database'],row_limit=cap+1,
                    payload_limit=settings.federation_max_payload_bytes-payload)
                rows=result['rows']
                if len(rows)!=n or result.get('truncated') or len(rows)>cap:
                    raise ValueError('FEDERATION_INCOMPLETE_SNAPSHOT: Source changed or returned incomplete data; retry')
                total_rows+=n;types=[self.dtype(c['type']) for c in columns]
                table=quote(self.table_name(a))
                con.execute('CREATE TABLE '+table+' ('+', '.join(quote(c['name'])+' '+typ for c,typ in zip(columns,types))+')')
                batch=[]
                for row in rows:
                    payload+=len(json.dumps(row,default=str,ensure_ascii=False).encode())
                    if payload>settings.federation_max_payload_bytes:raise ValueError('FEDERATION_LIMIT_EXCEEDED: Snapshot payload exceeds the memory budget')
                    batch.append(tuple(self.value(row[c['name']],typ) for c,typ in zip(columns,types)))
                    if len(batch)>=1000:
                        con.executemany('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in columns)+')',batch);batch=[]
                if batch:con.executemany('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in columns)+')',batch)
                evidence.append({'asset_id':a['asset_id'],'source_id':a['source_id'],'rows_loaded':n,
                    'source_query_id':result.get('query_id'),'columns':[c['name'] for c in columns],
                    'fingerprint':meta['fingerprint']})
            yield con,{'execution_engine':'duckdb','source_ids':sorted({a['source_id'] for a in assets}),
                'snapshots':evidence,'total_rows_loaded':total_rows,'payload_bytes':payload,
                'atomic_across_sources':False,'source_rows_sent_to_llm':False}
        finally:con.close()

    def execute(self,workspace,assets,sql,projection=None,relationships=None,grains=None):
        from app.services.sql_safety import validate_read_only_sql
        ok,message=validate_read_only_sql(sql)
        if not ok:raise ValueError(message)
        started=time.monotonic()
        with self.snapshot(workspace,assets,projection) as (con,evidence):
            by_id={a['asset_id']:a for a in assets}
            for asset_id,keys in grains or []:
                table=quote(self.table_name(by_id[asset_id]));group=', '.join(quote(k) for k in keys)
                nulls=' OR '.join(quote(k)+' IS NULL' for k in keys)
                if con.execute(f'SELECT COUNT(*) FROM {table} WHERE {nulls}').fetchone()[0] or con.execute(f'SELECT COUNT(*) FROM (SELECT {group} FROM {table} GROUP BY {group} HAVING COUNT(*)>1)').fetchone()[0]:
                    raise ValueError('Measure grain changed in the federated snapshot; query refused')
            for rel in relationships or []:
                source=quote(self.table_name(by_id[rel['from_asset']]));target=quote(self.table_name(by_id[rel['to_asset']]))
                cur=con.execute(self.relationship_sql(source,target,rel['from_columns'],rel['to_columns']))
                measured=dict(zip([c[0] for c in cur.description],cur.fetchone()))
                if measured['target_duplicate_rows']:
                    raise ValueError('Relationship target uniqueness changed in the federated snapshot; query refused')
                if not measured['source_distinct'] or not measured['source_non_null_rows'] or measured['matched_distinct']/measured['source_distinct']<.90 or measured['matched_rows']/measured['source_non_null_rows']<.90:
                    raise ValueError('Relationship coverage changed in the federated snapshot; query refused')
            timer=threading.Timer(self.s.query_timeout_seconds,con.interrupt);timer.daemon=True;timer.start()
            try:
                result=con.execute(sql);names=[d[0] for d in result.description]
                rows=[dict(zip(names,row)) for row in result.fetchmany(self.s.max_result_rows)]
            finally:timer.cancel()
        return {'query_id':'federated-snapshot','columns':names,'rows':rows,'row_count':len(rows),
            'execution_ms':round((time.monotonic()-started)*1000),'bytes_scanned':None,'federation':evidence}
