"""Install official SQLBI Contoso V2 CSV 10K sample ON THE USER'S MACHINE.
Requires outbound GitHub access and py7zr. The archive stays under sample-data/contoso.
"""
from __future__ import annotations
import csv,hashlib,json,re,sqlite3,sys,urllib.request
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'sample-data'/'contoso'; DEST.mkdir(parents=True,exist_ok=True)
API='https://api.github.com/repos/sql-bi/Contoso-Data-Generator-V2-Data/releases/tags/ready-to-use-data'
def download_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'DIP-Contoso-Installer','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=60) as f:return json.load(f)
def ident(s):
    cleaned=re.sub('[^A-Za-z0-9_]','_',s.strip()).strip('_')[:62]
    return cleaned if cleaned and not cleaned[0].isdigit() else 'T_'+cleaned
def main():
    try: import py7zr
    except ImportError: raise SystemExit('Missing py7zr. Run: python -m pip install py7zr')
    rel=download_json(API)
    assets=[a for a in rel.get('assets',[]) if a['name'].lower().startswith('csv-') and re.search(r'10k',a['name'],flags=re.I) and a['name'].lower().endswith('.7z')]
    if len(assets)!=1:raise SystemExit(f'Expected exactly one official 10K CSV asset, got: {[a["name"] for a in assets]}')
    a=assets[0];name=a['name'];url=a['browser_download_url']
    print('Downloading official SQLBI archive:',name,'size',a['size'])
    path=DEST/name; temp=path.with_suffix('.partial')
    req=urllib.request.Request(url,headers={'User-Agent':'DIP-Contoso-Installer'})
    h=hashlib.sha256();size=0
    with urllib.request.urlopen(req,timeout=120) as remote,open(temp,'wb') as local:
        while data:=remote.read(1024*1024):
            size+=len(data)
            if size>300*1024*1024:raise SystemExit('Archive exceeds the 300MB size cap')
            h.update(data);local.write(data)
    if size!=a['size']:raise SystemExit(f'Incomplete official archive: {size} bytes vs {a["size"]}')
    digest=a.get('digest') or ''
    if digest.startswith('sha256:') and h.hexdigest()!=digest.split(':',1)[1]:raise SystemExit('Official asset SHA-256 mismatch')
    temp.replace(path)
    extracted=DEST/'official_csv';extracted.mkdir(exist_ok=True)
    with py7zr.SevenZipFile(path,mode='r') as z:
        names=z.getnames()
        if any(Path(n).is_absolute() or '..' in Path(n).parts for n in names):raise SystemExit('Unsafe archive path rejected')
        z.extractall(path=extracted)
    csvs=sorted(extracted.rglob('*.csv'))
    if not csvs:raise SystemExit('No CSV files in official release')
    out=DEST/'contoso_official.tmp.sqlite3';out.unlink(missing_ok=True)
    loaded={}
    with sqlite3.connect(out) as db:
        for p in csvs:
            table=ident(p.stem)
            if table in loaded:raise SystemExit('Duplicate CSV table stem: '+table)
            with p.open(encoding='utf-8-sig',newline='',errors='replace') as f:
                probe=f.read(4096);f.seek(0)
                try:dialect=csv.Sniffer().sniff(probe,delimiters=',;\t|')
                except csv.Error:dialect=csv.excel
                reader=csv.reader(f,dialect)
                headers=next(reader,None)
                if not headers:continue
                columns=[ident(h) for h in headers]
                if len(set(columns))!=len(columns):raise SystemExit('Duplicate CSV column identifiers: '+str(p))
                q=lambda x:'"'+x.replace('"','""')+'"'
                db.execute(f'CREATE TABLE {q(table)} ('+', '.join(q(c)+' TEXT' for c in columns)+')')
                statement=f'INSERT INTO {q(table)} VALUES('+','.join('?' for _ in columns)+')'
                batch=[];cnt=0
                for row in reader:
                    if len(row)!=len(columns):continue
                    batch.append(row);cnt+=1
                    if len(batch)>=2000:db.executemany(statement,batch);batch.clear()
                if batch:db.executemany(statement,batch)
                loaded[table]=cnt
    if not loaded:raise SystemExit('No tables loaded')
    out.replace(DEST/'contoso_official.sqlite3')
    manifest={'source':'SQLBI Contoso-Data-Generator-V2-Data','release_tag':'ready-to-use-data','asset':name,'asset_url':url,'archive_sha256':h.hexdigest(),'installed_at':datetime.now(timezone.utc).isoformat(),'rows_per_table':loaded,'note':'Columns imported as TEXT to preserve all source values; Phase 2 will infer physical types.'}
    (DEST/'official-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Installed',len(loaded),'official SQLBI tables into',DEST/'contoso_official.sqlite3')
if __name__=='__main__':main()
