#!/usr/bin/env python3
"""Import independent reference-SQL cases and run the shared live business benchmark.

Input JSON: [{"workspace":"finance","release_id":"p3-v1","question":"...",
"expected":"answer","reference_asset_id":"asset:...","reference_sql":"SELECT SUM(...) ...",
"previous_plan":null}]. Use expected=refuse for deliberate clarification cases.
The API requires publish permission; development headers do not authenticate production.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request,urlopen


def post(url,payload,headers):
    request=Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json',**headers},method='POST')
    with urlopen(request,timeout=600) as response:return json.loads(response.read())


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('cases');parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    parser.add_argument('--role',default='semantic_admin');parser.add_argument('--output',default='benchmark-results.json')
    args=parser.parse_args();cases=json.loads(Path(args.cases).read_text(encoding='utf-8'))
    if not isinstance(cases,list) or not cases:parser.error('Provide at least one independent reference case')
    headers={'X-Roles':args.role,'X-User':'benchmark-steward'};groups=set();runs=[]
    for case in cases:
        workspace=case['workspace'];release=case['release_id'];groups.add((workspace,release))
        post(args.base_url.rstrip('/')+'/api/benchmarks/business/cases?workspace='+quote(workspace,safe=''),
             {k:v for k,v in case.items() if k!='workspace'},headers)
    for workspace,release in sorted(groups):
        runs.append(post(args.base_url.rstrip('/')+'/api/benchmarks/business/run?workspace='+quote(workspace,safe=''),{'release_id':release},headers))
    out={'method':'llm_answers_vs_independent_reference_sql','runs':runs}
    Path(args.output).write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps(out,indent=2))
    raise SystemExit(0 if all(r['status']=='passed' for r in runs) else 3)


if __name__=='__main__':main()
