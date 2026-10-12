from __future__ import annotations
from datetime import datetime, timedelta, timezone

def _matches(value:int,expr:str,min_v:int,max_v:int)->bool:
    def atom(part):
        if '/' in part:
            base,step=part.split('/',1); step=int(step)
            if step<=0: return False
            start=min_v if base=='*' else int(base)
            return value>=start and (value-start)%step==0
        if '-' in part:
            a,b=(int(x) for x in part.split('-',1)); return a<=value<=b
        if part=='*': return True
        return value==int(part)
    try: return any(atom(x.strip()) for x in expr.split(',') if x.strip())
    except Exception: return False

def cron_matches(dt:datetime,expr:str)->bool:
    parts=str(expr or '').split()
    if len(parts)!=5: raise ValueError('Cron must contain exactly five fields: minute hour day month weekday.')
    minute,hour,day,month,weekday=parts; cron_weekday=(dt.weekday()+1)%7
    return _matches(dt.minute,minute,0,59) and _matches(dt.hour,hour,0,23) and _matches(dt.day,day,1,31) and _matches(dt.month,month,1,12) and _matches(cron_weekday,weekday,0,6)

def next_run(expr:str,after:datetime|None=None)->datetime:
    cur=(after or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(second=0,microsecond=0)+timedelta(minutes=1)
    # Bound search to one leap year. This supports normal 5-field cron schedules without a runtime dependency.
    for _ in range(527040):
        if cron_matches(cur,expr): return cur
        cur+=timedelta(minutes=1)
    raise ValueError('Cron expression produced no run time within one year.')
