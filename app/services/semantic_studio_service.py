"""Semantic Studio is an authoring view of the shared ontology registry."""
from app.services.phase3_service import Phase3Service
from app.services.semantic_registry_service import SemanticRegistryService
from app.services.graph_rag_service import GraphRAGService
from app.repositories.control_repository import ControlRepository

KIND_MAP={'entity':'entity','dimension':'code_set','metric':'measure','concept':'business_concept','business_term':'business_concept'}


class SemanticStudioService:
    def __init__(self):self.p3=Phase3Service();self.registry=SemanticRegistryService();self.control=ControlRepository()

    def objects(self,workspace,kind):
        if kind not in KIND_MAP:raise ValueError('Use typed ontology objects; verified SQL templates are no longer query authority')
        return [{'id':o['object_id'],**o} for o in self.registry.objects(workspace) if o['kind']==KIND_MAP[kind]]

    def overview(self,workspace):
        objects=self.registry.objects(workspace)
        return {'workspace_id':workspace,'counts':{k:sum(o['kind']==v for o in objects) for k,v in KIND_MAP.items()},
            'schema_drift':(self.control.get('WORKSPACE',workspace) or {}).get('schema_drift',[]),
            'suggestions':[r for r in self.control.list('SUGGESTION',1000) if r.get('market')==workspace],
            'relationships':self.registry.graph_relationships(workspace),'semantic_authority':'P3_OBJECT / P2_RELATIONSHIP',
            'metric_validation':{'ok':all(not any(d['severity']=='error' for d in self.p3.diagnostics(workspace,o)) for o in objects if o['kind']=='measure')}}

    def upsert(self,workspace,kind,object_id,spec,actor='system'):
        if kind not in KIND_MAP:raise ValueError('Unsupported semantic kind')
        existing=next((o for o in self.registry.objects(workspace) if o['object_id']==object_id),None)
        binding=spec.get('binding')
        if binding is None:
            if spec.get('database') and spec.get('table'):
                asset=next((a for a in self.p3.assets(workspace) if a['database']==spec['database'] and a['table']==spec['table']),None)
                if not asset:raise ValueError('Physical binding is outside the workspace')
                columns=spec.get('columns') or ([spec['column']] if spec.get('column') else [c['name'] for c in self.p3.p2.metadata(workspace,asset['asset_id'])['columns']])
                binding={'asset_id':asset['asset_id'],'columns':columns}
            else:binding=(existing or {}).get('binding',{})
        body={'kind':KIND_MAP[kind],'object_id':object_id,'label':spec.get('label',object_id),'description':spec.get('description',''),
            'definition':spec.get('definition',''),'binding':binding,'depends_on':spec.get('depends_on',[]),
            'synonyms':spec.get('synonyms',[]),'semantics':spec.get('semantics',{}),'created_from':'semantic_studio'}
        if spec.get('status') not in (None,'draft','inferred', (existing or {}).get('status')):
            raise ValueError('Use explicit review transitions; authoring cannot bypass certification')
        if existing:out=self.p3.update(workspace,object_id,{**body,'expected_version':spec.get('expected_version',existing['version'])},actor)
        else:out=self.p3.create(workspace,body,actor)
        GraphRAGService().build(workspace,persist=True)
        return {'id':out['object_id'],**out}

    def transition(self,workspace,kind,object_id,status,note='',actor='system'):
        o=self.p3.object(workspace,object_id)
        if KIND_MAP.get(kind)!=o['kind']:raise ValueError('Semantic kind mismatch')
        out=self.p3.transition(workspace,object_id,status,note,actor,o['version'])
        GraphRAGService().build(workspace,persist=True)
        return {'id':out['object_id'],**out}

    def promote_suggestion(self,workspace,suggestion_id,actor='system'):
        suggestion=self.control.get('SUGGESTION',suggestion_id)
        if not suggestion or suggestion.get('market')!=workspace:raise KeyError(suggestion_id)
        assets=self.p3.assets(workspace)
        asset=next((a for a in assets if a['database']==suggestion.get('database') and a['table']==suggestion.get('table')),None)
        if not asset:raise ValueError('Suggestion is not physically scoped')
        made=self.p3.propose(workspace,actor,100)
        return {'status':'draft','objects':made['objects'],'message':'Review executable definitions in the shared Object Studio; suggestions are never certified automatically.'}
