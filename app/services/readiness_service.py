from __future__ import annotations
from app.config import get_settings, production_configuration_errors
from app.services.data_source_service import DataSourceService
from app.services.market_service import MarketService

class ReadinessService:
    def __init__(self): self.s=get_settings(); self.sources=DataSourceService(); self.workspaces=MarketService()
    def report(self):
        workspaces=self.workspaces.list_workspaces(); configured=self.sources.configured_ids(); checks=[]
        def add(name,ok,detail,required=True): checks.append({'name':name,'ok':bool(ok),'required':required,'detail':detail})
        add('data_source_configured',bool(configured),f"Configured sources: {', '.join(configured) if configured else 'none'}")
        add('semantic_workspace_generated',bool(workspaces),f'Runtime workspaces: {len(workspaces)}')
        add('security_enabled',self.s.security_enabled,'SECURITY_ENABLED must remain true in production.')
        add('production_configuration_gate',not production_configuration_errors(self.s),'; '.join(production_configuration_errors(self.s)) or 'Validated configuration; live security acceptance still required.',self.s.is_production)
        add('dev_identity_headers_disabled',not self.s.allow_dev_identity_headers,'ALLOW_DEV_IDENTITY_HEADERS=false is required in production.',self.s.is_production)
        add('production_auth_mode',self.s.auth_mode in {'alb_oidc'},f'AUTH_MODE={self.s.auth_mode}; production uses alb_oidc.',self.s.is_production)
        add('alb_signer_pinned',bool(self.s.alb_expected_signer_arn),'ALB_EXPECTED_SIGNER_ARN pins the trusted load balancer.',self.s.is_production and self.s.auth_mode=='alb_oidc')
        add('cors_restricted','*' not in self.s.cors_origins,f"CORS_ORIGINS={','.join(self.s.cors_origins)}",self.s.is_production)
        add('sample_values_disabled',not self.s.allow_sample_values,'ALLOW_SAMPLE_VALUES=false preserves metadata-only onboarding.',True)
        if self.s.is_aws:
            if self.s.default_data_source=='athena' or self.s.athena_output: add('athena_results_s3',self.s.athena_output.startswith('s3://'),'ATHENA_OUTPUT must be an s3:// URI when Athena is used.')
            durable_required=self.s.is_production or not self.s.persist_local_state
            add('semantic_bucket',bool(self.s.semantic_bucket),'SEMANTIC_BUCKET persists ontology/workspaces/graphs across machine replacement.',durable_required)
            add('durable_control_plane',bool(self.s.learning_table),'LEARNING_TABLE enables durable conversations, reports, audit and workspace registry.',durable_required)
            add('ephemeral_local_state',not self.s.persist_local_state,'PERSIST_LOCAL_STATE=false is recommended for stateless production deployments.',self.s.is_production)
            add('otel_enabled',self.s.otel_enabled,'OTEL_ENABLED=true recommended/required for production observability.',self.s.is_production)
        required=[x for x in checks if x['required']]
        return {'ready':all(x['ok'] for x in required),'production_certified':False,'acceptance_required':self.s.is_production,'environment':self.s.app_env,'mode':self.s.app_mode,'auth_mode':self.s.auth_mode,'checks':checks,'workspaces':workspaces,'configured_sources':configured}
