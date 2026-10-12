from __future__ import annotations
import json, uuid
from datetime import datetime, timezone
from app.config import get_settings
from app.repositories.control_repository import ControlRepository
from app.services.market_service import MarketService
from app.services.security_service import SecurityService, UserContext

class ActionService:
    def __init__(self): self.s=get_settings(); self.repo=ControlRepository(); self.markets=MarketService(); self.security=SecurityService()
    def definitions(self,market): return self.markets.context(market).get('actions',[]) or []
    def execute(self,action_id,market,parameters,user:UserContext,dry_run=False):
        spec=next((x for x in self.definitions(market) if x.get('id')==action_id),None)
        if not spec: raise KeyError(action_id)
        if not self.security.can(user,'execute_action',market): raise PermissionError('Action execution permission denied.')
        required=spec.get('roles',[]) or []
        if required and not user.has_any(required) and not self.security.is_admin(user): raise PermissionError('Action is not permitted for the current role.')
        missing=[p.get('name') for p in spec.get('parameters',[]) or [] if p.get('required',True) and p.get('name') not in parameters]
        if missing: raise ValueError('Missing parameters: '+', '.join(missing))
        now=datetime.now(timezone.utc).isoformat(); aid='action-'+uuid.uuid4().hex[:10]
        result={'action_event_id':aid,'action_id':action_id,'market':market,'parameters':parameters,'status':'dry_run' if dry_run else 'completed','user_id':user.user_id,'created_at':now,'handler':spec.get('handler','audit_only')}
        if not dry_run and spec.get('handler')=='lambda':
            if not self.s.is_aws or not self.s.action_lambda_arn: raise RuntimeError('ACTION_LAMBDA_ARN is required for Lambda-backed actions.')
            import boto3
            client=boto3.client('lambda',region_name=self.s.aws_region)
            r=client.invoke(FunctionName=self.s.action_lambda_arn,InvocationType='RequestResponse',Payload=json.dumps({'action':spec,'parameters':parameters,'user':user.user_id}).encode())
            result['lambda_status']=r.get('StatusCode'); result['response']=json.loads(r['Payload'].read().decode() or '{}')
        self.repo.put('ACTION',aid,result); self.repo.put('AUDIT','audit-'+uuid.uuid4().hex[:12],{'event':'action.execute','actor':user.user_id,'roles':list(user.roles),'resource':action_id,'payload':{'dry_run':dry_run,'parameters':parameters},'created_at':now})
        return result
    def history(self,limit=100): return self.repo.list('ACTION',limit)
