from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]

def test_readme_explains_three_s3_purposes():
    s=(ROOT/'README.md').read_text()
    assert 'Actual business data' in s
    assert 'Athena query results' in s
    assert 'Platform semantic artifacts' in s
    assert 'ATHENA_OUTPUT=s3://' in s

def test_production_env_has_no_default_customer_workspace():
    for name in ['.env.windows.test.example','.env.windows.production.example']:
        s=(ROOT/name).read_text().lower()
        assert 'default_market=' in s
        assert 'allow_sample_values=false' in s

def test_windows_native_launcher_and_service_task_exist():
    start=(ROOT/'windows/Start-App.ps1').read_text()
    task=(ROOT/'windows/Install-StartupTask.ps1').read_text()
    assert 'uvicorn' in start and '0.0.0.0' in start
    assert 'New-ScheduledTaskTrigger -AtStartup' in task
    assert 'SYSTEM' in task

def test_instance_role_includes_source_data_and_athena_results():
    d=json.loads((ROOT/'infra/windows/ec2-instance-role-policy.json').read_text())
    sids={x['Sid'] for x in d['Statement']}
    assert {'SourceDataRead','AthenaResults','GlueRead','AthenaReadExecute'} <= sids

def test_no_runtime_country_specific_files():
    market_root=ROOT/'data/semantic/markets'
    assert not market_root.exists() or not list(market_root.rglob('*.yaml'))
    assert 'runtime-generated' in (ROOT/'data/seed/ontology.json').read_text()

def test_embedding_service_has_distinct_client_and_embed_method():
    s=(ROOT/'app/services/embedding_service.py').read_text()
    assert '_bedrock_client' in s and 'def _bedrock_embed' in s
