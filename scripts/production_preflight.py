r"""Fail-closed deployment checks: offline configuration plus optional live AWS validation.

Windows use: .\windows\Load-Env.ps1, then python scripts\production_preflight.py
Always keep the EC2 origin restricted to the authenticated ALB security group.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings, production_configuration_errors


def live_aws_checks(s: Settings) -> list[dict]:
    checks=[]
    def check(name,func):
        try:
            detail=func()
            checks.append({'name':name,'ok':True,'detail':str(detail)[:250]})
        except Exception as exc:
            checks.append({'name':name,'ok':False,'detail':f'{type(exc).__name__}: {str(exc)[:250]}'})
    try:
        import boto3
    except ImportError:
        return [{'name':'boto3_installed','ok':False,'detail':'Install requirements-windows.txt'}]
    session=boto3.Session(region_name=s.aws_region)
    check('sts_identity',lambda: session.client('sts').get_caller_identity()['Arn'])
    if s.semantic_bucket:
        check('semantic_s3_bucket_access',lambda: session.client('s3').head_bucket(Bucket=s.semantic_bucket)['ResponseMetadata']['HTTPStatusCode'])
    if s.learning_table:
        check('dynamodb_table_access',lambda: session.client('dynamodb').describe_table(TableName=s.learning_table)['Table']['TableStatus'])
    if s.default_data_source=='athena':
        check('athena_workgroup_access',lambda: session.client('athena').get_work_group(WorkGroup=s.athena_workgroup)['WorkGroup']['State'])
    # Live warehouse SQL equivalence, Bedrock InvokeModel, ALB ingress and worker
    # failover must be tested against the actual account in separate acceptance.
    return checks


def main(argv=None)->int:
    p=argparse.ArgumentParser()
    p.add_argument('--require-production',action='store_true')
    p.add_argument('--check-aws',action='store_true')
    p.add_argument('--json',action='store_true')
    args=p.parse_args(argv)
    s=Settings()
    issues=production_configuration_errors(s)
    if s.app_env not in {'development','test','production'}:
        issues.append('APP_ENV must be development, test, or production (no aliases)')
    if s.app_mode not in {'local','aws'}:
        issues.append('APP_MODE must be local or aws')
    if args.require_production and not s.is_production:
        issues.append('APP_ENV must equal production')
    checks=live_aws_checks(s) if args.check_aws and not issues else []
    result={'pass':not issues and all(x['ok'] for x in checks),'environment':s.app_env,'mode':s.app_mode,'configuration_issues':issues,'live_aws_checks':checks,'notice':'Live ALB/OIDC, external warehouses, Windows EC2 and cross-host failover require on-environment acceptance.'}
    if args.json:
        print(json.dumps(result,indent=2))
    else:
        print(('PASS' if result['pass'] else 'BLOCKED')+' — production preflight')
        for issue in issues:print('  BLOCKER:',issue)
        for chk in checks: print(' ',('PASS' if chk['ok'] else 'FAIL'),chk['name'],chk['detail'])
        print(result['notice'])
    return 0 if result['pass'] else 2

if __name__=='__main__': raise SystemExit(main())
