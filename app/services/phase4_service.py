"""Release-pinned evidence, documentation branches and the shared LLM query facade."""
from __future__ import annotations
from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from uuid import uuid4
from app.repositories.control_repository import ControlRepository
from app.services.phase3_service import Phase3Service
from app.services.phase2_service import Phase2Service

STOP={'what','is','the','a','an','of','for','in','to','me','show','give','by','please','how','many','count','total','sum','average','avg','minimum','maximum','min','max','number','value','amount','records','rows'}
OPERATIONS={'count','sum','avg','min','max'}

def utc(): return datetime.now(timezone.utc).isoformat()
def digest(o):return hashlib.sha256(json.dumps(o,sort_keys=True,default=str).encode()).hexdigest()
def words(s):return set(re.findall(r'[a-z0-9]+',str(s).lower()))-STOP

def slug(s):
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}',str(s)):
        raise ValueError('Invalid release or branch identifier')
    return s

class Phase4Service:
    def __init__(self):
        self.repo=ControlRepository();self.p3=Phase3Service();self.p2=Phase2Service()

    def _list(self,kind,w):return [r for r in self.repo.list(kind,1000) if r.get('workspace_id')==w]
    def _get(self,kind,w,ident):
        r=self.repo.get(kind,w+'::'+ident)
        if not r or r.get('workspace_id')!=w:raise KeyError('Resource not found in workspace')
        return r
    def _put(self,kind,w,ident,data):return self.repo.put(kind,w+'::'+ident,data)
    def audit(self,w,actor,action,detail):
        self._put('P4_AUDIT',w,uuid4().hex,{'workspace_id':w,'actor':actor,'action':action,'detail':detail,'timestamp':utc()})

    def releases(self,w):
        self.p2.scope(w)
        return [{k:v for k,v in r.items() if k!='objects'} for r in self._list('P4_RELEASE',w)]

    def _source(self,w,version):
        source=self._get('P3_RELEASE',w,version)
        if not source.get('objects') or source.get('target')!='phase3_review_snapshot_only':
            raise ValueError('Only an evidence-certified Phase 3 release may be promoted')
        if digest([{k:v for k,v in o.items() if k not in {'review_history','updated_at'}} for o in source['objects']])!=source['content_digest']:
            raise ValueError('Phase 3 release digest mismatch')
        return source

    def promote(self,w,version,actor):
        source=self._source(w,version)
        rid='p3-'+version
        if self.repo.get('P4_RELEASE',w+'::'+rid):raise ValueError('Already promoted')
        release={'workspace_id':w,'release_id':rid,'source_version':version,'source_digest':source['content_digest'],
             'objects':deepcopy(source['objects']),'content_digest':digest(source['objects']),
             'published_at':utc(),'published_by':actor,'branch_id':None,'mode':'governed_preview'}
        result=self._put('P4_RELEASE',w,rid,release)
        self.audit(w,actor,'promote_release',{'release_id':rid})
        return {k:v for k,v in result.items() if k!='objects'}

    def release(self,w,release_id):
        self.p2.scope(w)
        return self._get('P4_RELEASE',w,release_id)

    def _fresh(self,w,obj):
        try:
            current=self.p3.object(w,obj['object_id'])
            if current['status']!='certified' or current['version']!=obj['version']:
                return 'CERTIFICATION_REVOKED_OR_VERSION_CHANGED'
            if any(d['severity']=='error' for d in self.p3.diagnostics(w,current)):
                return 'EVIDENCE_EXPIRED'
            if current['kind']!=obj['kind'] or current.get('binding')!=obj.get('binding') or current.get('depends_on')!=obj.get('depends_on') or current.get('semantics')!=obj.get('semantics'):
                return 'SEMANTICS_CHANGED'
            return None
        except (KeyError,ValueError):return 'MISSING_LIVE_SEMANTICS'

    def _eligible(self,w,release_id):
        r=self.release(w,release_id)
        source=self._source(w,r['source_version'])
        if source['content_digest']!=r['source_digest']:
            raise ValueError('Pinned source release has changed')
        if r['content_digest']!=digest(r['objects']):
            raise ValueError('Pinned release content digest mismatch')
        active=[];blocked=[]
        for obj in r['objects']:
            reason=self._fresh(w,obj)
            if reason:blocked.append({'object_id':obj['object_id'],'code':reason})
            else:active.append(obj)
        return r,active,blocked

    def overview(self,w,release_id=''):
        self.p2.scope(w)
        releases=self.releases(w)
        if not release_id and releases:release_id=releases[0]['release_id']
        if not release_id:return {'workspace_id':w,'releases':0,'eligible':0,'blocked':[], 'active_release':None,
            'notice':'Publish a certified Phase 3 snapshot and promote it into Phase 4.'}
        _,eligible,blocked=self._eligible(w,release_id)
        return {'workspace_id':w,'releases':len(releases),'active_release':release_id,
                'eligible':len(eligible),'blocked':blocked,'governance':'fresh_certified_read_only'}

    def branch(self,w,release_id,branch_id,actor):
        slug(branch_id);base,allowed,blocked=self._eligible(w,release_id)
        if blocked:raise ValueError('Branch baseline contains stale evidence')
        if self.repo.get('P4_BRANCH',w+'::'+branch_id):raise ValueError('Branch already exists')
        result=self._put('P4_BRANCH',w,branch_id,{'workspace_id':w,'branch_id':branch_id,'base_release_id':release_id,
            'base_digest':base['content_digest'],'patches':{},'version':1,'status':'draft','created_by':actor,'created_at':utc(),
            'reviewed_by':None,'review_note':''})
        self.audit(w,actor,'branch_created',{'branch_id':branch_id})
        return result

    def branches(self,w):self.p2.scope(w);return self._list('P4_BRANCH',w)
    def patch(self,w,branch_id,object_id,field,value,expected_version,actor):
        b=self._get('P4_BRANCH',w,branch_id)
        if b['status']!='draft' or b['version']!=expected_version:raise ValueError('Branch is not editable or version conflict')
        if field not in {'label','description'}:raise ValueError('Only label/description patches supported; changes to executable semantics require Phase 3 re-certification')
        if not isinstance(value,str) or not 2<=len(value.strip())<=500:raise ValueError('Label/description must be 2–500 characters')
        base=self.release(w,b['base_release_id'])
        if base['content_digest']!=b['base_digest']:raise ValueError('Branch baseline has changed')
        if object_id not in {x['object_id'] for x in base['objects']}:raise KeyError('Object not in pinned baseline')
        patches=deepcopy(b['patches']);patches.setdefault(object_id,{})[field]=value.strip()
        row=self._put('P4_BRANCH',w,branch_id,{**b,'patches':patches,'version':b['version']+1})
        self.audit(w,actor,'branch_patch',{'branch_id':branch_id,'object_id':object_id,'field':field})
        return row

    def compare(self,w,branch_id):
        b=self._get('P4_BRANCH',w,branch_id);base=self.release(w,b['base_release_id'])
        return {'branch_id':branch_id,'base_release_id':b['base_release_id'],'version':b['version'],
           'status':b['status'],'changes':[{'object_id':oid,'changes':{field:{'before':next(o.get(field) for o in base['objects'] if o['object_id']==oid),'after':v}
                for field,v in patch.items()}} for oid,patch in b['patches'].items()]}

    def review_branch(self,w,branch_id,decision,note,expected_version,actor):
        b=self._get('P4_BRANCH',w,branch_id)
        if b['version']!=expected_version:raise ValueError('Branch version conflict')
        if b['status']!='draft':raise ValueError('Only draft branch may be reviewed')
        if decision not in {'approved','rejected'}:raise ValueError('Unsupported branch review decision')
        if len(note.strip())<5 or actor==b['created_by']:raise ValueError('Independent reviewer and explanation required')
        _,_,blocked=self._eligible(w,b['base_release_id'])
        if blocked:raise ValueError('Pinned baseline has stale evidence')
        result=self._put('P4_BRANCH',w,branch_id,{**b,'status':decision,'version':b['version']+1,
            'reviewed_by':actor,'review_note':note[:1000],'reviewed_at':utc()})
        self.audit(w,actor,'branch_review',{'branch_id':branch_id,'decision':decision})
        return result

    def publish_branch(self,w,branch_id,version,actor):
        slug(version);b=self._get('P4_BRANCH',w,branch_id)
        if b['status']!='approved' or not b['patches']:raise ValueError('Requires approved non-empty branch')
        if self.repo.get('P4_RELEASE',w+'::'+version):raise ValueError('Release version already exists')
        base,_,blocked=self._eligible(w,b['base_release_id'])
        if blocked or base['content_digest']!=b['base_digest']:raise ValueError('Pinned baseline stale')
        objects=deepcopy(base['objects'])
        for obj in objects:obj.update(b['patches'].get(obj['object_id'],{}))
        result=self._put('P4_RELEASE',w,version,{'workspace_id':w,'release_id':version,
            'source_version':base['source_version'],'source_digest':base['source_digest'],
            'objects':objects,'content_digest':digest(objects),'branch_id':branch_id,
            'published_at':utc(),'published_by':actor,'mode':'governed_preview'})
        self._put('P4_BRANCH',w,branch_id,{**b,'status':'published','version':b['version']+1})
        self.audit(w,actor,'branch_release',{'branch_id':branch_id,'release_id':version})
        return {k:v for k,v in result.items() if k!='objects'}

    def retrieval(self,w,release_id,question,limit=8):
        if not 2<=len(question.strip())<=500:raise ValueError('Question length must be 2–500')
        if limit<1 or limit>20:raise ValueError('limit must be 1–20')
        r,objs,blocked=self._eligible(w,release_id)
        q=words(question);hits=[]
        for o in objs:
            aid=o['binding'].get('asset_id');asset=self.p2.asset(w,aid) if aid else None
            terms=words(' '.join([o['label'],o.get('description',''),o['object_id'],asset['table'] if asset else '']))
            overlap=sorted(terms&q)
            if not overlap or len(overlap)/max(len(q),1)<0.65:continue
            current=self.p3.object(w,o['object_id'])
            ledger=[x for x in self.p3.evidence(w,o['object_id']) if x['object_version']==current['version']]
            hits.append({'object_id':o['object_id'],'label':o['label'],'kind':o['kind'],'asset_id':aid,
                 'domain':asset['database'] if asset else 'ontology', 'score':round(len(overlap)/max(len(q),1),3),
                 'matched_terms':overlap,'evidence_digest':ledger[0]['source_digest'] if ledger else None,
                 'provenance':{'release_id':release_id,'object_version':o['version'],'source_digest':r['source_digest']}})
        hits.sort(key=lambda x:(-x['score'],x['label']))
        domains=defaultdict(list)
        for hit in hits[:limit]:domains[hit['domain']].append(hit)
        return {'workspace_id':w,'release_id':release_id,'question':question,
           'domains':[{'name':name,'objects':results} for name,results in domains.items()],
           'hits':hits[:limit],'blocked_objects':blocked,'algorithm':'deterministic_hierarchical_lexical',
           'llm_used':False,'notes':'Domain → certified ontology object → measured evidence; no untrusted sources.'}

    def plan(self,w,release_id,question,object_id=None):
        if object_id:raise ValueError('Object pinning was replaced by approved metric definitions')
        from app.services.unified_ask_service import UnifiedAskService
        return UnifiedAskService().ask(w,release_id,question,False)

    def ask(self,w,release_id,question,object_id=None,execute=False):
        if object_id:raise ValueError('Object pinning was replaced by approved metric definitions')
        from app.services.unified_ask_service import UnifiedAskService
        return UnifiedAskService().ask(w,release_id,question,execute)

    def cases(self,w):
        from app.services.business_benchmark_service import BusinessBenchmarkService
        self.p2.scope(w)
        return BusinessBenchmarkService().cases(w)
    def save_case(self,w,data,actor):
        from app.services.business_benchmark_service import BusinessBenchmarkService
        body={**data,'expected':{'allow':'answer','reject':'refuse'}.get(data.get('expected'),data.get('expected'))}
        if body['expected']=='answer' and not body.get('reference_sql'):
            raise ValueError('BENCHMARK_MIGRATION_REQUIRED: Supply independently reviewed reference_sql and reference_asset_id; object matching is not a business-result benchmark')
        return BusinessBenchmarkService().save(w,body,actor)

    def evaluation(self,w,release_id,actor,mutations=True):
        from app.services.business_benchmark_service import BusinessBenchmarkService
        # Paraphrases and negative cases are independently authored cases, not generated
        # mutations assumed equivalent without a business reference.
        out=BusinessBenchmarkService().run(w,release_id)
        return {**out,'passed':out['counts']['passed'],'score':round(100*out['counts']['passed']/out['total'],2)}

    def evaluations(self,w):
        self.p2.scope(w)
        return self._list('BUSINESS_RUN',w)

    def impact(self,w,release_id,object_id,max_depth=5):
        if max_depth<1 or max_depth>8:raise ValueError('Impact depth must be 1–8')
        r=self.release(w,release_id);objs={x['object_id']:x for x in r['objects']}
        if object_id not in objs:raise KeyError('Object absent from release')
        reverse=defaultdict(list)
        for o in objs.values():
            for dep in o.get('depends_on',[]):reverse[dep].append(o['object_id'])
        queue=deque([(object_id,0)]);seen={object_id};nodes=[];edges=[]
        while queue:
            oid,depth=queue.popleft();o=objs[oid];nodes.append({'id':oid,'label':o['label'],'kind':o['kind'],'depth':depth,
                'fresh':self._fresh(w,o) is None})
            if depth==max_depth:continue
            for child in sorted(reverse.get(oid,[])):
                edges.append({'source_id':oid,'target_id':child,'kind':'IMPACTS'})
                if child not in seen:seen.add(child);queue.append((child,depth+1))
        asset=objs[object_id]['binding'].get('asset_id')
        return {'workspace_id':w,'release_id':release_id,'focus':object_id,'nodes':nodes,'edges':edges,
                'physical_asset':asset,'affected_count':len(nodes)-1,'direction':'downstream','depth':max_depth}

    def bi(self,w,release_id,question,object_id=None,execute=False):
        return self.ask(w,release_id,question,object_id,execute)

    def agent_tools(self):
        return [{'name':'ontology.retrieve','description':'Read certified ontology concepts and citations; no SQL',
             'parameters':['workspace','release_id','question']},
            {'name':'ontology.plan','description':'Construct an evidence-checked aggregate query plan; no execution',
             'parameters':['workspace','release_id','question','object_id']},
            {'name':'ontology.ask','description':'Offline Contoso-certified aggregate answer; opt-in execute',
             'parameters':['workspace','release_id','question','object_id','execute']},
            {'name':'ontology.impact','description':'Dependency impact from pinned ontology release',
             'parameters':['workspace','release_id','object_id']}]
    def agent(self,w,release_id,tool,arguments):
        if not isinstance(arguments,dict):raise ValueError('Tool arguments must be an object')
        if tool=='ontology.retrieve':return self.retrieval(w,release_id,arguments['question'])
        if tool=='ontology.plan':return self.plan(w,release_id,arguments['question'],arguments.get('object_id'))
        if tool=='ontology.ask':return self.ask(w,release_id,arguments['question'],arguments.get('object_id'),arguments.get('execute') is True)
        if tool=='ontology.impact':return self.impact(w,release_id,arguments['object_id'])
        raise ValueError('Unknown or unapproved agent tool')
