"""Batch preparation and review without automatic business certification."""
from datetime import datetime, timezone
from app.services.phase2_service import Phase2Service
from app.services.phase3_service import Phase3Service
from app.services.phase4_service import Phase4Service
from app.services.llm_planner_service import LLMPlannerService
from app.repositories.control_repository import ControlRepository


class GuidedOnboardingService:
    def __init__(self):self.p2=Phase2Service();self.p3=Phase3Service();self.p4=Phase4Service();self.repo=ControlRepository()

    def status(self,workspace):
        assets=self.p2.assets(workspace);objects=self.p3.objects(workspace);contracts=self.p2.contracts(workspace)
        llm=LLMPlannerService().status();releases=self.p4.releases(workspace)
        return {'workspace_id':workspace,'llm':llm,'datasets':[{'asset':a,
            'profile':self.p2.current_profile(workspace,a['asset_id']),
            'contract':next(c for c in contracts if c['asset_id']==a['asset_id'])} for a in assets],
            'objects':objects,'relationships':self.p2.relationships(workspace),'releases':releases,
            'can_ask':bool(llm['ready'] and releases),'review_required':True,
            'steps':['Connect and scope tables','Prepare profiles and draft definitions','Confirm metric units, grain and predicates',
                'Review contracts and exact relationship evidence','Independent ontology certification','Publish and promote','Ask with a verified LLM']}

    def prepare(self,workspace,actor,owner):
        if not owner.strip():raise ValueError('A dataset owner is required')
        assets=self.p2.assets(workspace)
        if len(assets)>100:raise ValueError('Split preparation into workspaces of at most 100 datasets')
        profiles=[];contracts=[]
        for a in assets:
            current=self.p2.current_profile(workspace,a['asset_id']);meta=self.p2.metadata(workspace,a['asset_id'])
            if not current or current['fingerprint']!=meta['fingerprint'] or current['status']!='complete' or not current['measured']:
                profiles.append(self.p2.profile(workspace,a['asset_id'],'standard',actor,200))
            c=self.p2.contracts(workspace,a['asset_id'])[0]
            if c['version']==0:contracts.append(self.p2.save_contract(workspace,a['asset_id'],{'owner':owner},actor))
        proposals=self.p3.propose(workspace,actor,100)
        measured=[]
        for r in self.p2.relationships(workspace):
            if r['status']=='suggested':measured.append(self.p2.validate_relationship(workspace,r['relationship_id'],actor))
        return {'profiles_prepared':len(profiles),'contracts_prepared':len(contracts),'objects_proposed':proposals['created'],
            'relationships_measured':len(measured),'certified_automatically':0,'status':self.status(workspace)}

    def review_batch(self,workspace,items,actor,note):
        if not isinstance(items,list) or not 1<=len(items)<=100 or len(note.strip())<5:raise ValueError('Provide 1–100 review items and a rationale')
        if len({(i.get('kind'),i.get('id')) for i in items})!=len(items):raise ValueError('Duplicate review items')
        # Preflight all author/version/diagnostic checks before mutating any records.
        for item in items:
            kind=item.get('kind');decision=item.get('decision');ident=item.get('id')
            if kind=='object':
                o=self.p3.object(workspace,ident)
                if item.get('expected_version')!=o['version']:raise ValueError('Ontology version conflict')
                from app.services.phase3_service import TRANSITIONS
                if decision not in TRANSITIONS.get(o['status'],set()):raise ValueError('Invalid object transition')
                if decision=='certified':
                    if o['authored_by']==actor:raise ValueError('Independent steward required')
                    if any(d['severity']=='error' for d in self.p3.diagnostics(workspace,o)):raise ValueError('Object has blocking evidence diagnostics')
            elif kind=='contract':
                c=self.p2.contracts(workspace,ident)[0]
                if item.get('expected_version')!=c['version']:raise ValueError('Contract version conflict')
                if (c['status'],decision) not in {('draft','reviewed'),('reviewed','certified')}:
                    raise ValueError('Invalid contract review transition')
                if decision=='certified':
                    p=self.p2.current_profile(workspace,ident);m=self.p2.metadata(workspace,ident)
                    if not c['owner'] or c['schema_fingerprint']!=m['fingerprint'] or not p or not p['measured'] or p['status']!='complete' or p['fingerprint']!=m['fingerprint']:
                        raise ValueError('Contract evidence is incomplete')
            elif kind=='relationship':
                r=self.p2._get('relationship',workspace,ident)
                if decision not in {'approved','rejected'}:raise ValueError('Invalid relationship decision')
                if decision=='approved' and (r['status']!='evidenced' or not (r.get('evidence') or {}).get('passed')):
                    raise ValueError('Relationship evidence must pass')
            else:raise ValueError('Unknown review item')
        results=[]
        for item in items:
            if item['kind']=='object':out=self.p3.transition(workspace,item['id'],item['decision'],note,actor,item['expected_version'])
            elif item['kind']=='contract':out=self.p2.transition_contract(workspace,item['id'],item['decision'],note,actor)
            else:out=self.p2.review_relationship(workspace,item['id'],item['decision'],note,actor)
            results.append(out)
        return {'reviewed':len(results),'results':results}

    def publish(self,workspace,version,note,actor):
        self.p3.publish_snapshot(workspace,version,note,actor)
        return self.p4.promote(workspace,version,actor)

    def refresh(self,workspace,actor='semantic-evidence-worker'):
        refreshed=self.p2.refresh_relationships(workspace,actor);grains=[]
        for o in self.p3.objects(workspace):
            if o['status']=='certified' and o['kind']=='measure':
                sem=o.get('semantics') or {}
                if sem.get('grain'):grains.append(self.p2.grain_evidence(workspace,o['binding']['asset_id'],sem['grain']))
        result={'workspace_id':workspace,'relationships_refreshed':len(refreshed),
            'relationships_revoked':sum(not r.get('trusted_for_queries') for r in refreshed),
            'invalid_grains':sum(not g['passed'] for g in grains),'checked_at':datetime.now(timezone.utc).isoformat()}
        self.repo.put('EVIDENCE_REFRESH',workspace,result)
        return result

    def refresh_all(self):
        results=[]
        for w in self.repo.list('WORKSPACE',500):
            if not w.get('scope_id'):continue
            try:results.append(self.refresh(w['workspace_id']))
            except Exception as exc:
                self.repo.put('EVIDENCE_REFRESH',w['workspace_id'],{'workspace_id':w['workspace_id'],'status':'error','error_type':type(exc).__name__,'checked_at':datetime.now(timezone.utc).isoformat()})
        return results
