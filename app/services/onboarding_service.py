from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import re
from app.config import get_settings
from app.repositories.semantic_repository import SemanticRepository
from app.repositories.control_repository import ControlRepository
from app.services.type_inference import infer_semantic_type
from app.services.dashboard_service import DashboardService
from app.services.market_service import MarketService
from app.services.data_source_service import DataSourceService

_IGNORE_PREFIX=("_hoodie_","_execution","_source","_uuid")
_NUMERIC_HINTS={'number','numeric','decimal','double','float','real','int','integer','bigint','smallint'}
_STEWARD_STATUSES={'reviewed','approved','verified','certified','deprecated'}

def _slug(value):
    x=re.sub(r'[^a-z0-9]+','_',str(value or '').lower()).strip('_'); return x or 'asset'
def _workspace_id(value):
    x=re.sub(r'[^a-z0-9_-]+','-',str(value or '').lower()).strip('-_')
    if not x: raise ValueError('workspace_id is required')
    return x[:80]
def _label(value): return re.sub(r'[_\-]+',' ',str(value or '')).strip().title()

class OnboardingService:
    """Metadata-only onboarding with schema-drift protection and workspace isolation."""
    def __init__(self):
        self.s=get_settings(); self.repo=SemanticRepository(); self.markets=MarketService(); self.sources=DataSourceService(); self.control=ControlRepository()

    def status(self,market=None):
        stats=DashboardService().stats(); ctx=self.markets.context(market) if market else None
        row=self.control.get('WORKSPACE',market) if market else None
        return {'mode':self.s.app_mode,'workspace':(ctx or {}).get('market',{}),'sample_values_enabled':self.s.allow_sample_values,'stats':stats,'tables':stats['tables'],'columns':stats['columns'],'description_coverage':stats['description_coverage'],'schema_drift':(row or {}).get('schema_drift',[]),'capabilities':{'catalog_sync':bool(self.sources.configured_ids()),'relationship_discovery':True,'sample_rows_required':False,'runtime_semantic_generation':True,'schema_drift_protection':True,'multi_workspace_isolation':True}}

    def _build_context(self,workspace_id,display_name,source_id,discovery):
        objects=discovery.get('objects',[]) or []; names=[o.get('table') for o in objects]; duplicates={x for x in names if names.count(x)>1}
        concepts={}; entities={}; dimensions={}; bindings={'concepts':{},'dimensions':{},'dates':{}}; metrics={}; glossary={}; suggestions=[]
        non_additive_hints=('ratio','rate','pct','percent','percentage','median','avg','average','score','confidence','lift','support','share','index')
        for obj in objects:
            db=obj.get('database') or obj.get('schema') or 'default'; table=obj.get('table')
            if not table: continue
            cid=_slug(f'{db}_{table}' if table in duplicates else table); desc=obj.get('description') or f'Physical table {db}.{table} discovered from {source_id} metadata.'
            cols=obj.get('columns',[]) or []
            key_col=next((c.get('name') for c in cols if c.get('primary_key')),None) or next((c.get('name') for c in cols if infer_semantic_type(c.get('name',''),c.get('type',''),[])=='identifier'),None)
            concepts[cid]={'label':_label(table),'description':desc,'synonyms':[table.replace('_',' '),_label(table)],'status':'inferred','source':'catalog_metadata'}
            entities[cid]={'label':_label(table),'description':desc,'status':'inferred','source':'catalog_metadata'}
            bindings['concepts'][cid]={'database':db,'table':table,**({'key':key_col} if key_col else {})}

            # Every physical entity receives an inferred row-count metric. It is safe to preview in development,
            # but remains visibly inferred until a steward certifies it for production reporting.
            row_mid=_slug(f'{cid}_record_count')
            metrics[row_mid]={
                'label':f'{_label(table)} Record Count','description':f'Number of rows in {db}.{table}.',
                'synonyms':['record count','row count','number of records',f'count {_label(table)}',f'how many {_label(table)}'],
                'aggregation':'count','additivity':'additive','status':'inferred','entity':cid,'source':'catalog_metadata',
                'preferred_sources':[{'database':db,'table':table,'aggregation':'count','status':'inferred'}]
            }

            for c in cols:
                name=c.get('name','')
                if not name or name.lower().startswith(_IGNORE_PREFIX): continue
                sem=c.get('semantic_type') or infer_semantic_type(name,c.get('type','string'),[]); did=_slug(f'{table}_{name}'); cdesc=c.get('comment') or f'Column {name} from {db}.{table}.'; label=_label(name)
                synonyms=[name.replace('_',' '),label]
                if name.lower().endswith('_id'):
                    base=_label(name[:-3]); synonyms += [base+' id',base+' ids','total '+base+' ids','number of '+base+' ids','count '+base+' ids','unique '+base+' ids']
                dimensions[did]={'label':label,'description':cdesc,'synonyms':list(dict.fromkeys(synonyms)),'status':'inferred','semantic_type':sem,'entity':cid,'source':'catalog_metadata'}
                bindings['dimensions'][did]={'database':db,'table':table,'column':name,'label':label,'status':'inferred'}
                if sem in {'date','datetime','timestamp','temporal'} or any(x in name.lower() for x in ['date','time','timestamp','created_at','updated_at']): bindings['dates'][did]={'database':db,'table':table,'column':name,'status':'inferred'}
                typ=str(c.get('type','')).lower(); lname=name.lower()

                # Identifier/reference columns become distinct-count measures, so questions such as
                # "total car ids" cannot silently degrade to COUNT(*).
                if sem in {'identifier','reference'} or lname.endswith('_id'):
                    mid=_slug(f'unique_{table}_{name}')
                    mlabel=f'Unique {label}'
                    msyn=list(dict.fromkeys([mlabel,'count '+label,'number of '+label,'total '+label] + synonyms))
                    metrics[mid]={'label':mlabel,'description':f'Distinct count of {db}.{table}.{name}.','synonyms':msyn,'aggregation':'count_distinct','additivity':'non_additive','status':'inferred','entity':cid,'dimensions':[did],'source':'catalog_metadata','preferred_sources':[{'database':db,'table':table,'column':name,'aggregation':'count_distinct','status':'inferred'}]}
                    suggestions.append({'id':f'metric-{workspace_id}-{mid}','object_id':mid,'type':'metric_candidate','label':mlabel,'database':db,'table':table,'column':name,'aggregation':'count_distinct','reason':'Identifier metadata suggests a distinct-count metric; business meaning must be reviewed.'})
                elif any(h in typ for h in _NUMERIC_HINTS) and sem not in {'code'}:
                    agg='avg' if any(h in lname for h in non_additive_hints) else 'sum'
                    prefix='Average' if agg=='avg' else 'Total'; mid=_slug(f'{agg}_{table}_{name}')
                    mlabel=label if label.lower().startswith(prefix.lower()+' ') else f'{prefix} {label}'
                    additivity='non_additive' if agg=='avg' else 'additive'
                    metrics[mid]={'label':mlabel,'description':f'{prefix} of {db}.{table}.{name}, inferred from numeric metadata and awaiting business review.','synonyms':[mlabel,label,name.replace('_',' ')], 'aggregation':agg,'additivity':additivity,'status':'inferred','entity':cid,'dimensions':[did],'source':'catalog_metadata','preferred_sources':[{'database':db,'table':table,'column':name,'aggregation':agg,'status':'inferred'}]}
                    suggestions.append({'id':f'metric-{workspace_id}-{mid}','object_id':mid,'type':'metric_candidate','label':mlabel,'database':db,'table':table,'column':name,'aggregation':agg,'reason':f'Numeric metadata suggests a {agg} metric; business meaning must be reviewed.'})
                glossary.setdefault(_slug(name),{'preferred':label,'definition':cdesc,'status':'inferred'})
        return {'market':{'id':workspace_id,'name':display_name or _label(workspace_id),'description':'Runtime semantic workspace generated from connected source metadata.','country':'','flag':'◉','currency':'','locale':'','region':None,'data_source':source_id,'source_scope':discovery.get('scope',[]),'status':'draft'},'data_sources':{'default':source_id,'supported':[source_id]},'concepts':concepts,'entities':entities,'dimensions':dimensions,'bindings':bindings,'metrics':metrics,'glossary':glossary,'value_mappings':{},'rules':[],'governed_joins':[],'verified_queries':[],'hierarchies':[],'lineage':[],'trusted_queries':[],'_metric_suggestions':suggestions}

    @staticmethod
    def _snapshot(discovery):
        out={}
        for o in discovery.get('objects',[]) or []:
            db=o.get('database') or o.get('schema') or 'default'; table=o.get('table')
            if table: out[f'{db}.{table}']={c.get('name'):str(c.get('type','')) for c in o.get('columns',[]) or [] if c.get('name')}
        return out
    @staticmethod
    def _drift(old,new):
        events=[]
        for t in sorted(set(new)-set(old)): events.append({'type':'table_added','asset':t})
        for t in sorted(set(old)-set(new)): events.append({'type':'table_removed','asset':t,'severity':'high'})
        for t in sorted(set(old)&set(new)):
            oc,nc=old[t],new[t]
            for c in sorted(set(nc)-set(oc)): events.append({'type':'column_added','asset':f'{t}.{c}'})
            for c in sorted(set(oc)-set(nc)): events.append({'type':'column_removed','asset':f'{t}.{c}','severity':'high'})
            for c in sorted(set(oc)&set(nc)):
                if oc[c]!=nc[c]: events.append({'type':'column_type_changed','asset':f'{t}.{c}','from':oc[c],'to':nc[c],'severity':'high'})
        return events
    @staticmethod
    def _preserve_steward(old,new):
        """Metadata refresh may add inferred objects but never overwrite steward-owned semantics."""
        for key in ('concepts','entities','dimensions','metrics','glossary'):
            target=new.setdefault(key,{})
            for oid,spec in (old.get(key,{}) or {}).items():
                if str((spec or {}).get('status','')).lower() in _STEWARD_STATUSES or str((spec or {}).get('source','')).lower() in {'semantic_studio','manual'}:
                    target[oid]=deepcopy(spec)
        oldb=old.get('bindings',{}) or {}; newb=new.setdefault('bindings',{})
        for bkind in ('concepts','dimensions','dates'):
            for oid,b in (oldb.get(bkind,{}) or {}).items():
                governed=(old.get('dimensions',{}).get(oid) or old.get('concepts',{}).get(oid) or {})
                if str(governed.get('status','')).lower() in _STEWARD_STATUSES: newb.setdefault(bkind,{})[oid]=deepcopy(b)
        for key in ('verified_queries','governed_joins','rules','hierarchies','lineage','trusted_queries'):
            if old.get(key): new[key]=deepcopy(old[key])
        return new

    def _save_ontology(self,workspace_id,source_id,discovery):
        ont=self.repo.ontology(); dd=ont.setdefault('data_dictionary',{})
        # Remove only this workspace's membership. Shared physical assets remain for other workspaces.
        for db in list(dd):
            for table in list(dd[db]):
                info=dd[db][table] or {}; memberships=set(info.get('workspace_ids') or ([info.get('market')] if info.get('market') else [])); memberships.discard(workspace_id)
                if memberships:
                    info['workspace_ids']=sorted(memberships)
                    if len(memberships)==1: info['market']=next(iter(memberships))
                    else: info.pop('market',None)
                else: dd[db].pop(table,None)
            if not dd[db]: dd.pop(db,None)
        table_count=column_count=0; now=datetime.now(timezone.utc).isoformat()
        for obj in discovery.get('objects',[]) or []:
            db=obj.get('database') or obj.get('schema') or 'default'; table=obj.get('table')
            if not table: continue
            cols=[]
            for raw in obj.get('columns',[]) or []:
                name=raw.get('name','')
                if not name or name.lower().startswith(_IGNORE_PREFIX): continue
                cols.append({**raw,'semantic_type':raw.get('semantic_type') or infer_semantic_type(name,raw.get('type','string'),[])}); column_count+=1
            previous=dd.get(db,{}).get(table,{}) or {}; memberships=set(previous.get('workspace_ids') or ([previous.get('market')] if previous.get('market') else [])); memberships.add(workspace_id)
            dd.setdefault(db,{})[table]={'name':table,'description':obj.get('description','') or previous.get('description',''),'location':obj.get('location','') or previous.get('location',''),'columns':cols,'synced_from':source_id,'synced_at':now,'workspace_ids':sorted(memberships),'market':workspace_id if len(memberships)==1 else None,'source_id':source_id}; table_count+=1
        meta=ont.setdefault('ontology',{}); meta.update({'version':'7.0.1','source':'runtime-generated','table_count':sum(len(x) for x in dd.values()),'column_count':sum(len(t.get('columns',[])) for db in dd.values() for t in db.values()),'last_updated':now})
        self.repo.save_ontology(ont); return table_count,column_count

    def bootstrap_source(self,source_id,workspace_id,display_name=None,schemas=None,discover_relationships=True,preserve_existing=True,discovery=None,scope_id=None):
        if source_id not in {x['id'] for x in self.sources.sources()} | {'contoso'}: raise ValueError(f'Unsupported data source: {source_id}')
        discovery=discovery if discovery is not None else self.sources.discover(source_id,schemas); wid=_workspace_id(workspace_id)
        if not discovery.get('objects'): raise ValueError('No tables were discovered. Check connector credentials, database/schema scope and network access.')
        old_record=self.control.get('WORKSPACE',wid) or {}; old_ctx=deepcopy(old_record.get('semantic_context',{})); old_snapshot=old_record.get('catalog_snapshot',{}) or {}
        new_snapshot=self._snapshot(discovery); drift=self._drift(old_snapshot,new_snapshot) if old_snapshot else []
        table_count,column_count=self._save_ontology(wid,source_id,discovery)
        ctx=self._build_context(wid,display_name or (old_ctx.get('market',{}) or {}).get('name') or _label(wid),source_id,discovery); suggestions=ctx.pop('_metric_suggestions',[])
        if preserve_existing and old_ctx: ctx=self._preserve_steward(old_ctx,ctx)
        self.markets.save_workspace(wid,ctx,source_id=source_id,source_scope=discovery.get('scope',[]),status=old_record.get('status','draft'))
        record=self.control.get('WORKSPACE',wid) or {}; record['catalog_snapshot']=new_snapshot; record['schema_drift']=drift; record['last_synced_at']=datetime.now(timezone.utc).isoformat(); self.control.put('WORKSPACE',wid,record)
        for item in suggestions[:500]:
            raw_id=str(item.get('id') or item.get('object_id') or _slug(item.get('label')))
            sid=raw_id if raw_id.startswith(f'metric-{wid}-') else f'metric-{wid}-{raw_id}'
            existing=self.control.get('SUGGESTION',sid)
            payload={**item,'id':sid,'type':'metric_candidate','market':wid,'workspace_id':wid,'status':'inferred','confidence':0.55,'authority':0.35}
            if not existing or existing.get('status') in {'inferred','rejected'}: self.control.put('SUGGESTION',sid,payload)
        if drift:
            self.control.put('SCHEMA_DRIFT',f'{wid}-{int(datetime.now().timestamp())}',{'workspace_id':wid,'market':wid,'events':drift,'status':'open','detected_at':datetime.now(timezone.utc).isoformat()})
        # Explicit discovery scope becomes the shared physical allowlist.
        from app.services.scope_service import ScopeService
        scopes=ScopeService();linked=scope_id or record.get('scope_id')
        if linked:
            scope=scopes.get(linked)
            if scope['workspace_id']!=wid or scope['source_id']!=source_id:raise ValueError('Scope does not belong to this source and workspace')
        else:
            scope=scopes.save({'scope_id':wid+'-scope','workspace_id':wid,'source_id':source_id,
                'tables':[{'database':o.get('database') or o.get('schema') or 'default','schema':o.get('schema') or o.get('database') or '',
                    'catalog':o.get('catalog',''),'table':o['table']} for o in discovery['objects']]})
        scope['status']='generated';scopes.repo.put('SCOPE',scope['scope_id'],scope)
        record.update({'scope_id':scope['scope_id'],'selected_tables':scope['tables'],'scope_version':scope['version']})
        self.control.put('WORKSPACE',wid,record)
        if discover_relationships:
            from app.services.graph_rag_service import GraphRAGService
            rel_result=GraphRAGService().discover_relationship_candidates(wid,min(300,max(50,table_count*8)))
        else:
            from app.services.graph_rag_service import GraphRAGService
            GraphRAGService().build(wid,persist=True); rel_result={'generated':0}
        return {'workspace_id':wid,'display_name':display_name or _label(wid),'data_source':source_id,'tables_scanned':table_count,'columns_scanned':column_count,'metric_suggestions':len(suggestions),'relationship_candidates':rel_result.get('generated',0),'sample_rows_used':False,'generated_files':str(self.s.state_dir/'semantic'/'workspaces'/wid),'schema_drift':drift,'preserved_steward_semantics':bool(old_ctx),'status':old_record.get('status','draft'),'message':'Metadata workspace generated. Review inferred semantics/relationships before certifying production analytics.'}

    def sync_catalog(self,market,databases=None,source_id=None):
        ctx=self.markets.context(market); source_id=source_id or (ctx.get('market',{}) or {}).get('data_source') or (ctx.get('data_sources',{}) or {}).get('default')

        from app.services.scope_service import ScopeService
        selected=ScopeService().sync_workspace(market)
        if selected is not None: return selected
        return self.bootstrap_source(source_id,market,(ctx.get('market',{}) or {}).get('name',market),databases,False,True)
    def discover_relationships(self,market,max_candidates=300):
        from app.services.graph_rag_service import GraphRAGService
        return GraphRAGService().discover_relationship_candidates(market,max_candidates)
