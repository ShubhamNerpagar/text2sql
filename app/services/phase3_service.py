"""Phase 3 Ontology 2.0: scope-bound semantic proposals, provenance, review and diagnostics.

Does not silently enroll candidates in production SQL/Ask. Physical evidence is taken
from Phase 2; read-only graph/compile endpoints never run a warehouse query.
"""
from __future__ import annotations
import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4
from app.repositories.control_repository import ControlRepository
from app.services.phase2_service import Phase2Service
from app.services.business_semantics import validate_semantics, is_fresh

KINDS={'entity','event','measure','code_set','business_concept','rule'}
STATES={'draft','reviewed','certified','rejected','deprecated'}
TRANSITIONS={'draft':{'reviewed','rejected'},'reviewed':{'certified','draft','rejected'},
             'certified':{'deprecated','draft'},'rejected':{'draft'},'deprecated':{'draft'}}
MODES={'conceptual','logical','evidence','dependency'}
def stamp():return datetime.now(timezone.utc).isoformat()
def hashof(data):return hashlib.sha256(json.dumps(data,sort_keys=True,default=str).encode()).hexdigest()
def slug(s):return re.sub(r'[^a-z0-9_]+','_',str(s).strip().lower()).strip('_')[:64]

def error(code,message,severity='error',refs=None):return {'code':code,'message':message,'severity':severity,'evidence_refs':refs or []}

