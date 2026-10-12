from __future__ import annotations
import hashlib, json, math
from typing import Any
from app.config import get_settings

class EmbeddingService:
    """Provider-pluggable GraphRAG embeddings: deterministic hash locally, Bedrock in AWS."""
    def __init__(self):
        self.s=get_settings(); self.provider=self.s.embedding_provider; self.model=self.s.embedding_model
        self.dimensions=self.s.embedding_dimensions if self.provider=='bedrock' else self.s.graph_embedding_dimensions
        self._bedrock_client=None

    @property
    def bedrock(self):
        if self._bedrock_client is None:
            import boto3
            self._bedrock_client=boto3.client('bedrock-runtime',region_name=self.s.bedrock_region)
        return self._bedrock_client

    def _hash(self,text:str)->list[float]:
        vec=[0.0]*self.dimensions; toks=[x for x in (text or '').lower().split() if len(x)>1]
        for tok in toks+[f'{a}_{b}' for a,b in zip(toks,toks[1:])]:
            d=hashlib.sha256(tok.encode()).digest(); idx=int.from_bytes(d[:4],'big')%self.dimensions; vec[idx]+=1.35 if '_' in tok else (1 if d[4]%2==0 else -1)
        norm=math.sqrt(sum(x*x for x in vec)) or 1.0
        return [round(x/norm,6) for x in vec]

    def _bedrock_embed(self,text:str)->list[float]:
        body={'inputText':text or '', 'normalize':self.s.embedding_normalize}
        if self.s.embedding_dimensions: body['dimensions']=self.s.embedding_dimensions
        r=self.bedrock.invoke_model(modelId=self.model,accept='application/json',contentType='application/json',body=json.dumps(body))
        obj=json.loads(r['body'].read().decode()); vec=obj.get('embedding') or obj.get('vector')
        if not vec: raise RuntimeError('Embedding provider returned no vector')
        vec=[float(x) for x in vec]; norm=math.sqrt(sum(x*x for x in vec)) or 1.0
        return [round(x/norm,6) for x in vec]

    def embed(self,text:str)->list[float]:
        if self.provider=='bedrock':
            try: return self._bedrock_embed(text)
            except Exception:
                if not self.s.embedding_fallback: raise
        return self._hash(text)

    def metadata(self)->dict[str,Any]:
        return {'provider':self.provider,'model':self.model if self.provider!='hash' else 'deterministic-hash-v2','dimensions':self.dimensions,'fallback_enabled':self.s.embedding_fallback,'fallback_provider':'hash'}
