#!/usr/bin/env python3
"""Non-destructive verification of production backup/DR safeguards."""
from __future__ import annotations
import json, os, sys
import boto3

region=os.getenv('AWS_REGION','eu-west-1'); bucket=os.getenv('SEMANTIC_BUCKET',''); table=os.getenv('LEARNING_TABLE','')
rows=[]
def add(name,ok,detail): rows.append({'name':name,'ok':bool(ok),'detail':detail})
if bucket:
    try:
        s3=boto3.client('s3',region_name=region); v=s3.get_bucket_versioning(Bucket=bucket).get('Status'); add('s3_versioning',v=='Enabled',v or 'disabled')
        enc=s3.get_bucket_encryption(Bucket=bucket); add('s3_encryption',bool(enc.get('ServerSideEncryptionConfiguration',{}).get('Rules')),'configured')
        pab=s3.get_public_access_block(Bucket=bucket)['PublicAccessBlockConfiguration']; add('s3_public_access_block',all(bool(pab.get(k)) for k in ['BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets']),pab)
    except Exception as e: add('s3_safeguards',False,f'{type(e).__name__}: {e}')
else: add('s3_configured',False,'SEMANTIC_BUCKET unset')
if table:
    try:
        ddb=boto3.client('dynamodb',region_name=region); p=ddb.describe_continuous_backups(TableName=table)['ContinuousBackupsDescription']['PointInTimeRecoveryDescription']['PointInTimeRecoveryStatus']; add('dynamodb_pitr',p=='ENABLED',p)
    except Exception as e: add('dynamodb_pitr',False,f'{type(e).__name__}: {e}')
else: add('dynamodb_configured',False,'LEARNING_TABLE unset')
print(json.dumps({'ok':all(x['ok'] for x in rows),'checks':rows},indent=2,default=str)); sys.exit(0 if all(x['ok'] for x in rows) else 2)
