"""Shared identities and projections for authoring, GraphRAG, Ask and reports.

P3_OBJECT and P2_RELATIONSHIP are the authoring stores. Promoted releases are the
execution authority. Legacy dictionaries are import sources, never query authority.
"""
from copy import deepcopy
from app.repositories.control_repository import ControlRepository


class SemanticRegistryService:
    def __init__(self):
        self.repo = ControlRepository()

    def objects(self, workspace):
        return [r for r in self.repo.list('P3_OBJECT', 1000) if r.get('workspace_id') == workspace]

    def latest_release(self, workspace):
        releases = [r for r in self.repo.list('P4_RELEASE', 1000) if r.get('workspace_id') == workspace]
        if not releases:
            raise ValueError('Publish and promote a certified ontology release before querying')
        return max(releases, key=lambda r:r['published_at'])['release_id']

    def project_context(self, workspace, context):
        from app.services.phase2_service import Phase2Service
        objects = self.objects(workspace)
        if not objects:
            return context
        p2 = Phase2Service()
        assets = {a['asset_id']:a for a in p2.assets(workspace)}
        result = deepcopy(context)
        for k in ('entities', 'concepts', 'metrics', 'dimensions'):
            result[k] = {}
        result['bindings'] = {'concepts':{}, 'dimensions':{}, 'dates':{}}
        result['rules'] = []
        for o in objects:
            ident=o['object_id'];binding=o.get('binding',{});sem=o.get('semantics',{})
            asset=assets.get(binding.get('asset_id'));spec={**o,'id':ident}
            if asset:
                db=asset['database'] if p2.scope(workspace)['source_id']!='federated' else f"{asset['source_id']}::{asset['database']}::{asset.get('schema','')}"
                physical={'database':db,'physical_database':asset['database'],'table':asset['table'],'asset_id':asset['asset_id'],'source_id':asset['source_id'],'status':o['status']}
                spec.update(physical)
                for c in binding['columns']:
                    did=ident+':'+c
                    dim={**physical,'column':c,'label':c,'object_id':ident,'status':o['status']}
                    result['dimensions'][did]=dim;result['bindings']['dimensions'][did]=dim
                result['bindings']['concepts'][ident]={**physical,'key':(sem.get('grain') or binding['columns'])[0]}
                if sem.get('time'):
                    result['bindings']['dates'][ident]={**physical,**sem['time']}
            if o['kind']=='measure':
                spec.update({'aggregation':sem.get('aggregation'),'unit':sem.get('unit'),
                    'additivity':sem.get('additivity'),'preferred_sources':[{**physical,'column':(sem.get('expression') or {}).get('column'),
                    'aggregation':sem.get('aggregation')}] if asset else []})
                result['metrics'][ident]=spec
            elif o['kind'] in {'entity','event'}:
                result['entities'][ident]=spec;result['concepts'][ident]=spec
            elif o['kind']=='rule':result['rules'].append(spec)
            else:result['concepts'][ident]=spec
        result['semantic_authority']='certified_release_registry'
        return result

    def graph_relationships(self, workspace):
        from app.services.phase2_service import Phase2Service
        from app.services.business_semantics import is_fresh
        from app.services.phase2_service import digest
        p2=Phase2Service();assets={a['asset_id']:a for a in p2.assets(workspace)}
        fingerprints={}
        rows=[]
        for r in p2.relationships(workspace):
            a,b=assets.get(r['from_asset']),assets.get(r['to_asset'])
            if not a or not b:continue
            e=r.get('evidence') or {};sc,tc=p2.relationship_columns(r)
            trusted=bool(r.get('trusted_for_queries') and r['status']=='approved' and is_fresh(e)
                and e.get('passed') is True and e.get('target_duplicate_rows')==0
                and e.get('definition_digest')==digest([r['from_asset'],sc,r['to_asset'],tc,r.get('role','')]))
            if trusted:
                try:
                    for aid in (r['from_asset'],r['to_asset']):
                        if aid not in fingerprints:fingerprints[aid]=p2.metadata(workspace,aid)['fingerprint']
                    trusted=e.get('source_fingerprint')==fingerprints[r['from_asset']] and e.get('target_fingerprint')==fingerprints[r['to_asset']]
                except Exception:trusted=False
            multi=p2.scope(workspace)['source_id']=='federated'
            adb=f"{a['source_id']}::{a['database']}::{a.get('schema','')}" if multi else a['database']
            bdb=f"{b['source_id']}::{b['database']}::{b.get('schema','')}" if multi else b['database']
            rows.append({**r,'id':r['relationship_id'],'market':workspace,
                'trusted_for_queries':bool(trusted),
                'from_db':adb,'from_table':a['table'],'to_db':bdb,'to_table':b['table'],
                'source':'semantic_registry','relationship_type':r.get('role','many_to_one')})
        return rows

    @staticmethod
    def catalog(objects, assets, relationships, release):
        from app.services.business_semantics import validate_semantics
        metrics={};concepts={}
        for o in objects:
            sem=o.get('semantics') or {}
            entry={'object_id':o['object_id'],'label':o['label'],'description':o.get('description',''),
                'definition':o.get('definition',''),
                'synonyms':o.get('synonyms',[]),'binding':o.get('binding',{}),'semantics':sem,
                'depends_on':o.get('depends_on',[]),'version':o['version']}
            if o['kind']=='measure':
                if not sem:raise ValueError('Release contains a prose-only metric; migrate its executable definition')
                validate_semantics('measure',sem,o['binding'])
                metrics[o['object_id']]=entry
            elif o['kind'] in {'business_concept','rule'}:
                entry['executable']=bool(sem.get('filters') and o.get('binding'))
                concepts[o['object_id']]=entry
        return {'workspace_id':release['workspace_id'],'release_id':release['release_id'],
            'release_digest':release['content_digest'],'assets':assets,'relationships':relationships,
            'metrics':metrics,'concepts':concepts,'policy':'Approved metric IDs and exact unique-target joins only'}
