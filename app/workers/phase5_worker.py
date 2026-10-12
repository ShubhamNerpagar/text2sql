"""Windows-native durable Phase5 worker.
Usage: python -m app.workers.phase5_worker --once [--worker-id hostname-1]
"""
import argparse, os, socket, threading, time, traceback
from app.services.phase5_service import Phase5Service

def process_one(service,worker_id,lease=120):
    job=service.jobs.claim(worker_id,lease_seconds=lease)
    if job is None:return None
    stop=threading.Event(); lost=threading.Event()
    def heartbeat():
        while not stop.wait(max(3,lease/4)):
            if not service.jobs.heartbeat(job['id'],worker_id,job['attempts'],lease,workspace=job['workspace']):
                lost.set();return
    t=threading.Thread(target=heartbeat,daemon=True);t.start()
    try:
        result=service.perform(job)
        if lost.is_set():raise RuntimeError('Job lease was lost; refusing stale commit')
        finished=service.jobs.finish(job['id'],worker_id,job['attempts'],result=result,workspace=job['workspace'])
    except Exception as exc:
        print('🚨 Phase5 job failed:',job['id'],type(exc).__name__,str(exc),flush=True)
        try:finished=service.jobs.finish(job['id'],worker_id,job['attempts'],error=type(exc).__name__+': '+str(exc),workspace=job['workspace'])
        except ValueError:finished={'id':job['id'],'status':'lease_lost'}
    finally:stop.set();t.join(timeout=1)
    print(('✅' if finished['status']=='succeeded' else '🚨'),job['id'],finished['status'],flush=True)
    return finished

def main():
    a=argparse.ArgumentParser()
    a.add_argument('--once',action='store_true')
    a.add_argument('--poll',type=float,default=2.0)
    a.add_argument('--worker-id',default=socket.gethostname()+'-'+str(os.getpid()))
    args=a.parse_args()
    if not 0.2<=args.poll<=60:raise SystemExit('Poll interval must be 0.2–60 seconds')
    service=Phase5Service();print('Phase5 worker online:',args.worker_id,flush=True)
    last_refresh=0
    while True:
        if time.monotonic()-last_refresh>=60:
            from app.services.guided_onboarding_service import GuidedOnboardingService
            GuidedOnboardingService().refresh_all()
            last_refresh=time.monotonic()
        result=process_one(service,args.worker_id)
        if args.once:break
        if result is None:time.sleep(args.poll)
if __name__=='__main__':main()
