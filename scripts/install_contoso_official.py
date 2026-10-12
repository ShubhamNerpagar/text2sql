"""Download the official SQLBI CSV 10K release and import a new typed dataset."""
from __future__ import annotations
import hashlib,json,re,sys,urllib.request
from html.parser import HTMLParser
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.services.contoso_import_service import import_archive

DEST=ROOT/'sample-data'/'contoso'
API='https://api.github.com/repos/sql-bi/Contoso-Data-Generator-V2-Data/releases/tags/ready-to-use-data'
RELEASE_HTML='https://github.com/sql-bi/Contoso-Data-Generator-V2-Data/releases/expanded_assets/ready-to-use-data'
RELEASE_PATH='/sql-bi/Contoso-Data-Generator-V2-Data/releases/download/ready-to-use-data/'


def download_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'DIP-Contoso-Installer','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=60) as response:return json.load(response)


class ReleaseAssets(HTMLParser):
    def __init__(self):
        super().__init__();self.assets={};self.digests={}
    def handle_starttag(self,tag,attributes):
        attrs=dict(attributes)
        if tag=='a':
            href=attrs.get('href','')
            if href.startswith(RELEASE_PATH):
                name=href.removeprefix(RELEASE_PATH)
                if re.fullmatch(r'csv-10k\.7z',name,re.I):self.assets[name]='https://github.com'+href
        if tag=='clipboard-copy':
            label=attrs.get('aria-label','');digest=attrs.get('value','')
            prefix='Copy to clipboard digest for '
            if label.startswith(prefix) and re.fullmatch(r'sha256:[a-fA-F0-9]{64}',digest):self.digests[label.removeprefix(prefix)]=digest


def release_asset():
    try:
        release=download_json(API)
        assets=[a for a in release.get('assets',[]) if re.fullmatch(r'csv-10k\.7z',a.get('name',''),re.I)]
        if len(assets)!=1:raise ValueError('Expected exactly one official CSV 10K release asset')
        return assets[0]
    except (OSError,ValueError):
        # Some environments allow public GitHub pages but deny api.github.com.
        # The public release page supplies the same URL and published SHA-256.
        req=urllib.request.Request(RELEASE_HTML,headers={'User-Agent':'DIP-Contoso-Installer'})
        with urllib.request.urlopen(req,timeout=60) as response:html=response.read(2*1024*1024+1)
        if len(html)>2*1024*1024:raise ValueError('Release listing exceeds size limit')
        parser=ReleaseAssets();parser.feed(html.decode('utf-8'))
        if len(parser.assets)!=1:raise ValueError('Cannot identify official CSV 10K download')
        name,url=next(iter(parser.assets.items()))
        if name not in parser.digests:raise ValueError('Official release page did not provide an archive checksum')
        return {'name':name,'browser_download_url':url,'digest':parser.digests[name]}


def download_asset(asset,destination):
    name=asset['name'];url=asset['browser_download_url']
    if not re.fullmatch(r'csv-10k\.7z',name,re.I) or not url.startswith('https://github.com'+RELEASE_PATH):
        raise ValueError('Unexpected official release asset URL')
    digest=asset.get('digest') or ''
    expected=digest.split(':',1)[1] if re.fullmatch(r'sha256:[a-fA-F0-9]{64}',digest) else None
    destination.mkdir(parents=True,exist_ok=True)
    path=destination/name;temp=path.with_suffix('.partial')
    req=urllib.request.Request(url,headers={'User-Agent':'DIP-Contoso-Installer'})
    h=hashlib.sha256();size=0
    try:
        with urllib.request.urlopen(req,timeout=120) as remote,open(temp,'wb') as local:
            length=remote.headers.get('Content-Length')
            while data:=remote.read(1024*1024):
                size+=len(data)
                if size>300*1024*1024:raise ValueError('Archive exceeds the 300 MiB size cap')
                h.update(data);local.write(data)
        if (asset.get('size') is not None and size!=asset['size']) or (length and size!=int(length)):
            raise ValueError('Incomplete official archive')
        if expected and h.hexdigest()!=expected.lower():raise ValueError('Official asset SHA-256 mismatch')
        temp.replace(path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return path,expected


def main():
    if (DEST/'contoso_official.sqlite3').exists():raise SystemExit('contoso_official already exists; use a new dataset ID for a reviewed migration')
    asset=release_asset()
    print('Downloading official SQLBI archive:',asset['name'])
    path,expected=download_asset(asset,DEST)
    manifest=import_archive(path,'contoso_official',DEST,expected_sha256=expected,
        provenance='SQLBI Contoso-Data-Generator-V2-Data; ready-to-use-data; '+asset['browser_download_url'])
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError) as exc:raise SystemExit('Official Contoso installation failed: '+str(exc))
