"""Bedrock permission-aware model catalog and explicit task routing.
A listed model is NEVER marked invokable before a real Converse permission probe.
"""
from __future__ import annotations
from datetime import datetime,timezone
from app.config import get_settings
from app.repositories.control_repository import ControlRepository

TASKS=('semantic_verification','ontology','semantic_planning','ask','summaries','classification','sme_questions')
STRATEGIES=('balanced','quality','cost','latency')

class BedrockModelService:
    def __init__(self): self.s=get_settings();self.repo=ControlRepository()
    def _client(self,service):
        import boto3
        return boto3.client(service,region_name=self.s.bedrock_region)
    def discover(self):
        try:
            bedrock=self._client('bedrock')
            warnings=[]
            try:base=bedrock.list_foundation_models().get('modelSummaries',[])
            except Exception as e:base=[];warnings.append('Foundation-model listing failed: '+str(e)[:150])
            profiles=[];cursor=None
            try:
                while True:
                    req={'maxResults':100}
                    if cursor:req['nextToken']=cursor
                    out=bedrock.list_inference_profiles(**req)
                    profiles+=out.get('inferenceProfileSummaries',[])
                    cursor=out.get('nextToken')
                    if not cursor:break
            except Exception as e:warnings.append('Inference-profile listing failed: '+str(e)[:150])
            rows={}
            for m in base:
                # This selector is specifically for conversational text LLMs, not image/embedding models.
                if m.get('inputModalities') and 'TEXT' not in m['inputModalities']:continue
                if m.get('outputModalities') and 'TEXT' not in m['outputModalities']:continue
                mid=m.get('modelId')
                if mid:rows[mid]={'id':mid,'label':m.get('modelName') or mid,'provider':m.get('providerName') or 'Unknown','kind':'foundation','inference_types':m.get('inferenceTypesSupported') or [],'status':'unverified','probe_supported':True}
            for m in profiles:
                mid=m.get('inferenceProfileId') or m.get('inferenceProfileArn')
                if mid:rows[mid]={'id':mid,'label':m.get('inferenceProfileName') or mid,'provider':'Profile','kind':'inference_profile','inference_types':['PROFILE'],'underlying_models':[x.get('modelArn') for x in m.get('models',[])], 'status':'unverified','probe_supported':True}
            for k,m in rows.items():
                probe=self.repo.get('MODEL_PROBE',k)
                if probe:m['status']=probe['status'];m['last_checked_at']=probe.get('checked_at')
            result={'region':self.s.bedrock_region,'models':list(rows.values()),'models_found':len(rows),'status':'partial' if warnings and rows else 'error' if warnings else 'discovered','warning':'A listed model does not prove invocation permission. Probe a model before use. '+(' '.join(warnings))}
            # Keep a small snapshot for runtime routing; production store is not a large-model-cache DB.
            self.repo.put('MODEL_DISCOVERY','latest',{'region':result['region'],'models':[{'id':m['id'],'label':m['label'],'kind':m['kind']} for m in result['models'][:100]]})
            return result
        except Exception as e:
            return {'region':self.s.bedrock_region,'models':[],'models_found':0,'status':'error','warning':str(e)[:300]}

    def probe(self,model_id):
        found={m['id']:m for m in self.discover()['models']}
        if model_id not in found:raise ValueError('Only listed Bedrock models/inference profiles can be probed')
        # Explicit on-demand API call incurs a very small cost; DO NOT probe all models automatically.
        try:
            reply=self._client('bedrock-runtime').converse(modelId=model_id,messages=[{'role':'user','content':[{'text':'Reply OK.'}]}],inferenceConfig={'maxTokens':8,'temperature':0})
            status='verified'
            detail='Converse invocation succeeded.'
        except Exception as e:
            status='blocked' if any(z in str(e).lower() for z in ('accessdenied','not authorized','access denied')) else 'error'
            detail=str(e)[:280]
        self.repo.put('MODEL_PROBE',model_id,{'id':model_id,'status':status,'checked_at':datetime.now(timezone.utc).isoformat(),'detail':detail})
        return {'model_id':model_id,'status':status,'detail':detail}

    @staticmethod
    def _rank(m,task,strategy):
        label=(m['id']+' '+m['label']).lower()
        if 'embedding' in label or 'embed' in label or 'rerank' in label:return -100
        if 'sonnet' in label or 'opus' in label or 'nova-pro' in label:return {'quality':90,'balanced':70,'cost':35,'latency':35}[strategy]
        if 'haiku' in label or 'nova-lite' in label or 'nova-micro' in label:return {'quality':50,'balanced':75,'cost':95,'latency':95}[strategy]
        return 55

    def overview(self):
        d=self.discover()
        return {**d,'configuration':self.config(),'recommendation':self.recommend(d['models'])}
    def config(self):
        return self.repo.get('MODEL_CONFIG','default') or {'strategy':'balanced','task_models':{},'pinned':False}
    def recommend(self,models=None):
        all_models=(models if models is not None else self.discover()['models'])
        cfg=self.config();strategy=cfg.get('strategy','balanced')
        # Verified models preferred; unverified ones merely recommendations to test, not usable permission guarantees.
        eligible=[m for m in all_models if m.get('status') not in {'blocked','error'}]
        verified=[m for m in eligible if m['status']=='verified']
        choices=verified or eligible
        result={}
        for task in TASKS:
            chosen=sorted(choices,key=lambda m:(self._rank(m,task,strategy),m['kind']=='inference_profile'),reverse=True)
            result[task]={'model_id':chosen[0]['id'] if chosen else None,'status':chosen[0]['status'] if chosen else 'none','reason':'Heuristic fit for task, strategy, and permission-probe status; not an accuracy benchmark.'}
        return {'strategy':strategy,'recommendations':result,'method':'heuristic_not_benchmarked'}
    def save(self,config):
        strategy=config.get('strategy','balanced')
        if strategy not in STRATEGIES:raise ValueError('Invalid strategy')
        selected=config.get('task_models') or {}
        if not isinstance(selected,dict) or any(task not in TASKS for task in selected):raise ValueError('Invalid task name')
        candidates={m['id']:m for m in self.discover()['models']}
        for task,mid in selected.items():
            if mid and mid not in candidates:raise ValueError(f'Unknown model for {task}')
            if mid and candidates[mid]['status']!='verified':raise ValueError(f'Run Test access and obtain VERIFIED permission before selecting model: {mid}')
        return self.repo.put('MODEL_CONFIG','default',{'strategy':strategy,'task_models':selected,'pinned':bool(config.get('pinned',False))})
    def chosen_model(self,task='ask'):
        config=self.config();manual=config.get('task_models',{}).get(task)
        if task=='semantic_verification' and not manual:manual=config.get('task_models',{}).get('semantic_planning')
        if manual:return manual
        # Runtime must not call ListFoundationModels / ListInferenceProfiles on every LLM invocation.
        cached=self.repo.get('MODEL_DISCOVERY','latest') or {}
        verified=[{**m,'status':'verified'} for m in cached.get('models',[]) if (self.repo.get('MODEL_PROBE',m['id']) or {}).get('status')=='verified']
        if verified:return self.recommend(verified)['recommendations'].get(task,{}).get('model_id') or self.s.bedrock_model
        return self.s.bedrock_model
