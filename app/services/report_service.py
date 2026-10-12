from __future__ import annotations
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from copy import deepcopy
import csv, io, json, operator, uuid
from app.config import get_settings
from app.repositories.control_repository import ControlRepository
from app.services.security_service import SecurityService, UserContext
from app.services.query_service import QueryService

class ReportService:
    """Governed BI reports with filters, sharing, scheduling, alerts and exports."""
    OPS={'>':operator.gt,'>=':operator.ge,'<':operator.lt,'<=':operator.le,'==':operator.eq,'!=':operator.ne}
    def __init__(self):
        self.repo=ControlRepository(); self.security=SecurityService(); self.queries=QueryService(); self.s=get_settings()
    @staticmethod
    def _now(): return datetime.now(timezone.utc).isoformat()
    @staticmethod
    def _numeric(v):
        if isinstance(v,(int,float)) and not isinstance(v,bool): return True
        try: float(str(v).replace(',','')); return True
        except Exception: return False
    def suggest_visualization(self,response):
        result=response.get('result') or {}; rows=result.get('rows') or []; cols=result.get('columns') or (list(rows[0]) if rows else []); plan=response.get('plan') or {}; features=plan.get('features') or {}
        if not rows or not cols: return {'type':'table','title':response.get('question','Result'),'columns':cols}
        nums=[]; texts=[]
        for c in cols:
            vals=[r.get(c) for r in rows[:20] if r.get(c) is not None]
            (nums if vals and sum(self._numeric(v) for v in vals)>=max(1,int(len(vals)*.8)) else texts).append(c)
        if len(rows)==1 and nums: return {'type':'kpi','title':response.get('question','Metric'),'value':nums[0],'format':'auto'}
        time_col=next((c for c in cols if any(w in c.lower() for w in ('date','month','quarter','year','week','day','period'))),None); value=nums[0] if nums else None; cat=next((c for c in texts if c!=value),None) or (cols[0] if cols else None)
        if value and (time_col or features.get('time_series') or features.get('period_over_period')): return {'type':'line','title':response.get('question','Trend'),'x':time_col or cat,'y':value}
        if value and cat: return {'type':'bar','title':response.get('question','Breakdown'),'x':cat,'y':value,'limit':20}
        return {'type':'table','title':response.get('question','Result'),'columns':cols}
    def _can_read(self,r,u):
        if not self.security.can(u,'query',r.get('market','')): return False
        if self.security.is_admin(u) or r.get('owner_id')==u.user_id: return True
        return r.get('status') in {'published','certified'} and (not (r.get('shared_roles') or []) or u.has_any(r.get('shared_roles') or []))
    def _can_edit(self,r,u):
        if not self.security.can(u,'query',r.get('market','')): return False
        return self.security.is_admin(u) or r.get('owner_id')==u.user_id or self.security.can(u,'semantic_review',r.get('market',''))
    def list(self,market,u):
        if not self.security.can(u,'query',market): raise PermissionError('Report workspace access denied.')
        return [{**x,'widget_count':len(x.get('widgets') or [])} for x in self.repo.list('REPORT',500) if x.get('market')==market and self._can_read(x,u)]
    def get(self,rid,u):
        r=self.repo.get('REPORT',rid)
        if not r: raise KeyError(rid)
        if not self._can_read(r,u): raise PermissionError('Report access denied.')
        return r
    def create(self,market,title,description,u):
        if not self.security.can(u,'query',market): raise PermissionError('Report creation requires query permission.')
        rid='report-'+uuid.uuid4().hex[:12]; r={'report_id':rid,'market':market,'workspace_id':market,'title':title,'description':description,'owner_id':u.user_id,'status':'draft','shared_roles':[],'filters':[],'widgets':[],'schedule':{'enabled':False},'alerts':[],'created_at':self._now()}; return self.repo.put('REPORT',rid,r)
    def add_widget(self,rid,question,title,chart_type,u,release_id=None):
        r=self.get(rid,u)
        if not self._can_edit(r,u): raise PermissionError('Report edit permission denied.')
        if len(r.get('widgets') or [])>=24: raise ValueError('A report can contain at most 24 widgets.')
        planned=self.queries.run(question,r['market'],False,user=u,release_id=release_id)
        if not planned.get('structured_plan'):raise ValueError('Resolve the question before saving a report widget')
        w={'release_id':planned['release_id'],'structured_plan':planned['structured_plan'],'semantic_review':planned['semantic_review'],'widget_id':'widget-'+uuid.uuid4().hex[:10],'title':title or question[:120],'question':question,'chart_type':chart_type or 'auto','size':'wide' if chart_type in {'bar','line','table','auto'} else 'small','filters':[],'created_at':self._now()}; r.setdefault('widgets',[]).append(w); r['updated_at']=self._now(); self.repo.put('REPORT',rid,r); return w
    def remove_widget(self,rid,wid,u):
        r=self.get(rid,u)
        if not self._can_edit(r,u): raise PermissionError('Report edit permission denied.')
        r['widgets']=[w for w in r.get('widgets',[]) if w.get('widget_id')!=wid]; r['updated_at']=self._now(); return self.repo.put('REPORT',rid,r)
    def set_status(self,rid,status,u):
        r=self.get(rid,u); market=r.get('market','')
        if status=='certified' and not self.security.can(u,'publish',market): raise PermissionError('Certification requires publish permission.')
        if status in {'published','deprecated'} and not self._can_edit(r,u): raise PermissionError('Report status permission denied.')
        r['status']=status; r['updated_at']=self._now(); return self.repo.put('REPORT',rid,r)
    def share(self,rid,roles,u):
        r=self.get(rid,u)
        if not self._can_edit(r,u): raise PermissionError('Report sharing permission denied.')
        r['shared_roles']=sorted({str(x).strip() for x in roles if str(x).strip()}); r['updated_at']=self._now(); return self.repo.put('REPORT',rid,r)
    def set_filters(self,rid,filters,u):
        r=self.get(rid,u)
        if not self._can_edit(r,u): raise PermissionError('Report edit permission denied.')
        ctx=self.queries.markets.context(r.get('market','')); allowed=set((ctx.get('bindings',{}).get('dimensions',{}) or {}))|set((ctx.get('bindings',{}).get('dates',{}) or {}))|set((ctx.get('bindings',{}).get('concepts',{}) or {}))
        for f in filters:
            if f.get('dimension') not in allowed: raise ValueError(f"Filter dimension {f.get('dimension')} is not governed for this workspace.")
        r['filters']=filters[:20]; r['updated_at']=self._now(); return self.repo.put('REPORT',rid,r)
    def set_schedule(self,rid,schedule,u):
        r=self.get(rid,u)
        if not self._can_edit(r,u): raise PermissionError('Report schedule permission denied.')
        sched={**schedule,'updated_at':self._now()}
        if sched.get('enabled'):
            from app.services.cron_service import next_run
            try: sched['next_run_at']=next_run(sched.get('cron','0 8 * * *'),datetime.now(timezone.utc)).isoformat()
            except Exception as e: raise ValueError(f'Invalid report cron expression: {e}')
        r['schedule']=sched; return self.repo.put('REPORT',rid,r)
    def add_alert(self,rid,alert,u):
        r=self.get(rid,u)
        if not self._can_edit(r,u): raise PermissionError('Report alert permission denied.')
        if alert.get('widget_id') not in {w.get('widget_id') for w in r.get('widgets',[])}: raise ValueError('Alert widget does not exist.')
        aid='alert-'+uuid.uuid4().hex[:10]; item={'alert_id':aid,**alert,'created_at':self._now()}; r.setdefault('alerts',[]).append(item); self.repo.put('REPORT',rid,r); return item
    def _filtered_question(self,question,filters):
        q=question.rstrip(' .')
        for f in filters or []:
            if f.get('value') not in {None,''}: q+=f" where {str(f.get('dimension')).replace('_',' ')} {f.get('operator','equals')} {f.get('value')}"
        return q
    def lineage(self,rid,u):
        r=self.get(rid,u);nodes=[{'id':'report:'+rid,'label':r['title'],'type':'report'}];edges=[]
        for widget in r.get('widgets',[]):
            wid='report_widget:'+widget['widget_id'];nodes.append({'id':wid,'label':widget['title'],'type':'report_widget'})
            edges.append({'source':'report:'+rid,'target':wid,'type':'HAS_WIDGET'})
            plan=widget.get('structured_plan',{})
            for m in plan.get('metrics',[]):
                mid='metric:'+m['metric_id'];nodes.append({'id':mid,'label':m['metric_id'],'type':'metric'})
                edges.append({'source':wid,'target':mid,'type':'USES_METRIC'})
            for d in plan.get('dimensions',[]):
                did='dimension:'+d['asset_id']+':'+d['column'];nodes.append({'id':did,'label':d['column'],'type':'dimension'})
                edges.append({'source':wid,'target':did,'type':'GROUPS_BY'})
        return {'report_id':rid,'nodes':list({n['id']:n for n in nodes}.values()),'edges':edges}

    def _widget_plan(self,report,widget,filters):
        if not widget.get('release_id') or not widget.get('structured_plan'):
            raise ValueError('Legacy widget needs explicit migration: re-save its question against a certified release')
        plan=deepcopy(widget['structured_plan'])
        ctx=self.queries.markets.context(report['market']);bindings=ctx.get('bindings',{}).get('dimensions',{})
        from app.services.phase2_service import Phase2Service
        assets=Phase2Service().assets(report['market'])
        for f in filters:
            b=bindings.get(f['dimension'])
            if not b:raise ValueError('Report filter is no longer governed')
            asset=next((a for a in assets if a['table']==b['table'] and a['database']==b['database']),None)
            if not asset:raise ValueError('Report filter is out of scope')
            op={'equals':'eq','=':'eq','>':'gt','<':'lt','!=':'ne'}.get(f.get('operator','eq'),f.get('operator','eq'))
            plan.setdefault('filters',[]).append({'asset_id':asset['asset_id'],'column':b['column'],'op':op,'value':f['value']})
        return plan

    def drilldown(self,rid,wid,dimension,u,data_source=None):
        r=self.get(rid,u);w=next((w for w in r['widgets'] if w['widget_id']==wid),None)
        if not w:raise KeyError(wid)
        b=self.queries.markets.context(r['market']).get('bindings',{}).get('dimensions',{}).get(dimension)
        if not b:raise ValueError('Drilldown dimension is not governed')
        from app.services.phase2_service import Phase2Service
        a=next((a for a in Phase2Service().assets(r['market']) if a['database']==b['database'] and a['table']==b['table']),None)
        plan=self._widget_plan(r,w,r.get('filters',[])+w.get('filters',[]))
        plan['dimensions']=[{'asset_id':a['asset_id'],'column':b['column']}]
        response=self.queries.run(w['question'],r['market'],True,data_source=data_source,user=u,release_id=w['release_id'],approved_plan=plan)
        return {'report_id':rid,'widget_id':wid,'dimension':dimension,'query':response,'visualization':self.suggest_visualization(response)}

    def render(self,rid,u,data_source=None):
        r=self.get(rid,u);rendered=[]
        for w in r.get('widgets',[])[:24]:
            plan=self._widget_plan(r,w,r.get('filters',[])+w.get('filters',[]))
            response=self.queries.run(w['question'],r['market'],True,data_source=data_source,user=u,release_id=w['release_id'],approved_plan=plan)
            viz=self.suggest_visualization(response)
            if w.get('chart_type','auto')!='auto':viz['type']=w['chart_type']
            rendered.append({'widget':w,'query':response,'visualization':viz})
        return {'report':r,'rendered_widgets':rendered,'refreshed_at':self._now()}

    def evaluate_alerts(self,rendered):
        r=rendered['report']; by_widget={x['widget'].get('widget_id'):x for x in rendered.get('rendered_widgets',[])}; triggered=[]
        for a in r.get('alerts',[]) or []:
            if not a.get('enabled',True): continue
            x=by_widget.get(a.get('widget_id')); rows=((x or {}).get('query') or {}).get('result',{}).get('rows',[]) if x else []
            if not rows: continue
            col=a.get('value_column'); row=rows[0]
            if not col: col=next((k for k,v in row.items() if self._numeric(v)),None)
            if not col or not self._numeric(row.get(col)): continue
            value=float(str(row[col]).replace(',','')); op=self.OPS.get(a.get('operator','>'),operator.gt); threshold=float(a.get('threshold',0))
            if op(value,threshold): triggered.append({**a,'actual_value':value,'triggered_at':self._now()})
        return triggered
    def _notify(self,report,alerts):
        if not alerts or not self.s.report_alert_sns_topic_arn: return
        try:
            import boto3
            boto3.client('sns',region_name=self.s.aws_region).publish(TopicArn=self.s.report_alert_sns_topic_arn,Subject=f"Data Intelligence alert: {report.get('title','Report')}",Message=json.dumps({'report_id':report.get('report_id'),'alerts':alerts},indent=2,default=str))
        except Exception as e: self.repo.put('AUDIT',f"sns-error-{uuid.uuid4().hex}",{'event':'report_alert_delivery_failed','report_id':report.get('report_id'),'error':str(e)[:500]})
    def run_scheduled(self,report_id,u,data_source=None):
        rendered=self.render(report_id,u,data_source); alerts=self.evaluate_alerts(rendered); self._notify(rendered['report'],alerts); run={'run_id':'report-run-'+uuid.uuid4().hex[:12],'report_id':report_id,'market':rendered['report'].get('market'),'status':'success','alert_count':len(alerts),'alerts':alerts,'executed_at':self._now()}; self.repo.put('REPORT_RUN',run['run_id'],run); return run

    def run_due(self):
        now=datetime.now(timezone.utc); admin=UserContext('report-worker',tuple(self.s.admin_roles),{'workspace':''}); runs=[]
        for r in self.repo.list('REPORT',1000):
            sched=r.get('schedule') or {}
            if not sched.get('enabled'): continue
            try: due=datetime.fromisoformat(str(sched.get('next_run_at','')).replace('Z','+00:00'))
            except Exception: due=now
            if due>now: continue
            try:
                run=self.run_scheduled(r['report_id'],admin,sched.get('data_source')); runs.append(run)
                from app.services.cron_service import next_run
                sched['last_run_at']=now.isoformat(); sched['next_run_at']=next_run(sched.get('cron','0 8 * * *'),now).isoformat(); r['schedule']=sched; self.repo.put('REPORT',r['report_id'],r)
            except Exception as e:
                run={'run_id':'report-run-'+uuid.uuid4().hex[:12],'report_id':r.get('report_id'),'status':'error','error':str(e)[:500],'executed_at':self._now()}; self.repo.put('REPORT_RUN',run['run_id'],run); runs.append(run)
        return {'due_count':len(runs),'runs':runs}

    def export(self,rid,u,fmt='csv',data_source=None):
        rendered=self.render(rid,u,data_source); title=rendered['report'].get('title','report'); fmt=fmt.lower()
        if fmt=='csv':
            out=io.StringIO(); w=csv.writer(out)
            for item in rendered['rendered_widgets']:
                w.writerow([item['widget'].get('title')]); rows=(item['query'].get('result') or {}).get('rows') or []; cols=(item['query'].get('result') or {}).get('columns') or (list(rows[0]) if rows else [])
                w.writerow(cols); [w.writerow([row.get(c) for c in cols]) for row in rows]; w.writerow([])
            return out.getvalue().encode(),'text/csv',f'{rid}.csv'
        if fmt=='xlsx':
            from openpyxl import Workbook
            wb=Workbook(); wb.remove(wb.active)
            for i,item in enumerate(rendered['rendered_widgets'],1):
                ws=wb.create_sheet((item['widget'].get('title') or f'Widget {i}')[:31]); rows=(item['query'].get('result') or {}).get('rows') or []; cols=(item['query'].get('result') or {}).get('columns') or (list(rows[0]) if rows else []); ws.append(cols)
                for row in rows: ws.append([row.get(c) for c in cols])
                ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions
            buf=BytesIO(); wb.save(buf); return buf.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',f'{rid}.xlsx'
        if fmt=='pdf':
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
            from reportlab.lib import colors
            from reportlab.lib.styles import getSampleStyleSheet
            buf=BytesIO(); doc=SimpleDocTemplate(buf,pagesize=A4); st=getSampleStyleSheet(); story=[Paragraph(title,st['Title']),Spacer(1,12)]
            for item in rendered['rendered_widgets']:
                story.append(Paragraph(item['widget'].get('title','Widget'),st['Heading2'])); rows=(item['query'].get('result') or {}).get('rows') or []; cols=(item['query'].get('result') or {}).get('columns') or (list(rows[0]) if rows else []); data=[cols]+[[str(row.get(c,''))[:80] for c in cols] for row in rows[:50]]
                if data and cols:
                    t=Table(data,repeatRows=1); t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#162033')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),.25,colors.grey),('FONTSIZE',(0,0),(-1,-1),7)])); story.append(t)
                story.append(Spacer(1,12))
            doc.build(story); return buf.getvalue(),'application/pdf',f'{rid}.pdf'
        raise ValueError('format must be csv, xlsx, or pdf')
