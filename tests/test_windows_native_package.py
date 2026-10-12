from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]

def test_windows_native_has_no_docker_runtime_artifacts():
    assert not (ROOT/'Dockerfile').exists()
    assert not (ROOT/'docker-compose.yml').exists()
    assert not (ROOT/'.dockerignore').exists()

def test_windows_native_scripts_present():
    required=['Install-App.ps1','Load-Env.ps1','Start-App.ps1','Test-App.ps1','Test-Aws.ps1','Run-Tests.ps1','Open-Firewall.ps1','Install-StartupTask.ps1','Uninstall-StartupTask.ps1','Install-ReportWorkerTask.ps1','Uninstall-ReportWorkerTask.ps1','Run-ReportWorker.ps1']
    for name in required:
        assert (ROOT/'windows'/name).exists(), name

def test_windows_env_template_is_test_safe():
    text=(ROOT/'.env.windows.test.example').read_text()
    assert 'APP_MODE=aws' in text
    assert 'PERSIST_LOCAL_STATE=true' in text
    assert 'ALLOW_SAMPLE_VALUES=false' in text
    assert 'AUTH_MODE=dev_headers' in text
    assert 'EMBEDDING_PROVIDER=hash' in text
    assert 'AWS_ACCESS_KEY_ID' not in text
    assert 'AWS_SECRET_ACCESS_KEY' not in text

def test_windows_iam_policy_has_athena_glue_and_source_s3():
    p=json.loads((ROOT/'infra/windows/ec2-instance-role-policy.json').read_text())
    actions={a for s in p['Statement'] for a in s.get('Action',[])}
    assert 'glue:GetTables' in actions
    assert 'athena:StartQueryExecution' in actions
    assert 's3:GetObject' in actions

def test_windows_readme_explains_three_s3_paths_and_security_group():
    s=(ROOT/'WINDOWS_EC2_README.md').read_text()
    assert 'Actual business data' in s
    assert 'Athena query results' in s
    assert 'Platform semantic artifacts' in s
    assert 'Security Group' in s
    assert '0.0.0.0/0' in s

def test_windows_ci_uses_windows_runner_and_native_uvicorn():
    s=(ROOT/'.github/workflows/windows-native.yml').read_text()
    assert 'windows-latest' in s
    assert 'uvicorn' in s
    assert 'pytest' in s
    assert 'docker build' not in s
