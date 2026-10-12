"""Bounded HTTP smoke/load tool; requires explicit --url. No auth credentials embedded."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import argparse, json, math, statistics, time
from urllib.request import Request, urlopen

def run(args):
    if not args.url.startswith(('http://127.0.0.1:', 'http://localhost:')) and not args.allow_remote:
        raise ValueError('Remote load testing requires --allow-remote; test only systems you own')
    if args.path not in {'/api/health','/api/ready'}:
        raise ValueError('Benchmark path restricted to read-only health and readiness endpoints')
    n=args.requests
    def ping(_):
        started=time.perf_counter()
        try:
            with urlopen(Request(args.url.rstrip('/')+args.path,headers={'User-Agent':'DIP-P5-Bounded-Load/1.0'}),timeout=args.timeout) as r:
                code=r.status;r.read(2048)
        except Exception as e:code=0
        return (code,1000*(time.perf_counter()-started))
    start=time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results=list(pool.map(ping,range(n)))
    elapsed=time.perf_counter()-start
    samples=sorted(v for _,v in results)
    percentile=lambda p:samples[min(len(samples)-1,math.ceil(p/100*len(samples))-1)]
    data={'url':args.url,'path':args.path,'requests':n,'concurrency':args.concurrency,
          'success':sum(1 for code,_ in results if code==200),'errors':sum(1 for code,_ in results if code!=200),
          'elapsed_s':round(elapsed,3),'rps':round(n/max(0.001,elapsed),2),
          'latency_ms':{'p50':round(percentile(50),2),'p95':round(percentile(95),2),'p99':round(percentile(99),2),
                         'max':round(samples[-1],2)},
          'warning':'Small bounded smoke load, not a production capacity certificate'}
    print(json.dumps(data,indent=2))
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(json.dumps(data,indent=2),encoding='utf-8')
    return 0 if not data['errors'] else 2
if __name__=='__main__':
    a=argparse.ArgumentParser()
    a.add_argument('--url',required=True)
    a.add_argument('--path',default='/api/health')
    a.add_argument('--requests',type=int,default=100)
    a.add_argument('--concurrency',type=int,default=8)
    a.add_argument('--timeout',type=float,default=6)
    a.add_argument('--output')
    a.add_argument('--allow-remote',action='store_true')
    args=a.parse_args()
    if not 1<=args.requests<=1000 or not 1<=args.concurrency<=32 or not 1<=args.timeout<=20:
        a.error('Requests 1–1000, concurrency 1–32, timeout 1–20 seconds')
    raise SystemExit(run(args))
