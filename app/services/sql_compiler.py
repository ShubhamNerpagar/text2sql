from __future__ import annotations
import re
from app.services.market_service import MarketService

class SQLCompiler:
    """Deterministic, dialect-aware compiler for governed semantic plans."""
    def __init__(self): self.markets=MarketService()
    @staticmethod
    def _metric_id(plan):
        m=plan.get('metric'); return m.get('id') if isinstance(m,dict) else m
    @staticmethod
    def _node(spec):
        t=spec.get('table'); return (f"{spec.get('database')}.{t}" if spec.get('database') else t) if t else None
    @staticmethod
    def _allowed_metric_statuses(plan):
        allowed={'verified','approved','governed','certified'}
        if plan.get('allow_inferred_metrics'): allowed |= {'inferred','draft','reviewed'}
        return allowed
    @staticmethod
    def _quote_table(node,dialect='athena'):
        parts=node.split('.',1) if '.' in node else [node]
        q='`' if dialect=='databricks' else '"'
        return '.'.join(f'{q}{x}{q}' for x in parts)
    @staticmethod
    def _translate(expr,dialect):
        if dialect=='postgresql':
            expr=re.sub(r'TRY_CAST\((.+?) AS DOUBLE\)',r"CAST(NULLIF(\1::text,'') AS DOUBLE PRECISION)",expr,flags=re.I)
            expr=re.sub(r'TRY_CAST\((.+?) AS DATE\)',r'CAST(\1 AS DATE)',expr,flags=re.I)
        return expr
    def can_compile(self,plan):
        reasons=[]; tables=plan.get('tables',[]) or []
        if plan.get('decision')!='COMMIT': reasons.append('plan_not_committed')
        if not tables: reasons.append('no_tables')
        if not (plan.get('join_plan',{}) or {}).get('connected',True): reasons.append('untrusted_or_missing_join_path')
        ctx=self.markets.context(plan.get('market','')); bindings=ctx.get('bindings',{}) or {}; mid=self._metric_id(plan)
        if mid and mid!='record_count':
            metric=plan.get('metric') or {}; src=[x for x in (metric.get('spec',{}) or {}).get('preferred_sources',[]) or [] if str(x.get('status','')).lower() in self._allowed_metric_statuses(plan)]
            if not src: reasons.append(f'metric_not_governed:{mid}')
        if plan.get('intent')=='aggregate' and not mid:
            reasons.append('metric_required_for_aggregate')
        for dim in plan.get('group_dimensions',[]) or []:
            if dim not in (bindings.get('dimensions',{}) or {}) and dim not in (bindings.get('concepts',{}) or {}): reasons.append(f'dimension_not_bound:{dim}')
        for f in plan.get('filters',[]) or []:
            dim=f.get('dimension')
            if dim and dim not in (bindings.get('dimensions',{}) or {}) and dim not in (bindings.get('concepts',{}) or {}): reasons.append(f'filter_not_bound:{dim}')
        return not reasons,reasons
    def compile(self,plan,dialect='athena',row_predicates=None):
        ok,reasons=self.can_compile(plan)
        if not ok: return {'supported':False,'reasons':reasons,'sql':None,'compiler':'governed_ast_v2','dialect':dialect}
        market=plan.get('market',''); ctx=self.markets.context(market); bindings=ctx.get('bindings',{}) or {}; tables=list(dict.fromkeys(plan.get('tables',[]) or [])); root=(plan.get('join_plan',{}) or {}).get('root') or tables[0]; ordered=[root]+[t for t in tables if t!=root]; aliases={t:f't{i}' for i,t in enumerate(ordered)}; select=[]; group=[]; where=[]
        def bound_expr(spec):
            node=self._node(spec); alias=aliases.get(node)
            if not alias: return None
            if spec.get('expression'): return self._translate(spec['expression'].replace('{alias}',alias),dialect)
            if spec.get('column'): return f"{alias}.{spec['column']}"
            if spec.get('key'): return f"{alias}.{spec['key']}"
            return None
        for dim in plan.get('group_dimensions',[]) or []:
            spec=(bindings.get('dimensions',{}) or {}).get(dim) or (bindings.get('concepts',{}) or {}).get(dim); expr=bound_expr(spec or {})
            if expr: select.append(f'{expr} AS {dim}'); group.append(expr)
        mid=self._metric_id(plan); metric=plan.get('metric') or {}
        if mid=='record_count':
            select.append('COUNT(*) AS record_count')
        elif mid:
            source=next((x for x in (metric.get('spec',{}) or {}).get('preferred_sources',[]) or [] if str(x.get('status','')).lower() in self._allowed_metric_statuses(plan)),None)
            if not source: return {'supported':False,'reasons':[f'metric_not_governed:{mid}'],'sql':None,'compiler':'governed_ast_v2','dialect':dialect}
            node=self._node(source); alias=aliases.get(node)
            if not alias: return {'supported':False,'reasons':[f'metric_source_not_in_plan:{node}'],'sql':None,'compiler':'governed_ast_v2','dialect':dialect}
            column=source.get('column'); col=f"{alias}.{column}" if column else None
            if source.get('expression'):
                expr=self._translate(source['expression'].replace('{column}',col or alias).replace('{alias}',alias),dialect)
            else:
                agg=str(source.get('aggregation') or (metric.get('spec',{}) or {}).get('aggregation') or '').lower()
                if agg=='count' and not column: expr='COUNT(*)'
                elif not column: return {'supported':False,'reasons':[f'metric_column_missing:{mid}'],'sql':None,'compiler':'governed_ast_v2','dialect':dialect}
                elif agg=='sum': expr=f'SUM({col})'
                elif agg=='avg': expr=f'AVG({col})'
                elif agg=='min': expr=f'MIN({col})'
                elif agg=='max': expr=f'MAX({col})'
                elif agg=='count': expr=f'COUNT({col})'
                elif agg=='count_distinct': expr=f'COUNT(DISTINCT {col})'
                else: return {'supported':False,'reasons':[f'unsupported_metric_aggregation:{agg or "missing"}'],'sql':None,'compiler':'governed_ast_v2','dialect':dialect}
            output_alias='record_count' if str(source.get('aggregation') or (metric.get('spec',{}) or {}).get('aggregation') or '').lower()=='count' and not source.get('column') else mid
            select.append(f'{expr} AS {output_alias}')
        elif plan.get('intent')=='detail':
            # Detail queries must name dimensions; aggregate queries are never silently converted to COUNT(*).
            pass
        else:
            return {'supported':False,'reasons':['metric_required_for_aggregate'],'sql':None,'compiler':'governed_ast_v2','dialect':dialect}
        grouped={}
        for f in plan.get('filters',[]) or []: grouped.setdefault(f.get('dimension'),[]).append(f)
        for dim,fs in grouped.items():
            spec=(bindings.get('dimensions',{}) or {}).get(dim) or (bindings.get('concepts',{}) or {}).get(dim); expr=bound_expr(spec or {})
            if not expr: continue
            vals=[]
            for f in fs:
                v=f.get('value')
                if v is None and f.get('representations'):
                    rep=(spec or {}).get('representation'); reps=f.get('representations') or {}; v=reps.get(rep) if rep else next(iter(reps.values()),f.get('canonical'))
                if v is None: v=f.get('canonical')
                if v is not None: vals.append(str(v))
            safe=list(dict.fromkeys(x.replace("'","''") for x in vals))
            if len(safe)==1: where.append(f"{expr} = '{safe[0]}'")
            elif safe: where.append(f"{expr} IN ({', '.join(chr(39)+v+chr(39) for v in safe)})")
        time_ctx=plan.get('time',{}) or {}; q=(plan.get('question') or '').lower(); date_key='registration_date' if any(x in q for x in ['register','registration','immatric']) else ('invoice_date' if mid in {'revenue','invoice_count','vehicles_sold'} or 'invoice' in q or 'facture' in q else None); ds=(bindings.get('dates',{}) or {}).get(date_key) if date_key else None
        if ds:
            node=self._node(ds); alias=aliases.get(node)
            if alias and ds.get('column'):
                raw=f"{alias}.{ds['column']}"; dexpr=self._translate(f'TRY_CAST({raw} AS DATE)',dialect); years=time_ctx.get('years',[]) or []
                if years:
                    yexpr=f'EXTRACT(YEAR FROM {dexpr})' if dialect=='postgresql' else f'YEAR({dexpr})'; where.append(f"{yexpr} IN ({', '.join(str(int(y)) for y in years)})")
                if time_ctx.get('month'):
                    mexpr=f'EXTRACT(MONTH FROM {dexpr})' if dialect=='postgresql' else f'MONTH({dexpr})'; where.append(f'{mexpr} = {int(time_ctx["month"])}')
                if time_ctx.get('quarter'):
                    qexpr=f'EXTRACT(QUARTER FROM {dexpr})' if dialect=='postgresql' else f'QUARTER({dexpr})'; where.append(f'{qexpr} = {int(time_ctx["quarter"])}')
        joined={root}; joins=[]
        for step in (plan.get('join_plan',{}) or {}).get('joins',[]) or []:
            left,right=step.get('left'),step.get('right')
            if left not in aliases or right not in aliases: continue
            if left in joined and right not in joined: new=right
            elif right in joined and left not in joined: new=left
            elif left in joined and right in joined: continue
            else: continue
            cond=self._translate((step.get('condition') or '').replace('{left}',aliases[left]).replace('{right}',aliases[right]),dialect); joins.append(f'JOIN {self._quote_table(new,dialect)} {aliases[new]} ON {cond}'); joined.add(new)
        for rp in row_predicates or []:
            node=f"{rp.get('database')}.{rp.get('table')}" if rp.get('database') else rp.get('table'); alias=aliases.get(node)
            if alias and rp.get('expression'): where.append(str(rp['expression']).replace('{alias}',alias))
        if not select: return {'supported':False,'reasons':['empty_select'],'sql':None,'compiler':'governed_ast_v2','dialect':dialect}
        sql='SELECT\n  '+',\n  '.join(select)+f'\nFROM {self._quote_table(root,dialect)} {aliases[root]}'
        if joins: sql+='\n'+'\n'.join(joins)
        if where: sql+='\nWHERE\n  '+'\n  AND '.join(where)
        if group: sql+='\nGROUP BY '+', '.join(group)
        if group and mid:
            order_alias='record_count' if any(' AS record_count' in x for x in select) else mid
            sql+=f'\nORDER BY {order_alias} DESC'
        if plan.get('intent')=='breakdown' and not mid: sql+='\nLIMIT 500'
        return {'supported':True,'reasons':[],'sql':sql,'compiler':'governed_ast_v2','dialect':dialect,'tables':ordered,'metric':mid or 'record_count','dimensions':plan.get('group_dimensions',[]) or []}
