"""Typed business definitions. No SQL strings are accepted as executable semantics."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

AGGREGATIONS = {'sum', 'avg', 'min', 'max', 'count', 'count_distinct', 'ratio'}
COMPARISONS = {'eq', 'ne', 'gt', 'gte', 'lt', 'lte', 'in', 'between', 'is_null', 'not_null'}


def scalar_value(value):
    if type(value)==bool:return
    if type(value) in (int,float) and math.isfinite(value) and abs(value)<=10**15:return
    if isinstance(value,str) and len(value)<=120 and '\x00' not in value:return
    raise ValueError('Business predicate values must be finite typed scalars')


def expression_columns(expression, depth=0):
    if depth > 8 or not isinstance(expression, dict):
        raise ValueError('Business expression must be a bounded structured object')
    if set(expression) == {'column'} and isinstance(expression['column'], str):
        return {expression['column']}
    if set(expression) == {'literal'}:
        value = expression['literal']
        if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 10**15:
            raise ValueError('Expression constants must be finite numbers')
        return set()
    if set(expression) != {'op', 'args'} or expression['op'] not in {'add', 'subtract', 'multiply', 'divide', 'coalesce'}:
        raise ValueError('Unsupported business expression; raw SQL is prohibited')
    args = expression['args']
    if not isinstance(args, list) or len(args) != 2:
        raise ValueError('Business expression operators require two arguments')
    return set().union(*(expression_columns(x, depth + 1) for x in args))


def expression_sql(expression, reference):
    expression_columns(expression)
    if 'column' in expression:
        return reference(expression['column'])
    if 'literal' in expression:
        return str(expression['literal'])
    left, right = [expression_sql(x, reference) for x in expression['args']]
    op = expression['op']
    if op == 'coalesce':
        return f'COALESCE({left}, {right})'
    if op == 'divide':
        return f'(1.0 * {left} / NULLIF({right}, 0))'
    return f'({left} '+{'add': '+', 'subtract': '-', 'multiply': '*'}[op]+f' {right})'


def validate_semantics(kind, semantics, binding, metadata=None):
    """Validate author input and return its canonical representation.

    Empty definitions may be saved as drafts. Certification separately requires an
    executable measure definition; prose is never translated into a formula.
    """
    s = deepcopy(semantics or {})
    if not isinstance(s, dict):
        raise ValueError('semantics must be a structured object')
    if not s:
        return s
    allowed = {'grain', 'aggregation', 'expression', 'numerator', 'denominator',
               'unit', 'additivity', 'filters', 'time', 'value_mappings', 'weight_column'}
    if set(s) - allowed:
        raise ValueError('Unknown executable semantic fields')
    columns = set(binding.get('columns', []))
    grain = s.get('grain', [])
    if not isinstance(grain, list) or not grain or len(grain) != len(set(grain)) or not set(grain) <= columns:
        if kind in {'measure', 'entity', 'event'}:
            raise ValueError('Declare a nonempty grain using bound columns')
    if kind == 'measure':
        aggregation = s.get('aggregation')
        if aggregation not in AGGREGATIONS:
            raise ValueError('Declare an approved aggregation')
        required = set();numeric = set()
        if aggregation == 'ratio':
            for name in ('numerator', 'denominator'):
                part = s.get(name, {})
                if set(part) != {'aggregation', 'expression'} or part['aggregation'] not in {'sum', 'count_distinct'}:
                    raise ValueError('Ratios require structured sum/distinct-count numerator and denominator')
                required |= expression_columns(part['expression'])
                if part['aggregation']=='sum':numeric |= expression_columns(part['expression'])
        elif aggregation != 'count':
            required |= expression_columns(s.get('expression'))
            if aggregation!='count_distinct':numeric |= required
        if not required <= columns:
            raise ValueError('Every formula column must be explicitly bound and certified')
        if s.get('additivity') not in {'additive', 'semi_additive', 'non_additive'}:
            raise ValueError('Declare metric additivity')
        if not isinstance(s.get('unit'), str) or not s['unit'].strip():
            raise ValueError('Declare the metric unit, e.g. USD, records, percent')
        if aggregation == 'sum' and s['additivity'] != 'additive':
            raise ValueError('SUM requires an additive metric; snapshots and ratios cannot be summed')
        if aggregation in {'avg', 'ratio', 'count_distinct'} and s['additivity'] != 'non_additive':
            raise ValueError('Averages, ratios and distinct counts must be non_additive')
        if aggregation == 'avg' and s.get('weight_column'):
            if s['weight_column'] not in columns:
                raise ValueError('Average weight column must be bound')
        if metadata:
            types = {c['name']:str(c.get('type', '')).lower() for c in metadata['columns']}
            if aggregation not in {'count', 'count_distinct'}:
                for c in numeric | ({s['weight_column']} if s.get('weight_column') else set()):
                    if not any(t in types[c] for t in ('int', 'real', 'numeric', 'decimal', 'float', 'double', 'number')):
                        raise ValueError('Arithmetic and numeric aggregates require numeric columns')
    filters = s.get('filters', [])
    if not isinstance(filters, list) or len(filters) > 20:
        raise ValueError('At most 20 required business filters are supported')
    for f in filters:
        if not isinstance(f, dict) or set(f) - {'asset_id', 'column', 'op', 'value'} or f.get('op') not in COMPARISONS:
            raise ValueError('Business filters must be typed predicates')
        if binding.get('asset_id') and f.get('asset_id', binding['asset_id']) != binding['asset_id']:
            raise ValueError('Business predicates must bind to their own scoped asset')
        if f.get('column') not in columns:
            raise ValueError('Business predicate columns must be bound')
        if f['op'] not in {'is_null','not_null'}:
            value=f.get('value')
            if f['op'] in {'in','between'}:
                if not isinstance(value,list) or not 1<=len(value)<=20 or (f['op']=='between' and len(value)!=2):
                    raise ValueError('Invalid business predicate bounds')
                for v in value:scalar_value(v)
            else:scalar_value(value)
    if kind in {'business_concept', 'rule'} and not filters:
        raise ValueError('Executable concepts and rules require bound predicates')
    if s.get('time'):
        t = s['time']
        if not isinstance(t, dict) or set(t) - {'column', 'timezone', 'calendar', 'role'}:
            raise ValueError('Invalid metric time semantics')
        if t.get('column') not in columns or t.get('calendar', 'gregorian') != 'gregorian':
            raise ValueError('Bind a time column; unsupported calendars must be refused')
        if metadata:
            c=next(c for c in metadata['columns'] if c['name']==t['column'])
            if not any(x in (str(c.get('type',''))+' '+c['name']).lower() for x in ('date','time')):
                raise ValueError('Time roles require a temporal column')
        try:ZoneInfo(t.get('timezone', 'UTC'))
        except (ZoneInfoNotFoundError,TypeError):raise ValueError('Unknown business timezone') from None
    mappings = s.get('value_mappings', {})
    if not isinstance(mappings, dict) or any(c not in columns or not isinstance(v, dict) for c,v in mappings.items()):
        raise ValueError('Value mappings must identify bound columns and named codes')
    for values in mappings.values():
        if len(values)>100:raise ValueError('At most 100 named codes per bound column')
        for name,value in values.items():
            if not isinstance(name,str) or not 1<=len(name)<=120:raise ValueError('Invalid business value name')
            scalar_value(value)
    return s


def is_fresh(evidence, seconds=86400):
    try:
        at = datetime.fromisoformat(evidence['evaluated_at'])
        age = (datetime.now(timezone.utc) - at).total_seconds()
        return at.tzinfo is not None and 0 <= age <= seconds
    except (ValueError, KeyError, TypeError):
        return False
