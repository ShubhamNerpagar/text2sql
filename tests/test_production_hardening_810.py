"""Security regression tests for production readiness (no AWS credentials needed)."""
import base64
import json
import time
from dataclasses import replace
from importlib import import_module
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from app.config import Settings, production_configuration_errors, validate_production_config
from app.services.security_service import SecurityService


def production_settings():
    return replace(Settings(), job_queue_backend='dynamodb', aws_region='ap-south-1', app_env='production', app_mode='aws', auth_mode='alb_oidc',
                   security_enabled=True,allow_dev_identity_headers=False,
                   alb_expected_signer_arn='arn:aws:elasticloadbalancing:ap-south-1:123456789012:loadbalancer/app/test/abc',
                   alb_expected_client_id='oidc-client-id',cors_origins=('https://analytics.example.com',),
                   allow_sample_values=False,enable_sample_execution=False,allow_inferred_analytics=False,
                   semantic_bucket='semantic-bucket',learning_table='learning-control',
                   persist_local_state=False,default_data_source='athena',athena_output='s3://analytics-results/dip/')


def test_preflight_rejects_insecure_profiles():
    valid=production_settings()
    assert production_configuration_errors(valid)==[]
    validate_production_config(valid)
    for override in [dict(security_enabled=False),dict(auth_mode='dev_headers'),
                     dict(allow_dev_identity_headers=True),dict(alb_expected_signer_arn=''),
                     dict(alb_expected_client_id=''),dict(cors_origins=('*',)),
                     dict(allow_sample_values=True),dict(allow_inferred_analytics=True),
                     dict(semantic_bucket='<NAME>'),dict(persist_local_state=True),
                     dict(job_queue_backend='sqlite'),dict(aws_region='eu-west-1'),
                     dict(alb_jwt_public_key_url_template='https://evil.example/{kid}')]:
        bad=replace(valid,**override)
        assert production_configuration_errors(bad),override
        with pytest.raises(RuntimeError,match='Production configuration rejected'):
            validate_production_config(bad)


def test_header_forgery_and_unsigned_requests_denied_by_perimeter(monkeypatch):
    main=import_module('app.main')
    prod=production_settings()
    monkeypatch.setattr(main,'s',prod)
    monkeypatch.setattr(main.security_service,'s',prod)
    c=TestClient(main.app)
    if True:
        ok=c.get('/api/health')
        assert ok.status_code==200 and ok.json()['version']=='8.5.0'
        denied=c.get('/api/markets',headers={'x-user':'fake','x-roles':'admin'})
        assert denied.status_code==401
        assert 'no-store'==denied.headers['cache-control']
        assert c.post('/mcp',json={'jsonrpc':'2.0','method':'initialize','id':1}).status_code==401
        assert c.get('/').status_code==200
        assert c.get('/api/health').headers['x-content-type-options']=='nosniff'
        assert 'frame-ancestors' in c.get('/').headers['content-security-policy']


def test_oidc_key_id_and_signed_claim_validation():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key=ec.generate_private_key(ec.SECP256R1())
    pub=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    s=SecurityService();s.s=production_settings();s._alb_public_key=lambda kid:pub
    enc=lambda b:base64.urlsafe_b64encode(b).decode().rstrip('=')
    def signed(header):
        h=enc(json.dumps(header).encode());p=enc(json.dumps({'sub':'sub-1','exp':int(time.time())+180}).encode())
        der=key.sign(f'{h}.{p}'.encode(),ec.ECDSA(hashes.SHA256()))
        r,t=decode_dss_signature(der)
        return f'{h}.{p}.{enc(r.to_bytes(32,"big")+t.to_bytes(32,"big"))}'
    base={'alg':'ES256','kid':'abcd-123','signer':s.s.alb_expected_signer_arn,'client':s.s.alb_expected_client_id}
    assert s.verify_alb_oidc(signed(base))['sub']=='sub-1'
    for change in [{'client':'other'}, {'client':None}, {'kid':'../bad'}, {'signer':'wrong'}]:
        with pytest.raises(PermissionError):s.verify_alb_oidc(signed({**base,**change}))


def test_sensitive_catalog_cross_workspace_rejected():
    main=import_module('app.main')
    c=TestClient(main.app)
    res=c.get('/api/catalog/tables?market=test-lab',headers={'x-user':'analyst','x-roles':'analyst','x-workspace':'unrelated-lab'})
    assert res.status_code==403
    res=c.get('/api/lineage?market=test-lab',headers={'x-user':'analyst','x-roles':'analyst','x-workspace':'unrelated-lab'})
    assert res.status_code==403


def test_synthetic_source_health_is_reported_healthy():
    from app.services.data_source_service import DataSourceService
    response=DataSourceService().health()
    row=next(row for row in response['sources'] if row['id']=='contoso')
    assert row['status']=='healthy'


def test_report_ids_do_not_bypass_workspace_scope():
    from app.services.report_service import ReportService
    from app.services.security_service import UserContext
    svc=ReportService()
    owner=UserContext('report-owner',('semantic_admin',),{'workspace':'test-lab'})
    record=svc.create('test-lab','Workspace private','',owner)
    other=UserContext('report-owner',('analyst',),{'workspace':'another-workspace'})
    assert not svc._can_read(record,other)
    assert not svc._can_edit(record,other)
    with pytest.raises(PermissionError):svc.get(record['report_id'],other)
    with pytest.raises(PermissionError):svc.list('test-lab',other)

def test_external_origin_cannot_mutate_with_alb_browser_cookies(monkeypatch):
    main=import_module('app.main')
    prod=production_settings()
    monkeypatch.setattr(main,'s',prod)
    monkeypatch.setattr(main.security_service,'s',prod)
    c=TestClient(main.app)
    assert c.post('/api/query/features',headers={'Origin':'https://other.example.org'},json={'question':'orders'}).status_code==403
    assert c.post('/api/query/features',headers={'Sec-Fetch-Site':'cross-site'},json={'question':'orders'}).status_code==403

def test_monitor_denied_to_non_admin_in_production(monkeypatch):
    routes=import_module('app.api.routes')
    original=routes.security.context_from_request
    prod=production_settings()
    monkeypatch.setattr(routes,'user_ctx',lambda req: __import__('app.services.security_service',fromlist=['UserContext']).UserContext('u',('analyst',),{'workspace':'test-lab'}))
    monkeypatch.setattr(routes,'get_settings',lambda : prod)
    with pytest.raises(__import__('fastapi').HTTPException) as info:routes.monitor_summary(SimpleNamespace())
    assert info.value.status_code==403


def test_misspelled_production_profile_must_not_enable_development_auth():
    with pytest.raises(RuntimeError,match='APP_ENV must be'):
        validate_production_config(replace(Settings(),app_env='prod'))
    with pytest.raises(RuntimeError,match='APP_MODE must be'):
        validate_production_config(replace(Settings(),app_mode='warehouse'))
