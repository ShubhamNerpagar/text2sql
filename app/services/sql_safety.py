"""Conservative statement checks in addition to the typed, allowlisted compiler."""
import re
_ALLOWED_PREFIXES=('SELECT','WITH','SHOW','DESCRIBE','EXPLAIN')
_BLOCKED=re.compile(r'\b(INSERT|UPDATE|DELETE|MERGE|DROP|CREATE|ALTER|TRUNCATE|UNLOAD|CALL|GRANT|REVOKE|MSCK|VACUUM|OPTIMIZE)\b',re.I)


def strip_sql_fences(sql:str)->str:
    text=(sql or '').strip()
    if text.startswith('```'):
        text=re.sub(r'^```(?:sql)?\s*','',text,flags=re.I)
        text=re.sub(r'\s*```$','',text)
    return text.strip().rstrip(';').strip()


def statement_text(sql):
    """Mask quoted values/identifiers and comments before inspecting SQL tokens."""
    out=[];i=0
    while i<len(sql):
        char=sql[i]
        if char in {'\'','"','`'}:
            quote=char;i+=1
            while i<len(sql):
                if sql[i]==quote:
                    if i+1<len(sql) and sql[i+1]==quote:i+=2;continue
                    i+=1;break
                i+=1
            else:raise ValueError('Unterminated SQL quote')
            out.append(' ')
        elif sql[i:i+2]=='--':
            end=sql.find('\n',i+2);i=len(sql) if end<0 else end+1;out.append(' ')
        elif sql[i:i+2]=='/*':
            end=sql.find('*/',i+2)
            if end<0:raise ValueError('Unterminated SQL comment')
            i=end+2;out.append(' ')
        else:out.append(char);i+=1
    return ''.join(out)


def validate_read_only_sql(sql:str)->tuple[bool,str]:
    text=strip_sql_fences(sql)
    if not text:return False,'No SQL was generated.'
    try:tokens=statement_text(text)
    except ValueError as exc:return False,str(exc)
    if ';' in tokens:return False,'Multiple SQL statements are not allowed.'
    if not re.match(r'^\s*(?:'+ '|'.join(_ALLOWED_PREFIXES)+r')\b',tokens,re.I):
        return False,'Only SELECT/WITH/SHOW/DESCRIBE/EXPLAIN statements are allowed.'
    if _BLOCKED.search(tokens):return False,'The SQL contains a write or DDL operation and was blocked.'
    return True,'OK'
