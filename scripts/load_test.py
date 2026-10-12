#!/usr/bin/env python3
"""Dependency-free HTTP concurrency smoke/load test for a deployed candidate."""
from __future__ import annotations
import argparse, concurrent.futures, json, math, time, urllib.request

def percentile(xs,p):
    if not xs:return 0
    xs=sorted(xs); i=min(len(xs)-1,max(0,math.ceil(p*len(xs))-1)); return xs[i]
def one(url,headers):
    t=time.perf_counter()
    try:
        req=urllib.request.Request(url,headers=headers); r=urllib.request.urlopen(req,timeout=30); r.read(); return r.status,(time.perf_counter()-t)*1000
    except Exception:return 0,(time.perf_counter()-t)*1000

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--base-url',default='http://127.0.0.1:8000'); ap.add_argument('--path',default='/api/health'); ap.add_argument('--requests',type=int,default=500); ap.add_argument('--concurrency',type=int,default=25); args=ap.parse_args(); url=args.base_url.rstrip('/')+args.path
    started=time.perf_counter(); results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex: results=list(ex.map(lambda _:one(url,{'X-Roles':'semantic_admin','X-User':'load-test'}),range(args.requests)))
    elapsed=time.perf_counter()-started; lat=[x[1] for x in results]; success=sum(1 for s,_ in results if 200<=s<400); report={'url':url,'requests':args.requests,'concurrency':args.concurrency,'success':success,'errors':args.requests-success,'rps':round(args.requests/max(elapsed,.001),2),'p50_ms':round(percentile(lat,.50),2),'p95_ms':round(percentile(lat,.95),2),'p99_ms':round(percentile(lat,.99),2),'max_ms':round(max(lat or [0]),2)}; print(json.dumps(report,indent=2)); raise SystemExit(0 if success==args.requests else 4)
if __name__=='__main__': main()
