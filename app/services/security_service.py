from __future__ import annotations
import base64, fnmatch, json, math, re, time, urllib.request
from dataclasses import dataclass
from functools import lru_cache
from fastapi import Request
from app.config import get_settings
from app.services.market_service import MarketService

@dataclass
class UserContext:
    user_id: str
    roles: tuple[str,...]
    claims: dict
    def has_any(self,roles)->bool: return bool(set(self.roles)&set(roles or []))

class SecurityService:
    def __init__(self): self.s=get_settings(); self.markets=MarketService()
    @staticmethod
    def _b64(data): return base64.urlsafe_b64decode(data+'='*(-len(data)%4))
    @lru_cache(maxsize=32)
    def _alb_public_key(self,kid:str)->bytes:
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', kid):
            raise PermissionError('Invalid ALB key identifier.')
        url=self.s.alb_jwt_public_key_url_template.format(region=self.s.aws_region,kid=kid)
        with urllib.request.urlopen(url,timeout=5) as r: return r.read()
    def verify_alb_oidc(self,token:str)->dict:
        try:
            h,p,s=token.split('.'); header=json.loads(self._b64(h)); claims=json.loads(self._b64(p)); sig=self._b64(s)
        except Exception as e: raise PermissionError('Malformed ALB OIDC token.') from e
        if header.get('alg')!='ES256' or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',str(header.get('kid',''))): raise PermissionError('Unsupported ALB OIDC token algorithm or key identifier.')
        signer=header.get('signer') or claims.get('signer') or ''
        if self.s.alb_expected_signer_arn and signer!=self.s.alb_expected_signer_arn: raise PermissionError('ALB OIDC signer mismatch.')
        if self.s.alb_expected_client_id and header.get('client')!=self.s.alb_expected_client_id: raise PermissionError('ALB OIDC client mismatch.')
        try: expiry=float(claims.get('exp',0) or 0)
        except (TypeError, ValueError): raise PermissionError('Invalid ALB OIDC expiration.') from None
        if not math.isfinite(expiry) or expiry<=time.time(): raise PermissionError('ALB OIDC token expired or invalid.')
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            key=serialization.load_pem_public_key(self._alb_public_key(header['kid']))
            # JWT uses IEEE-P1363 r||s while cryptography verifies DER ECDSA.
            if len(sig)!=64: raise PermissionError('Invalid ES256 signature length.')
            from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
            der=encode_dss_signature(int.from_bytes(sig[:32],'big'),int.from_bytes(sig[32:],'big'))
            key.verify(der,f'{h}.{p}'.encode(),ec.ECDSA(hashes.SHA256()))
        except PermissionError: raise
        except Exception as e: raise PermissionError('ALB OIDC signature verification failed.') from e
        return claims
    def context_from_request(self,request:Request)->UserContext:
        if self.s.auth_mode=='alb_oidc':
            token=request.headers.get('x-amzn-oidc-data')
            uid_header=request.headers.get('x-amzn-oidc-identity')
            if not token or not uid_header: raise PermissionError('Authenticated ALB/OIDC headers are required.')
            claims=self.verify_alb_oidc(token); uid=str(claims.get('sub') or '')
            if not uid or uid != uid_header: raise PermissionError('ALB identity does not match signed identity.')
            role_value=claims.get(self.s.identity_role_claim,[]) or []
            if isinstance(role_value,str): roles=tuple(x.strip() for x in role_value.split(',') if x.strip())
            else: roles=tuple(str(x) for x in role_value if x)
            if not roles: roles=self.s.default_roles
            claims={**claims,'workspace':claims.get('workspace') or claims.get('market','')}
            return UserContext(uid,roles,claims)
        if self.s.is_production:
            raise PermissionError('Development identity fallback is prohibited in production.')
        uid=(request.headers.get('x-user') if self.s.allow_dev_identity_headers else None) or 'authenticated-user'
        raw_roles=request.headers.get('x-roles',','.join(self.s.default_roles)) if self.s.allow_dev_identity_headers else request.headers.get(self.s.trusted_roles_header,','.join(self.s.default_roles))
        roles=tuple(x.strip() for x in raw_roles.split(',') if x.strip())
        return UserContext(uid,roles,{'workspace':request.headers.get('x-workspace') or request.headers.get('x-market','')})
    def policies(self,market): return self.markets.context(market).get('security',{}) or {}
    def is_admin(self,user): return user.has_any(self.s.admin_roles)
    def workspace_allowed(self,user,workspace):
        claim=user.claims.get('workspace','') if user.claims else ''
        return not claim or claim==workspace or self.is_admin(user)
    def can(self,user,permission,market):
        if not self.workspace_allowed(user,market): return False
        if not self.s.security_enabled or self.is_admin(user): return True
        role_perms=self.policies(market).get('role_permissions',{}) or {}
        return any(permission in (role_perms.get(r,[]) or []) or '*' in (role_perms.get(r,[]) or []) for r in user.roles)
    def denied_columns(self,user,market):
        if not self.s.security_enabled or self.is_admin(user): return []
        denied=[]
        for rule in self.policies(market).get('column_policies',[]) or []:
            if not user.has_any(rule.get('roles',[]) or []): denied.extend(rule.get('columns',[]) or [])
        return denied
    def column_allowed(self,user,market,database,table,column):
        full=f'{database}.{table}.{column}'; return self.workspace_allowed(user,market) and not any(fnmatch.fnmatch(full,p) or fnmatch.fnmatch(column,p) for p in self.denied_columns(user,market))
    def relationship_allowed(self,user,market,rel): return self.column_allowed(user,market,rel.get('from_db',''),rel.get('from_table',''),rel.get('from_column','')) and self.column_allowed(user,market,rel.get('to_db',''),rel.get('to_table',''),rel.get('to_column',''))
    def filter_ontology(self,ontology,user,market):
        if not self.s.security_enabled or self.is_admin(user): return ontology
        import copy; out=copy.deepcopy(ontology); dd=out.get('data_dictionary',{}) or {}
        for db,tables in dd.items():
            for table,info in tables.items(): info['columns']=[c for c in (info.get('columns',[]) or []) if self.column_allowed(user,market,db,table,c.get('name',''))]
        return out
    def filter_graph_results(self,results,user,market):
        if not self.s.security_enabled or self.is_admin(user): return results
        return [x for x in results if x.get('node_type')!='column' or self.column_allowed(user,market,(x.get('attributes') or {}).get('database',''),(x.get('attributes') or {}).get('table',''),(x.get('attributes') or {}).get('column',''))]
    def filter_graph_payload(self,payload,user,market):
        if not self.s.security_enabled or self.is_admin(user): return payload
        nodes=payload.get('nodes',{}); iterable=[(x.get('id'),x) for x in nodes] if isinstance(nodes,list) else list(nodes.items())
        allowed={nid for nid,node in iterable if node.get('node_type')!='column' or self.column_allowed(user,market,(node.get('attributes') or {}).get('database',''),(node.get('attributes') or {}).get('table',''),(node.get('attributes') or {}).get('column',''))}
        out=dict(payload); out['nodes']=[node for nid,node in iterable if nid in allowed] if isinstance(nodes,list) else {nid:node for nid,node in iterable if nid in allowed}; out['edges']=[e for e in payload.get('edges',[]) if e.get('source_id') in allowed and e.get('target_id') in allowed]; return out
    def row_predicates(self,user,market):
        if not self.s.security_enabled or self.is_admin(user): return []
        return [r for r in self.policies(market).get('row_policies',[]) or [] if not (r.get('roles',[]) or []) or user.has_any(r.get('roles',[]) or [])]
    def enforce_sql(self,sql,user,market):
        if not self.workspace_allowed(user,market): return False,'Workspace access denied.'
        if not self.s.security_enabled or self.is_admin(user): return True,'Security policy passed.'
        low=sql.lower()
        for pattern in self.denied_columns(user,market):
            col=pattern.split('.')[-1].replace('*','').lower()
            if col and re.search(rf'(?<![a-z0-9_]){re.escape(col)}(?![a-z0-9_])',low): return False,f'Column policy blocks access to {pattern} for roles {", ".join(user.roles)}.'
        return True,'Security policy passed.'
    def summary(self,user,market): return {'user_id':user.user_id,'roles':list(user.roles),'is_admin':self.is_admin(user),'workspace_allowed':self.workspace_allowed(user,market),'auth_mode':self.s.auth_mode,'denied_columns':self.denied_columns(user,market),'permissions':{p:self.can(user,p,market) for p in ['query','semantic_review','publish','execute_action','manage_branch','pii_access']}}
