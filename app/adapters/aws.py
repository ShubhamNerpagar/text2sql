from __future__ import annotations
import json, time
from typing import Any
import boto3
from botocore.exceptions import ClientError
from app.config import get_settings
from app.services.sql_safety import validate_read_only_sql, strip_sql_fences

class AwsAdapter:
    def __init__(self):
        self.s=get_settings(); self._glue=self._athena=self._bedrock=self._s3=None
    @property
    def glue(self):
        if self._glue is None: self._glue=boto3.client("glue",region_name=self.s.aws_region)
        return self._glue
    @property
    def athena(self):
        if self._athena is None: self._athena=boto3.client("athena",region_name=self.s.aws_region)
        return self._athena
    @property
    def bedrock(self):
        if self._bedrock is None: self._bedrock=boto3.client("bedrock-runtime",region_name=self.s.bedrock_region)
        return self._bedrock
    @property
    def s3(self):
        if self._s3 is None: self._s3=boto3.client("s3",region_name=self.s.aws_region)
        return self._s3
    def health(self)->dict[str,Any]:
        out={"mode":"aws","aws_region":self.s.aws_region,"services":{}}
        try: self.glue.get_databases(MaxResults=1); out["services"]["glue"]="connected"
        except Exception as e: out["services"]["glue"]="error: "+str(e)[:160]
        try: self.athena.list_work_groups(MaxResults=1); out["services"]["athena"]="connected"
        except Exception as e: out["services"]["athena"]="error: "+str(e)[:160]
        try: boto3.client("sts",region_name=self.s.aws_region).get_caller_identity(); out["services"]["credentials"]="available"
        except Exception as e: out["services"]["credentials"]="error: "+str(e)[:160]
        return out
    def list_databases(self)->list[str]:
        names=[]; token=None
        while True:
            kw={"MaxResults":100};
            if token: kw["NextToken"]=token
            r=self.glue.get_databases(**kw)
            names += [d["Name"] for d in r.get("DatabaseList",[]) if not self.s.db_prefix or d["Name"].startswith(self.s.db_prefix)]
            token=r.get("NextToken")
            if not token: break
        return sorted(names)
    def list_tables(self,database:str)->list[dict]:
        out=[]; token=None
        while True:
            kw={"DatabaseName":database,"MaxResults":100}
            if token: kw["NextToken"]=token
            r=self.glue.get_tables(**kw)
            for t in r.get("TableList",[]):
                out.append({"database":database,"name":t.get("Name"),"description":t.get("Description","") or "","columns":len(t.get("StorageDescriptor",{}).get("Columns",[])),"location":(t.get("StorageDescriptor",{}) or {}).get("Location","") or ""})
            token=r.get("NextToken")
            if not token: break
        return out
    def get_columns(self,database:str,table:str)->list[dict]:
        t=self.glue.get_table(DatabaseName=database,Name=table).get("Table",{})
        cols=t.get("StorageDescriptor",{}).get("Columns",[])+t.get("PartitionKeys",[])
        return [{"name":c.get("Name"),"type":c.get("Type","string"),"comment":c.get("Comment","") or ""} for c in cols]
    def get_json(self,key:str)->dict|None:
        if not self.s.semantic_bucket: return None
        try:
            r=self.s3.get_object(Bucket=self.s.semantic_bucket,Key=key)
            return json.loads(r["Body"].read().decode("utf-8"))
        except ClientError as e:
            if e.response.get("Error",{}).get("Code") in {"NoSuchKey","404"}: return None
            raise
    def put_json(self,key:str,data:dict)->None:
        if self.s.semantic_bucket:
            self.s3.put_object(Bucket=self.s.semantic_bucket,Key=key,Body=json.dumps(data,indent=2,ensure_ascii=False).encode(),ContentType="application/json")
    def list_keys(self,prefix:str)->list[str]:
        if not self.s.semantic_bucket: return []
        out=[]; token=None
        while True:
            kw={"Bucket":self.s.semantic_bucket,"Prefix":prefix.strip("/")+"/"}
            if token: kw["ContinuationToken"]=token
            r=self.s3.list_objects_v2(**kw); out += [x.get("Key","") for x in r.get("Contents",[]) if x.get("Key")]
            token=r.get("NextContinuationToken")
            if not token: break
        return out
    def invoke_text(self,prompt:str,max_tokens:int=4096,task:str='ask')->str:
        """Use the explicitly selected Bedrock model/profile through Converse.
        This preserves the no-secrets EC2 instance-role workflow.
        """
        from app.services.bedrock_model_service import BedrockModelService
        model=BedrockModelService().chosen_model(task)
        out=self.bedrock.converse(modelId=model,
            messages=[{'role':'user','content':[{'text':prompt}]}],
            inferenceConfig={'maxTokens':max_tokens,'temperature':0})
        message=out.get('output',{}).get('message',{})
        text=''.join(c.get('text','') for c in message.get('content',[]) if 'text' in c)
        if not text:raise RuntimeError(f'Bedrock model {model} returned no text')
        return text.strip()
    def execute_query(self,sql:str,database:str|None=None,*,row_limit=None,payload_limit=None)->dict:
        ok,msg=validate_read_only_sql(sql)
        if not ok: raise ValueError(msg)
        if not self.s.athena_output: raise RuntimeError("ATHENA_OUTPUT must be configured in APP_MODE=aws")
        params={"QueryString":strip_sql_fences(sql),"ResultConfiguration":{"OutputLocation":self.s.athena_output},"WorkGroup":self.s.athena_workgroup}
        if database: params["QueryExecutionContext"]={"Database":database,"Catalog":self.s.athena_catalog}
        qid=self.athena.start_query_execution(**params)["QueryExecutionId"]
        started=time.time()
        while True:
            q=self.athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
            state=q["Status"]["State"]
            if state in {"SUCCEEDED","FAILED","CANCELLED"}: break
            if time.time()-started>self.s.query_timeout_seconds:
                self.athena.stop_query_execution(QueryExecutionId=qid)
                raise TimeoutError(f"Athena query {qid} exceeded {self.s.query_timeout_seconds}s and was stopped")
            time.sleep(.7)
        if state!="SUCCEEDED": raise RuntimeError(q["Status"].get("StateChangeReason",state))
        cap=self.s.max_result_rows if row_limit is None else row_limit
        cols=[]; rows=[]; token=None; first=True;payload=0
        while len(rows)<cap:
            kw={"QueryExecutionId":qid,"MaxResults":1000}
            if token: kw["NextToken"]=token
            r=self.athena.get_query_results(**kw); rs=r.get("ResultSet",{})
            if not cols: cols=[c.get("Name","") for c in rs.get("ResultSetMetadata",{}).get("ColumnInfo",[])]
            page=rs.get("Rows",[])
            if first and page: page=page[1:]; first=False
            for row in page:
                vals=[d.get("VarCharValue") for d in row.get("Data",[])]; vals += [None]*(len(cols)-len(vals))
                item=dict(zip(cols,vals[:len(cols)]))
                if payload_limit is not None:
                    payload+=len(json.dumps(item,default=str,ensure_ascii=False).encode())
                    if payload>payload_limit:raise ValueError('FEDERATION_LIMIT_EXCEEDED: Athena payload exceeds snapshot budget')
                rows.append(item)
                if len(rows)>=cap: break
            token=r.get("NextToken")
            if not token: break
        stats=q.get("Statistics",{})
        return {"query_id":qid,"columns":cols,"rows":rows,"row_count":len(rows),"truncated":bool(token),"bytes_scanned":stats.get("DataScannedInBytes",0),"execution_ms":stats.get("EngineExecutionTimeInMillis",0)}
