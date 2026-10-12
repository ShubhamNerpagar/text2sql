"""Opt-in Chromium UI smoke with real in-process FastAPI, no cloud dependencies.
Run: python tools/smoke_phase4_chromium.py
Requires playwright and Chromium executable; not needed to run the application.
"""
import os, sys, json
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import app
from app.services.scope_service import ScopeService
from app.services.phase2_service import Phase2Service
from app.services.phase3_service import Phase3Service
from app.services.phase4_service import Phase4Service

workspace='phase4-ui-'+uuid4().hex[:9]
s={'scope_id':workspace+'-scope','workspace_id':workspace,'display_name':'Phase 4 Visual Acceptance','source_id':'contoso',
   'tables':[{'database':'contoso_demo','table':'Orders'}]}
ScopeService().save(s);ScopeService().build(s['scope_id'])
p2=Phase2Service();asset=p2.assets(workspace)[0]
p2.profile(workspace,asset['asset_id'],'standard','ui-author',200)
p2.save_contract(workspace,asset['asset_id'],{'owner':'test-steward'},'ui-author')
p2.transition_contract(workspace,asset['asset_id'],'reviewed','Physical source reviewed','ui-author')
p2.transition_contract(workspace,asset['asset_id'],'certified','Measures and schema verified','ui-author')
p3=Phase3Service();obj=p3.create(workspace,{'kind':'entity','label':'Orders','description':'Orders business entity',
    'binding':{'asset_id':asset['asset_id'],'columns':['OrderKey']}},'ui-author')
obj=p3.transition(workspace,obj['object_id'],'reviewed','Qualified evidence and semantics','ui-author',obj['version'])
obj=p3.transition(workspace,obj['object_id'],'certified','Independent steward approval','ui-reviewer',obj['version'])
p3.publish_snapshot(workspace,'smoke-1','Evidence confirmed for release','ui-reviewer')
Phase4Service().promote(workspace,'smoke-1','ui-reviewer')
root=Path(__file__).resolve().parents[1]/'app/static/assets'
js=(root/'app.js').read_text().replace('localStorage.getItem','window.testLocalStorage.getItem').replace('localStorage.setItem','window.testLocalStorage.setItem')
css=(root/'app.css').read_text()
client=TestClient(app);statuses=[];errors=[]
def proxy(_source,uri,options):
    r=client.request(options.get('method','GET'),uri,content=options.get('body'),headers=options.get('headers') or {})
    statuses.append((r.status_code,uri))
    try:v=r.json()
    except Exception:v={'detail':r.text}
    return {'status':r.status_code,'body':v}
with sync_playwright() as runner:
    binary=os.environ.get('CHROMIUM_PATH') or '/usr/bin/chromium'
    browser=runner.chromium.launch(headless=True,executable_path=binary,args=['--no-sandbox','--disable-dev-shm-usage'])
    page=browser.new_page(viewport={'width':1560,'height':1030},device_scale_factor=1)
    page.on('pageerror',lambda err:errors.append(str(err)))
    page.expose_binding('phase4Backend',proxy)
    page.set_content('<html><head><style>'+css+'</style></head><body><div id="app"></div><div id="overlay"></div></body></html>')
    page.evaluate('''(()=>{window.testLocalStorage={getItem:k=>k==='dip-role'?'semantic_admin':null,setItem:()=>{}};
       window.fetch=async(uri,options={})=>{const r=await window.phase4Backend(uri,options);
       return new Response(JSON.stringify(r.body),{status:r.status,headers:{'Content-Type':'application/json'}})};})()''')
    page.add_script_tag(content=js)
    page.wait_for_timeout(700)
    page.locator('#marketSelect').select_option(workspace)
    page.locator('[data-section="semantics"]').click()
    page.locator('[data-tab="governed-ask"]').click();page.wait_for_timeout(500)
    assert page.locator('#p4-release').input_value()=='p3-smoke-1'
    assert page.locator('#view .notice.error').count()==0
    page.locator('#p4-plan').click();page.wait_for_timeout(470)
    assert 'Read-only aggregate SQL' in page.locator('#view').inner_text()
    page.locator('#p4-execute').click();page.wait_for_timeout(560)
    assert '10,000' in page.locator('#view').inner_text()
    image_dir=Path(__file__).resolve().parents[1]/'validation_screenshots'
    image_dir.mkdir(exist_ok=True)
    page.screenshot(path=str(image_dir/'phase4_governed_ask.png'),full_page=True)
    page.locator('[data-tab="golden"]').click();page.wait_for_timeout(370)
    page.locator('#p4-case-question').fill('Count Orders')
    page.locator('#p4-case-object').fill(obj['object_id'])
    page.locator('#p4-case-save').click();page.wait_for_timeout(430)
    assert 'Count Orders' in page.locator('#view').inner_text()
    page.locator('#p4-suite-run').click();page.wait_for_timeout(480)
    assert '100%' in page.locator('#view').inner_text()
    page.screenshot(path=str(image_dir/'phase4_golden_tests.png'),full_page=True)
    page.locator('[data-tab="ontology-releases"]').click();page.wait_for_timeout(420)
    assert page.locator('#p4-branch-create').count()==1
    page.screenshot(path=str(image_dir/'phase4_release_manager.png'),full_page=True)
    page.locator('[data-tab="impact-agent"]').click();page.wait_for_timeout(360)
    page.locator('#p4-impact').click();page.wait_for_timeout(360)
    assert 'physical_asset' in page.locator('#view').inner_text()
    page.locator('#p4-tool-call').click();page.wait_for_timeout(370)
    assert 'release_id' in page.locator('#view').inner_text()
    assert not errors,errors
    assert not page.locator('#view .notice.error').count()
    assert not [x for x in statuses if x[0]>=400], [x for x in statuses if x[0]>=400]
    print(json.dumps({'passed':True,'workspace':workspace,'api_requests':len(statuses),'api_failures':0,
        'javascript_errors':errors,'screenshots':[str(x) for x in image_dir.glob('*.png')]},indent=2))
    browser.close()
