"""Phase 5 operational control plane: explicit scoped federation, metadata search,
connector conformance samples and durable allowlisted worker jobs.

Safety boundaries: never expose row samples through federation; never execute SQL
supplied by a job request. Multi-machine worker coordination is NOT offered with
SQLite; the queue is multi-process on a shared local host only.
"""
from __future__ import annotations
import hashlib, json, os, re, sqlite3, time
from uuid import uuid4
from datetime import datetime, timezone
from app.repositories.control_repository import ControlRepository
from app.services.phase2_service import Phase2Service
from app.services.phase3_service import Phase3Service
from app.services.phase4_service import Phase4Service
from app.services.data_source_service import DataSourceService
from app.services.contoso_sample_service import ContosoSampleService
from app.services.phase5_jobs import JobStore

def now():return datetime.now(timezone.utc).isoformat()
def checksum(value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()
def identifier(s):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{1,63}',str(s)):
        raise ValueError('Identifier must start with a letter and use 2–64 letters/numbers/_/-')
    return s

class Phase5Service:
    def __init__(self,job_store=None):
        self.repo=ControlRepository();self.p2=Phase2Service();self.p3=Phase3Service()
        self.p4=Phase4Service();self.sources=DataSourceService()
        if job_store is not None:self.jobs=job_store
        elif os.getenv('JOB_QUEUE_BACKEND',os.getenv('PHASE5_QUEUE_BACKEND','dynamodb' if self.repo.s.is_production else 'sqlite')).lower()=='dynamodb':
            from app.services.phase5_dynamo_jobs import DynamoJobStore
            self.jobs=DynamoJobStore()
        else:self.jobs=JobStore()
    def _kind(self,kind,workspace):
        return [x for x in self.repo.list(kind,1000) if x.get('workspace_id')==workspace]
    def _domain(self,workspace,domain_id):
        d=self.repo.get('P5_DOMAIN',workspace+'::'+domain_id)
        if not d or d['workspace_id']!=workspace:raise KeyError('Domain not found in workspace')
        return d
    def _scope(self,workspace):return self.p2.scope(workspace)
    def overview(self,w):
        self._scope(w)
        domains=self._kind('P5_DOMAIN',w)
        return {'workspace_id':w,'domains':len(domains),'published_domains':sum(d['status']=='published' for d in domains),
                'job_status':self.jobs.summary(w),'connectors':self.sources.sources(),
                'worker_backend':getattr(self.jobs,'backend','sqlite_single_host'),'cross_machine_worker_leasing':getattr(self.jobs,'backend','')=='dynamodb_multi_host',
                'federation_policy':'explicit_publish_and_target_workspace_grant',
                'warning':'AWS live connector equivalence and multi-node Windows EC2 deployment are not certified.'}
    def domains(self,w):
        self._scope(w)
        return self._kind('P5_DOMAIN',w)
    def create_domain(self,w,body,actor):
        self._scope(w)
        did=identifier(body.get('domain_id',''))
        if self.repo.get('P5_DOMAIN',w+'::'+did):raise ValueError('Domain already exists')
        label=str(body.get('label','')).strip(); description=str(body.get('description','')).strip()
        if not 2<=len(label)<=120 or len(description)>500:raise ValueError('Invalid label or description')
        release_id=str(body.get('release_id','')).strip()
        if not release_id:raise ValueError('Certified release required for federation')
        _,active,blocked=self.p4._eligible(w,release_id)
        if blocked or not active:raise ValueError('Cannot federate an empty or stale certified release')
        d={'workspace_id':w,'domain_id':did,'label':label,'description':description,
           'owner':actor,'release_id':release_id,'status':'draft','version':1,
           'granted_workspaces':[],'published_manifest':None,'created_at':now()}
        return self.repo.put('P5_DOMAIN',w+'::'+did,d)
    def publish_domain(self,w,domain_id,actor,expected_version):
        d=self._domain(w,domain_id)
        if expected_version!=d['version']:raise ValueError('Domain version conflict')
        if d['status']=='revoked':raise ValueError('Revoked domain cannot be republished; create a new domain')
        release,active,blocked=self.p4._eligible(w,d['release_id'])
        if blocked or not active:raise ValueError('Certification or evidence is no longer current')
        # Safe manifest: NEVER publish physical bindings, columns, samples or provenance.
        objects=[{'object_id':o['object_id'],'kind':o['kind'],'label':o['label'],
           'description':(o.get('description') or '')[:220]} for o in active]
        manifest={'objects':objects,'count':len(objects),'release_digest':release['content_digest']}
        d={**d,'version':d['version']+1,'status':'published','published_at':now(),
           'published_by':actor,'published_manifest':manifest,'manifest_digest':checksum(manifest)}
        return self.repo.put('P5_DOMAIN',w+'::'+domain_id,d)
    def grant(self,w,domain_id,target_workspace,actor,expected_version,allow=True):
        d=self._domain(w,domain_id)
        if d['version']!=expected_version:raise ValueError('Domain version conflict')
        if d['status']!='published':raise ValueError('Publish the domain before granting')
        identifier(target_workspace)
        if target_workspace==w:raise ValueError('Own workspace does not need a grant')
        self._scope(target_workspace)   # Cannot grant a fictional namespace.
        targets=set(d.get('granted_workspaces') or [])
        if allow:targets.add(target_workspace)
        else:targets.discard(target_workspace)
        return self.repo.put('P5_DOMAIN',w+'::'+domain_id,{**d,'version':d['version']+1,
            'granted_workspaces':sorted(targets),'last_grant_actor':actor,'last_grant_at':now()})
    def revoke(self,w,domain_id,actor,expected_version):
        d=self._domain(w,domain_id)
        if d['version']!=expected_version:raise ValueError('Domain version conflict')
        return self.repo.put('P5_DOMAIN',w+'::'+domain_id,{**d,'status':'revoked',
            'version':d['version']+1,'revoked_at':now(),'revoked_by':actor})
    def federation(self,w):
        self._scope(w);out=[]
        for d in self.repo.list('P5_DOMAIN',1000):
            if d.get('status')!='published':continue
            if w!=d['workspace_id'] and w not in (d.get('granted_workspaces') or []):continue
            # Fail closed even if published manifest itself did not change.
            try:
                release,active,blocked=self.p4._eligible(d['workspace_id'],d['release_id'])
                if blocked or not active or d['published_manifest']['release_digest']!=release['content_digest']:
                    continue
                permitted={o['object_id'] for o in active}
                if permitted!={o['object_id'] for o in d['published_manifest']['objects']}:
                    continue
                if checksum(d['published_manifest'])!=d.get('manifest_digest'):continue
            except (KeyError,ValueError,TypeError):continue
            out.append({'workspace_id':d['workspace_id'],'domain_id':d['domain_id'],
                'label':d['label'],'description':d['description'],
                'release_id':d['release_id'],'objects':d['published_manifest']['objects'],
                'count':d['published_manifest']['count'],'owned':w==d['workspace_id']})
        return out
    def search(self,w,query,limit=20,include_federated=True):
        self._scope(w)
        q=str(query).strip()
        if not 2<=len(q)<=160:raise ValueError('Search query must be 2–160 characters')
        terms=set(re.findall(r'[a-z0-9]+',q.lower()))
        if not terms:raise ValueError('Search requires letters or numbers')
        hits=[]
        for a in self.p2.assets(w):
            hits.append({'kind':'dataset','label':a.get('table') or a.get('asset_id'),
                'description':a.get('database',''),'id':a['asset_id'],'workspace_id':w,'source':'local'})
        for o in self.p3.objects(w):
            # Only certified objects; hide physical bindings from search.
            if o['status']=='certified' and not self.p4._fresh(w,o):
                hits.append({'kind':o['kind'],'label':o['label'],
                    'description':o.get('description','')[:220], 'id':o['object_id'],
                    'workspace_id':w,'source':'local'})
        if include_federated:
            for d in self.federation(w):
                if d['owned']:continue
                for o in d['objects']:
                    hits.append({'kind':o['kind'],'label':o['label'],
                       'description':o['description'],'id':o['object_id'],
                       'workspace_id':d['workspace_id'],'domain_id':d['domain_id'],'source':'federated'})
        matches=[]
        for h in hits:
            name=h['label'].lower(); desc=h['description'].lower()
            score=sum(5 if t in name else 1 if t in desc else 0 for t in terms)
            if score:matches.append({**h,'score':score})
        matches.sort(key=lambda x:(-x['score'],x['workspace_id'],x['label']))
        matches=matches[:min(max(limit,1),100)]
        facets={}
        for h in matches:facets[h['kind']]=facets.get(h['kind'],0)+1
        return {'workspace_id':w,'query':q,'results':matches,'facets':facets,'returned':len(matches),
                'index_mode':'permission_filtered_live_metadata','no_row_values':True}
    def snapshot_search(self,w):
        # Digests are operational diagnostics; actual queries still re-check permission.
        items=self.p2.assets(w)
        local=[o for o in self.p3.objects(w) if o['status']=='certified' and not self.p4._fresh(w,o)]
        row={'workspace_id':w,'generated_at':now(),'local_assets':len(items),
             'certified_objects':len(local),'federated_domains':len(self.federation(w)),
             'snapshot_digest':checksum([a['asset_id'] for a in items]+[o['object_id'] for o in local])}
        self.repo.put('P5_INDEX',w,row)
        return row
    def benchmark(self,w,source_id,schemas=None):
        sc=self._scope(w)
        if source_id not in sc.get('source_ids',[sc['source_id']]):
            raise ValueError('Connector benchmark must use the workspace selected source')
        src=next((x for x in self.sources.sources() if x['id']==source_id),None)
        if not src or not src['configured']:raise ValueError('Source not configured')
        t0=time.perf_counter()
        if source_id=='contoso':
            sample=ContosoSampleService()
            rows=[]
            for t in sc['tables'][:20]:
                if t.get('source_id',sc['source_id'])!=source_id:continue
                table=t['table'];db=t['database']
                detail=sample.table_details(table,db)
                # Compare two independently executed bounded aggregate readers.
                sql=f'SELECT COUNT(*) AS row_count FROM "{table}"'
                actual=self.sources.execute('contoso',sql,db)
                with sample.set_dataset(db)._db() as con:
                    expected=con.execute(sql).fetchone()[0]
                n=int(actual['rows'][0]['row_count'])
                rows.append({'table':table,'source_count':n,'reference_count':expected,
                             'count_equal':n==expected,'column_count':len(detail['columns'])})
            status='passed' if rows and all(x['count_equal'] for x in rows) else 'failed'
            scope='offline_contoso_aggregate_and_schema'
        else:
            # Explicit schema list: avoid broad warehouse scans and arbitrary SQL.
            allowed={x['schema'] for x in sc['tables'] if x.get('source_id',sc['source_id'])==source_id}
            if not schemas or not set(schemas).issubset(allowed):
                raise ValueError('Connector benchmark needs explicit selected schema allowlist')
            discovered=self.sources.discover(source_id,schemas)
            selected={(x['schema'],x['table']) for x in sc['tables'] if x.get('source_id',sc['source_id'])==source_id}
            rows=[{'table':d['table'],'schema':d['schema'],
                   'column_count':len(d['columns']),'in_selected_scope':(d['schema'],d['table']) in selected}
                  for d in discovered['objects'] if (d['schema'],d['table']) in selected][:100]
            status='metadata_only';scope='external_schema_conformance_no_cross_engine_parity'
        result={'workspace_id':w,'source_id':source_id,'status':status,'scope':scope,
            'tables':rows,'table_count':len(rows),'elapsed_ms':round((time.perf_counter()-t0)*1000,2),
            'verified_at':now(),'cross_connector_equivalence_verified':False}
        self.repo.put('P5_BENCH',w+'::'+uuid4().hex,result)
        return result
    def benchmarks(self,w):
        self._scope(w);return self._kind('P5_BENCH',w)
    def submit(self,w,body,actor):
        self._scope(w)
        task=body['task'];p=body.get('payload') or {}
        if task=='profile':
            if p.get('tier') not in {'metadata','standard','deep'}:raise ValueError('Invalid profile tier')
            self.p2.asset(w,str(p.get('asset_id','')))
            if not 50<=int(p.get('max_rows',200))<=10000:raise ValueError('Profile row cap must be 50–10000')
            p={'tier':p['tier'],'asset_id':p['asset_id'],'max_rows':int(p.get('max_rows',200))}
        elif task=='golden_suite':
            self.p4.release(w,str(p.get('release_id','')))
            p={'release_id':p['release_id'],'mutations':bool(p.get('mutations',True))}
        elif task=='connector_benchmark':
            selected=self._scope(w)
            if p.get('source_id') not in selected.get('source_ids',[selected['source_id']]):raise ValueError('Connector outside selected scope')
            schemas=p.get('schemas') or []
            if not isinstance(schemas,list) or len(schemas)>10 or not all(isinstance(x,str) for x in schemas):raise ValueError('Invalid schemas')
            p={'source_id':p['source_id'],'schemas':schemas}
        elif task=='search_snapshot':p={}
        else:raise ValueError('Job type not allowlisted')
        return self.jobs.enqueue(w,task,p,actor,body.get('idempotency_key'),
                      int(body.get('priority',0)),int(body.get('max_attempts',3)))
    def perform(self,job):
        w=job['workspace'];p=job['payload'];task=job['task']
        if task=='profile':return self.p2.profile(w,p['asset_id'],p['tier'],'p5-worker',p['max_rows'])
        if task=='golden_suite':return self.p4.evaluation(w,p['release_id'],'p5-worker',p['mutations'])
        if task=='connector_benchmark':return self.benchmark(w,p['source_id'],p.get('schemas'))
        if task=='search_snapshot':return self.snapshot_search(w)
        raise ValueError('Unknown or blocked job type')
