#!/usr/bin/env python3
"""Deployment-time acceptance checks for the production AWS environment.

Run on the Windows EC2 host (or another machine) using the same IAM identity/policies as the application.
It intentionally does not modify source data. It verifies identity/configuration,
semantic S3 persistence, DynamoDB control plane, Glue/Athena access and Bedrock when enabled.
"""
from __future__ import annotations
import json, os, sys, time, uuid
from urllib.parse import urlparse
import boto3
from botocore.exceptions import ClientError

REGION=os.getenv('AWS_REGION','eu-west-1')
LOCAL_STATE=os.getenv('PERSIST_LOCAL_STATE','true').strip().lower() in {'1','true','yes','on'}
DURABLE_REQUIRED=not LOCAL_STATE or os.getenv('APP_ENV','development').strip().lower()=='production'
checks=[]
def check(name,fn,required=True):
    try:
        detail=fn(); checks.append({'name':name,'ok':True,'required':required,'detail':detail})
    except Exception as e:
        checks.append({'name':name,'ok':False,'required':required,'detail':f'{type(e).__name__}: {e}'})

def s3_parts(uri):
    p=urlparse(uri); return p.netloc,p.path.lstrip('/')

check('sts_identity',lambda: boto3.client('sts',region_name=REGION).get_caller_identity().get('Arn'))

semantic_bucket=os.getenv('SEMANTIC_BUCKET','')
if semantic_bucket:
    def semantic_s3():
        c=boto3.client('s3',region_name=REGION); key=f"runtime/acceptance/{uuid.uuid4().hex}.json"; body=b'{"ok":true}'
        c.put_object(Bucket=semantic_bucket,Key=key,Body=body,ContentType='application/json'); got=c.get_object(Bucket=semantic_bucket,Key=key)['Body'].read(); c.delete_object(Bucket=semantic_bucket,Key=key)
        return f'round-trip {len(got)} bytes'
    check('semantic_s3_roundtrip',semantic_s3)
else: checks.append({'name':'semantic_s3_roundtrip','ok':LOCAL_STATE,'required':DURABLE_REQUIRED,'detail':'SEMANTIC_BUCKET unset; local state enabled' if LOCAL_STATE else 'SEMANTIC_BUCKET unset'})

learning=os.getenv('LEARNING_TABLE','')
if learning:
    def ddb():
        t=boto3.resource('dynamodb',region_name=REGION).Table(learning); pk='ACCEPTANCE'; sk=uuid.uuid4().hex; t.put_item(Item={'pk':pk,'sk':sk,'payload':'{}'}); got=t.get_item(Key={'pk':pk,'sk':sk}).get('Item'); t.delete_item(Key={'pk':pk,'sk':sk}); return bool(got)
    check('dynamodb_roundtrip',ddb)
else: checks.append({'name':'dynamodb_roundtrip','ok':LOCAL_STATE,'required':DURABLE_REQUIRED,'detail':'LEARNING_TABLE unset; local state enabled' if LOCAL_STATE else 'LEARNING_TABLE unset'})

athena_output=os.getenv('ATHENA_OUTPUT','')
if athena_output:
    def athena():
        c=boto3.client('athena',region_name=REGION); wg=os.getenv('ATHENA_WORKGROUP','primary'); db=os.getenv('ACCEPTANCE_ATHENA_DATABASE') or os.getenv('DEFAULT_ATHENA_DATABASE')
        args={'QueryString':'SELECT 1 AS acceptance_ok','WorkGroup':wg,'ResultConfiguration':{'OutputLocation':athena_output}}
        if db: args['QueryExecutionContext']={'Database':db,'Catalog':os.getenv('ATHENA_CATALOG','AwsDataCatalog')}
        qid=c.start_query_execution(**args)['QueryExecutionId']; deadline=time.time()+60
        while time.time()<deadline:
            q=c.get_query_execution(QueryExecutionId=qid)['QueryExecution']; st=q['Status']['State']
            if st=='SUCCEEDED': return {'query_id':qid,'bytes_scanned':q.get('Statistics',{}).get('DataScannedInBytes',0),'workgroup':wg}
            if st in {'FAILED','CANCELLED'}: raise RuntimeError(q['Status'].get('StateChangeReason',st))
            time.sleep(1)
        c.stop_query_execution(QueryExecutionId=qid); raise TimeoutError('Athena acceptance query timed out')
    check('athena_select_1',athena)
else: checks.append({'name':'athena_select_1','ok':False,'required':os.getenv('DEFAULT_DATA_SOURCE','')=='athena','detail':'ATHENA_OUTPUT unset'})

def glue():
    c=boto3.client('glue',region_name=REGION); r=c.get_databases(MaxResults=1); return f"visible databases: {len(r.get('DatabaseList',[]))}+"
check('glue_catalog_access',glue,required=os.getenv('DEFAULT_DATA_SOURCE','')=='athena')

if os.getenv('EMBEDDING_PROVIDER','').lower()=='bedrock':
    def bedrock():
        c=boto3.client('bedrock-runtime',region_name=os.getenv('BEDROCK_REGION',REGION)); model=os.getenv('EMBEDDING_MODEL','amazon.titan-embed-text-v2:0'); payload=json.dumps({'inputText':'production acceptance','dimensions':int(os.getenv('EMBEDDING_DIMENSIONS','1024')),'normalize':True}).encode(); r=c.invoke_model(modelId=model,body=payload,accept='application/json',contentType='application/json'); data=json.loads(r['body'].read()); return f"embedding dimensions={len(data.get('embedding',[]))}"
    check('bedrock_embedding',bedrock)

print(json.dumps({'ok':all(x['ok'] for x in checks if x['required']),'checks':checks},indent=2,default=str))
sys.exit(0 if all(x['ok'] for x in checks if x['required']) else 2)