class Phase3Service:
    def __init__(self):
        self.repo=ControlRepository();self.p2=Phase2Service()

    def assets(self,workspace):return self.p2.assets(workspace)
    def _list(self,kind,workspace):
        return [r for r in self.repo.list(kind,1000) if r.get('workspace_id')==workspace]
    def _get(self,kind,workspace,key):
        x=self.repo.get(kind,workspace+'::'+key)
        if not x or x.get('workspace_id')!=workspace:raise KeyError(f'{kind} not found in workspace')
        return x
    def _put(self,kind,workspace,key,record):
        return self.repo.put(kind,workspace+'::'+key,record)
    def audit(self,workspace,actor,action,subject,detail=None):
        ident=uuid4().hex
        self._put('P3_AUDIT',workspace,ident,{'workspace_id':workspace,'event_id':ident,'at':stamp(),
            'actor':actor,'action':action,'subject':subject,'detail':detail or {}})

    def objects(self,workspace,kind=None):
        self.assets(workspace)
        if kind is not None and kind not in KINDS:raise ValueError('Unsupported ontology kind')
        rows=self._list('P3_OBJECT',workspace)
        return [r for r in rows if not kind or r['kind']==kind]
    def object(self,workspace,object_id):return self._get('P3_OBJECT',workspace,object_id)
    def evidence(self,workspace,object_id=None):
        self.assets(workspace)
        rows=self._list('P3_EVIDENCE',workspace)
        return [r for r in rows if not object_id or r['object_id']==object_id]

    def _binding(self,workspace,kind,binding):
        b=deepcopy(binding or {})
        aid=b.get('asset_id')
        physical=kind in {'entity','event','measure','code_set'}
        if physical and not aid:raise ValueError(f'{kind} requires an asset_id binding')
        if aid:
            a=self.p2.asset(workspace,aid)
            meta=self.p2.metadata(workspace,aid)
            available={c['name']:c for c in meta['columns']}
            columns=b.get('columns',[])
            if not isinstance(columns,list) or len(columns)>80 or len(columns)!=len(set(columns)):
                raise ValueError('Binding columns must be a unique list (up to 80)')
            if not columns and physical:raise ValueError('Physical ontology objects require at least one column')
            if any(not isinstance(c,str) or c not in available for c in columns):
                raise ValueError('Column binding must refer to selected physical schema columns')
            if kind=='event' and not any('date' in c.lower() or 'time' in c.lower() or
                any(t in str(available[c].get('type','')).lower() for t in ('date','timestamp','time')) for c in columns):
                raise ValueError('Event needs a time/date column')
            b={'asset_id':aid,'columns':columns,'schema_fingerprint':meta['fingerprint']}
        elif b:raise ValueError('Binding without asset_id is not permitted')
        return b

    @staticmethod
    def _synonyms(values):
        if not isinstance(values,list) or len(values)>30 or any(not isinstance(x,str) or not 1<=len(x)<=100 for x in values):
            raise ValueError('Provide up to 30 short synonyms')
        return list(dict.fromkeys(values))

    def create(self,workspace,body,actor):
        self.assets(workspace)
        kind=body.get('kind')
        if kind not in KINDS:raise ValueError('Unsupported ontology kind')
        label=str(body.get('label','')).strip()
        if not 2<=len(label)<=160:raise ValueError('Label requires 2–160 characters')
        desc=str(body.get('description','')).strip()
        if len(desc)>2000:raise ValueError('Description too long')
        oid=slug(body.get('object_id') or f'{kind}_{label}')
        if not oid or len(oid)<2:raise ValueError('Invalid object id')
        if self.repo.get('P3_OBJECT',workspace+'::'+oid):raise ValueError('Ontology object id already exists')
        binding=self._binding(workspace,kind,body.get('binding') or {})
        refs=body.get('depends_on',[])
        if not isinstance(refs,list) or len(refs)>30 or len(refs)!=len(set(refs)):
            raise ValueError('Dependencies must be unique and at most 30')
        if oid in refs:raise ValueError('Self-dependency is not allowed')
        for dep in refs:self.object(workspace,dep)
        if kind in {'business_concept','rule'} and not refs and not binding:
            raise ValueError('Concepts and rules must reference another ontology object or a scoped asset')
        out=self._put('P3_OBJECT',workspace,oid,{'workspace_id':workspace,'object_id':oid,'kind':kind,
           'label':label,'description':desc,'binding':binding,'depends_on':refs,'definition':str(body.get('definition',''))[:1000],
           'synonyms':self._synonyms(body.get('synonyms',[])),
           'semantics':validate_semantics(kind,body.get('semantics',{}),binding,self.p2.metadata(workspace,binding['asset_id']) if binding else None),
           'status':'draft','version':1,'authored_by':actor,'created_from':body.get('created_from','manual'),
           'authored_at':stamp(),'review_history':[]})
        self._snapshot_evidence(workspace,out,actor)
        self.audit(workspace,actor,'ontology_created',oid,{'kind':kind})
        return out

    def update(self,workspace,object_id,body,actor):
        old=self.object(workspace,object_id)
        if old['status'] not in ('draft','rejected'):raise ValueError('Return object to draft before editing')
        if body.get('expected_version')!=old['version']:raise ValueError('Ontology version conflict; reload before editing')
        label=str(body.get('label') if body.get('label') is not None else old['label']).strip()
        if not 2<=len(label)<=160:raise ValueError('Label requires 2–160 characters')
        kind=old['kind'];binding=self._binding(workspace,kind,body.get('binding') if body.get('binding') is not None else old['binding'])
        refs=body.get('depends_on') if body.get('depends_on') is not None else old['depends_on']
        if not isinstance(refs,list) or len(refs)>30 or len(refs)!=len(set(refs)) or object_id in refs:raise ValueError('Invalid dependencies')
        for dep in refs:self.object(workspace,dep)
        # Block dependency cycles so the semantic compiler has a DAG.
        def reaches(target,seen):
            if target==object_id:return True
            if target in seen:return False
            seen.add(target)
            return any(reaches(other,seen) for other in self.object(workspace,target).get('depends_on',[]))
        if any(reaches(dep,set()) for dep in refs):raise ValueError('Dependency cycle would be introduced')
        desc=str(body.get('description') if body.get('description') is not None else old['description'])
        if len(desc)>2000:raise ValueError('Description too long')
        changed={**old,'label':label,'description':desc,'definition':str(body.get('definition') if body.get('definition') is not None else old['definition'])[:1000],
          'binding':binding,'depends_on':refs,'version':old['version']+1,'status':'draft',
          'synonyms':self._synonyms(body.get('synonyms') if body.get('synonyms') is not None else old.get('synonyms',[])),
          'semantics':validate_semantics(kind,body.get('semantics') if body.get('semantics') is not None else old.get('semantics',{}),binding,self.p2.metadata(workspace,binding['asset_id']) if binding else None)}
        out=self._put('P3_OBJECT',workspace,object_id,changed)
        self._snapshot_evidence(workspace,out,actor)
        self.audit(workspace,actor,'ontology_updated',object_id,{'version':out['version']})
        return out

    def _join_evidence(self,workspace,obj):
        # A concept depending on semantics from distinct physical assets must
        # never invent a join; it needs a Phase 2 measured and approved edge.
        bound=set()
        aid=obj.get('binding',{}).get('asset_id')
        if aid:bound.add(aid)
        for dep in obj.get('depends_on',[]):
            try:
                d=self.object(workspace,dep)
                if d.get('binding',{}).get('asset_id'):bound.add(d['binding']['asset_id'])
            except KeyError:continue
        if len(bound)<2:return []
        relationships=self.p2.relationships(workspace)
        edges=[r for r in relationships if r.get('status')=='approved' and r.get('trusted_for_queries') and (r.get('evidence') or {}).get('passed')]
        reached={next(iter(bound))};selected=[]
        changed=True
        while changed:
            changed=False
            for r in edges:
                a,b=r['from_asset'],r['to_asset']
                if (a in reached)!=(b in reached):
                    reached.update([a,b]);selected.append(r);changed=True
        pairs=[{'assets':[r['from_asset'],r['to_asset']],'approved':r,'candidates':[r]} for r in selected]
        for asset in bound-reached:pairs.append({'assets':[next(iter(reached)),asset],'approved':None,'candidates':relationships})
        return pairs

    def _snapshot_evidence(self,workspace,obj,actor):
        aid=obj['binding'].get('asset_id');snap=[]
        if aid:
            meta=self.p2.metadata(workspace,aid)
            snap.append({'source_kind':'physical_schema','ref':aid,'fingerprint':meta['fingerprint'],
                         'measured':False,'status':'metadata','column_names':obj['binding']['columns']})
            ps=self.p2.profiles(workspace,aid)
            if ps:
                p=ps[0]
                snap.append({'source_kind':'aggregate_profile','ref':p['profile_id'],'fingerprint':p['fingerprint'],
                  'measured':bool(p['measured'] and p['status']=='complete'),'status':p['status']})
            cs=self.p2.contracts(workspace,aid)
            if cs and cs[0]['version']>0:
                c=cs[0];snap.append({'source_kind':'dataset_contract','ref':aid,
                    'fingerprint':c['schema_fingerprint'],'measured':False,'status':c['status'],'version':c['version']})
        for pair in self._join_evidence(workspace,obj):
            approved=pair['approved']
            if approved:
                snap.append({'source_kind':'relationship_evidence','ref':approved['relationship_id'],
                    'measured':True,'status':approved['status'],
                    'source_fingerprint':approved['evidence'].get('source_fingerprint'),
                    'target_fingerprint':approved['evidence'].get('target_fingerprint')})
        for dep in obj['depends_on']:
            d=self.object(workspace,dep)
            snap.append({'source_kind':'ontology_dependency','ref':dep,'version':d['version'],'status':d['status'], 'measured':False})
        # snapshot is immutable; future updates create an additional ledger entry
        eid='evi-'+uuid4().hex[:18]
        record={'workspace_id':workspace,'evidence_id':eid,'object_id':obj['object_id'],'object_version':obj['version'],
          'sources':snap,'source_digest':hashof(snap),'captured_at':stamp(),'captured_by':actor,
          'provenance':'metadata_and_phase2_snapshots_no_row_samples'}
        self._put('P3_EVIDENCE',workspace,eid,record)
        return record

    def diagnostics(self,workspace,obj):
        out=[];aid=obj['binding'].get('asset_id')
        if aid:
            try:
                meta=self.p2.metadata(workspace,aid)
                if meta['fingerprint']!=obj['binding'].get('schema_fingerprint'):
                    out.append(error('SCHEMA_DRIFT','Physical schema changed after ontology binding'))
                profile=self.p2.current_profile(workspace,aid)
                if not profile or not profile.get('measured') or profile.get('status')!='complete':
                    out.append(error('NO_MEASURED_PROFILE','Complete, measured Phase 2 profiling is required'))
                elif profile.get('fingerprint')!=meta['fingerprint']:
                    out.append(error('STALE_PROFILE','Last measured profile predates current schema'))
                else:
                    out.append(error('PROFILE_MEASURED',f"Profile {profile['profile_id']} supports this dataset",'info',[profile['profile_id']]))
                contract=self.p2.contracts(workspace,aid)[0]
                if contract['status']!='certified' or contract.get('schema_fingerprint')!=meta['fingerprint']:
                    out.append(error('CONTRACT_NOT_CERTIFIED','Certified current-schema Phase 2 contract is required'))
                else:
                    out.append(error('CONTRACT_CERTIFIED','Current physical contract certified','info',[aid]))
                if obj['kind']=='code_set' and profile:
                    col=obj['binding']['columns'][0];pc=next((c for c in profile['columns'] if c['name']==col),{})
                    count=pc.get('distinct_count')
                    if count is not None and count>500:
                        out.append(error('CODE_SET_CARDINALITY',f'{count} distinct codes; review classification','warning'))
            except (KeyError,ValueError):out.append(error('OUT_OF_SCOPE','Physical binding no longer belongs to the workspace'))
        if obj['kind']=='measure':
            try:
                sem=obj.get('semantics') or {}
                if not sem:raise ValueError('Provide an executable metric with aggregation, expression, grain, unit and additivity')
                validate_semantics('measure',sem,obj['binding'],self.p2.metadata(workspace,aid))
                if sem.get('unit')=='unspecified':raise ValueError('Confirm the metric unit before certification')
                grain=self.p2.grain_evidence(workspace,aid,sem['grain'])
                if not grain['passed']:raise ValueError('Declared measure grain contains null or duplicated keys')
            except (ValueError,KeyError) as exc:out.append(error('MEASURE_DEFINITION',str(exc)))
        if obj['kind']=='rule' and not obj.get('definition'):
            out.append(error('RULE_DEFINITION','State a testable business rule'))
        if obj['kind'] in {'business_concept','rule'} and not obj['depends_on'] and not aid:
            out.append(error('UNGROUNDED_CONCEPT','Business concept must link to scoped evidence'))
        for pair in self._join_evidence(workspace,obj):
            r=pair['approved']
            fresh=False
            if r:
                ev=r.get('evidence') or {}
                fresh=(is_fresh(ev) and ev.get('target_duplicate_rows')==0
                    and ev.get('source_fingerprint')==self.p2.metadata(workspace,r['from_asset'])['fingerprint']
                    and ev.get('target_fingerprint')==self.p2.metadata(workspace,r['to_asset'])['fingerprint'])
            if not r or not fresh:
                out.append(error('UNVERIFIED_SEMANTIC_JOIN',
                    'A cross-dataset semantic dependency requires a currently measured and approved Phase 2 relationship',
                    'error',[x['relationship_id'] for x in pair['candidates'][:3]]))
            else:
                out.append(error('RELATIONSHIP_APPROVED',f'Measured and approved join {r["relationship_id"]}',
                    'info',[r['relationship_id']]))
        for dep in obj['depends_on']:
            try:
                other=self.object(workspace,dep)
                if other['status']!='certified':out.append(error('DEPENDENCY_NOT_CERTIFIED',f'Dependency {dep} is not certified','error',[dep]))
            except KeyError:out.append(error('MISSING_DEPENDENCY',f'Dependency {dep} was removed'))
        ev=[r for r in self.evidence(workspace,obj['object_id']) if r['object_version']==obj['version']]
        if not ev:out.append(error('EVIDENCE_MISSING','No evidence snapshot for current version'))
        # No false measured provenance and no automatic trust for weak proposals.
        if not aid and obj['kind'] not in {'business_concept','rule'}:
            out.append(error('MISSING_BINDING','Physical ontology kind must have a binding'))
        return out

    def compile(self,workspace,object_id=None):
        objects=[self.object(workspace,object_id)] if object_id else self.objects(workspace)
        rows=[]
        for o in objects:
            ds=self.diagnostics(workspace,o)
            blocking=[x for x in ds if x['severity']=='error']
            rows.append({'object_id':o['object_id'],'label':o['label'],'kind':o['kind'],'status':o['status'],
                'version':o['version'],'diagnostics':ds,'blocking':len(blocking),
                'trust_state':'certified' if o['status']=='certified' and not blocking else 'blocked' if blocking else 'evidence_supported',
                'can_certify':not blocking and o['status']=='reviewed'})
        return {'workspace_id':workspace,'results':rows,'counts':{'objects':len(rows),
            'blocked':sum(bool(r['blocking']) for r in rows),'certified':sum(r['trust_state']=='certified' for r in rows),
            'evidence_supported':sum(r['trust_state']=='evidence_supported' for r in rows)},
            'compiler':'semantic_structural_diagnostics','executes_sql':False,
            'production_query_integration':False}

    def transition(self,workspace,object_id,decision,note,actor,expected_version):
        o=self.object(workspace,object_id)
        if expected_version!=o['version']:raise ValueError('Ontology version conflict; reload before review')
        if decision not in TRANSITIONS.get(o['status'],set()):raise ValueError('Unsupported ontology status transition')
        if len(note.strip())<5:raise ValueError('Provide a review rationale of at least five characters')
        if decision=='certified':
            if o['authored_by']==actor:raise ValueError('Independent steward required to certify an authored object')
            ds=self.diagnostics(workspace,o)
            if any(x['severity']=='error' for x in ds):raise ValueError('Compiler has unresolved blocking diagnostics')
            for dep in o['depends_on']:
                if self.object(workspace,dep)['status']!='certified':raise ValueError('All ontology dependencies must be certified')
        reviewed={**o,'version':o['version']+1,'status':decision,
          'review_history':(o['review_history']+[{'by':actor,'at':stamp(),'from':o['status'],'to':decision,'note':note[:1500]}])[-40:]}
        out=self._put('P3_OBJECT',workspace,object_id,reviewed)
        self._snapshot_evidence(workspace,out,actor)
        self.audit(workspace,actor,'ontology_'+decision,object_id,{'note':note[:250]})
        return out

    def propose(self,workspace,actor,max_assets=30):
        if not 1<=max_assets<=100:raise ValueError('max_assets must be 1–100')
        made=[];skipped=0
        for a in self.assets(workspace)[:max_assets]:
            meta=self.p2.metadata(workspace,a['asset_id']);cols=meta['columns']
            if not cols:continue
            names=[c['name'] for c in cols];grain=[c['name'] for c in cols if c.get('primary_key')]
            proposals=[('entity',names,a['table'],{},'')]
            if grain:
                proposals[0]=('entity',names,a['table'],{'grain':grain},'')
                proposals.append(('measure',grain,a['table']+' record count',
                    {'grain':grain,'aggregation':'count','unit':'records','additivity':'additive'},'Count records at the declared physical grain'))
            for c in cols:
                if c.get('primary_key') or c['suggested_role']=='foreign_key_candidate':
                    if grain:
                        proposals.append(('measure',list(dict.fromkeys(grain+[c['name']])),a['table']+' distinct '+c['name'],
                            {'grain':grain,'aggregation':'count_distinct','expression':{'column':c['name']},'unit':'distinct identifiers','additivity':'non_additive'},
                            'Confirm whether this identifier represents the requested business entity'))
                    continue
                if grain and any(k in str(c['type']).lower() for k in ('int','decimal','double','numeric','float','real')):
                    avg=any(h in c['name'].lower() for h in ('rate','ratio','percent','average','score'))
                    sem={'grain':grain,'aggregation':'avg' if avg else 'sum','expression':{'column':c['name']},
                        'unit':'unspecified','additivity':'non_additive' if avg else 'additive'}
                    proposals.append(('measure',list(dict.fromkeys(grain+[c['name']])),a['table']+' '+c['name'],sem,
                        'Candidate only: steward must verify unit, aggregation, grain and required filters'))
                if c['suggested_role']=='temporal':
                    proposals.append(('event',list(dict.fromkeys(grain+[c['name']])),a['table']+' '+c['name']+' event',
                        {'grain':grain,'time':{'column':c['name'],'timezone':'UTC','calendar':'gregorian'}} if grain else {},''))
                if c['suggested_role']=='dimension':proposals.append(('code_set',[c['name']],a['table']+' '+c['name']+' values',{},''))
            for kind,columns,label,sem,definition in proposals:
                oid=slug(f'{kind}_{label}_{a["asset_id"][-8:]}')
                if self.repo.get('P3_OBJECT',workspace+'::'+oid):skipped+=1;continue
                made.append(self.create(workspace,{'kind':kind,'object_id':oid,'label':label,
                    'description':'Metadata proposal; requires business review.', 'binding':{'asset_id':a['asset_id'],'columns':columns},
                    'definition':definition,'semantics':sem,'created_from':'schema_inference'},actor))
        return {'workspace_id':workspace,'created':len(made),'skipped_existing':skipped,'objects':made,
            'note':'Drafts only. Units, business predicates and meanings require steward review.'}

    def questions(self,workspace):
        items=[]
        for o in self.objects(workspace):
            for d in self.diagnostics(workspace,o):
                if d['severity']=='info':continue
                qid='q-'+hashof([o['object_id'],d['code']])[:20]
                recorded=self.repo.get('P3_QUESTION',workspace+'::'+qid)
                items.append({'question_id':qid,'workspace_id':workspace,'object_id':o['object_id'],
                    'question':d['message'],'diagnostic_code':d['code'],'severity':d['severity'],
                    'review_status':(recorded or {}).get('review_status','open'),
                    'review_note':(recorded or {}).get('review_note',''),
                    'reviewed_by':(recorded or {}).get('reviewed_by','')})
        return items

    def review_question(self,workspace,qid,decision,note,actor):
        item=next((r for r in self.questions(workspace) if r['question_id']==qid),None)
        if not item:raise KeyError('Question is not currently applicable')
        if decision not in {'acknowledged','needs_action','resolved'}:raise ValueError('Unsupported question ruling')
        if len(note.strip())<5:raise ValueError('Review note must contain at least five characters')
        # Acknowledging does not suppress diagnostics or bypass compiler trust gates.
        out=self._put('P3_QUESTION',workspace,qid,{**item,'review_status':decision,'review_note':note[:1500],
             'reviewed_by':actor,'reviewed_at':stamp()})
        self.audit(workspace,actor,'sme_question_'+decision,qid,{'object_id':item['object_id']})
        return out

    def graph(self,workspace,mode='conceptual',focus=None,limit=250):
        if mode not in MODES:raise ValueError('Unknown ontology graph mode')
        if limit<1 or limit>600:raise ValueError('Graph limit must be 1–600')
        objects=self.objects(workspace);nodes={};edges=[]
        def node(id,label,kind,status='reference',score=0):
            nodes[id]={'id':id,'label':label,'kind':kind,'status':status,'trust_score':score}
        def edge(a,b,kind):edges.append({'source_id':a,'target_id':b,'kind':kind})
        for o in objects:
            score=100 if o['status']=='certified' and not any(d['severity']=='error' for d in self.diagnostics(workspace,o)) else 50 if o['status']=='reviewed' else 10
            node(o['object_id'],o['label'],o['kind'],o['status'],score)
        for o in objects:
            if mode in {'conceptual','dependency','logical'}:
                for dep in o['depends_on']:
                    if dep in nodes:edge(o['object_id'],dep,'DEPENDS_ON')
            if mode=='conceptual':continue
            if mode in {'logical','dependency'}:
                aid=o['binding'].get('asset_id')
                if aid:
                    a=self.p2.asset(workspace,aid)
                    node(aid,a['table'],'dataset');edge(o['object_id'],aid,'BOUND_TO')
                    if mode=='logical':
                        for c in o['binding'].get('columns',[]):
                            cid=aid+':'+c;node(cid,c,'column');edge(o['object_id'],cid,'USES_COLUMN');edge(cid,aid,'COLUMN_OF')
            if mode=='evidence':
                ledgers=[e for e in self.evidence(workspace,o['object_id']) if e['object_version']==o['version']]
                for e in ledgers[-1:]:
                    for s in e['sources']:
                        nid=s['source_kind']+':'+str(s['ref'])
                        node(nid,str(s['ref'])[-25:],s['source_kind'],s['status']);edge(o['object_id'],nid,'SUPPORTED_BY')
        if focus:
            if focus not in nodes:raise KeyError('Focused node not in graph')
            nearby={focus}
            for e in edges:
                if focus in (e['source_id'],e['target_id']):nearby.add(e['source_id']);nearby.add(e['target_id'])
            nodes={k:v for k,v in nodes.items() if k in nearby}
            edges=[e for e in edges if e['source_id'] in nodes and e['target_id'] in nodes]
        total=len(nodes)
        wanted=list(nodes)[:limit];wanted_set=set(wanted);edges=[e for e in edges if e['source_id'] in wanted_set and e['target_id'] in wanted_set]
        return {'workspace_id':workspace,'mode':mode,'focus':focus,'total_nodes':total,
                'nodes':[nodes[k] for k in wanted], 'edges':edges[:1200], 'truncated':total>limit,
                'note':'Graph displays review state; a suggestion does not confer certified query trust.'}

    def publish_snapshot(self,workspace,version,note,actor):
        self.assets(workspace)
        version=version.strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}',version):raise ValueError('Invalid release version')
        if len(note.strip())<5:raise ValueError('Release rationale required')
        if self.repo.get('P3_RELEASE',workspace+'::'+version):raise ValueError('Release version already exists')
        objects=self.objects(workspace)
        certified=[o for o in objects if o['status']=='certified']
        if not certified:raise ValueError('At least one certified object is required for publication')
        bad=[o['object_id'] for o in certified if any(d['severity']=='error' for d in self.diagnostics(workspace,o))]
        if bad:raise ValueError('Certified object evidence is stale or incomplete: '+', '.join(bad[:5]))
        payload=[{k:v for k,v in o.items() if k not in {'review_history','updated_at'}} for o in certified]
        release={'workspace_id':workspace,'version':version,'published_at':stamp(),'published_by':actor,
            'note':note[:2000],'certified_count':len(payload),'content_digest':hashof(payload),'objects':payload,
            'target':'phase3_review_snapshot_only','production_query_integration':False}
        out=self._put('P3_RELEASE',workspace,version,release)
        self.audit(workspace,actor,'ontology_release',version,{'objects':len(payload)})
        return out

    def overview(self,workspace):
        assets=self.assets(workspace);objects=self.objects(workspace);compiled=self.compile(workspace)
        return {'workspace_id':workspace,'assets':len(assets),'objects':len(objects),'by_kind':{k:sum(o['kind']==k for o in objects) for k in sorted(KINDS)},
           'by_status':{k:sum(o['status']==k for o in objects) for k in sorted(STATES)},
           'blocked':compiled['counts']['blocked'],'questions':len(self.questions(workspace)),
           'evidence_records':len(self.evidence(workspace)),
           'releases':len(self._list('P3_RELEASE',workspace)),'production_query_integration':False}
