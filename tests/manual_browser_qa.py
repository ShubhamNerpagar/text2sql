from pathlib import Path
import os,sys,json,re,time,shutil,traceback
B=Path(__file__).resolve().parents[1]
OUT=B/'qa-artifacts'
OUT.mkdir(exist_ok=True)
shutil.rmtree(OUT/'state',ignore_errors=True)
os.environ.update({'APP_ENV':'development','APP_MODE':'local','DATA_DIR':str(B/'data'),'STATE_DIR':str(OUT/'state'),'PERSIST_LOCAL_STATE':'true','ALLOW_DEV_IDENTITY_HEADERS':'true','POSTGRES_URL':'','ALLOW_SAMPLE_VALUES':'false'})
sys.path.insert(0,str(B))
from app.main import app
from app.services.scope_service import ScopeService
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
W='qa-contoso-sidebar'
sc={'scope_id':W+'-scope','workspace_id':W,'display_name':'Contoso QA workspace','source_id':'contoso','tables':[{'database':'contoso_demo','table':t} for t in ('Orders','Customer','Store','OrderRows','Product')]}
s=ScopeService()
try:s.save(sc)
except ValueError as e:print('scope existing',e)
try:r=s.build(sc['scope_id']);print('seeded',r.get('tables_scanned'))
except Exception as e:print('seed error',type(e).__name__,str(e)[:200])
client=TestClient(app)
results=[];calls=[];errors=[];console=[]
print('starting browser',flush=True)

def backend(req):
 method=req.get('method','GET');path=req['url'];headers={'X-Roles':'semantic_admin','X-User':'local-ui',**(req.get('headers') or {})};headers={k:v for k,v in headers.items() if isinstance(v,str)}
 try:
  kw={'headers':headers};body=req.get('body');
  if body is not None and body!='':kw['content']=body
  response=client.request(method,path,**kw)
  status=response.status_code;text=response.text
 except Exception as e:
  status=599;text=json.dumps({'detail':'QA bridge: '+str(e)})
 calls.append({'status':status,'path':path,'method':method})
 return {'status':status,'body':text}

with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
 page=browser.new_page(viewport={'width':1512,'height':950},device_scale_factor=1)
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.on('console',lambda m:console.append(m.text) if m.type=='error' else None)
 page.set_default_timeout(6000)
 page.set_content('<!DOCTYPE html><html><head><title>Data Intelligence QA</title></head><body><div id="app">Starting</div></body></html>')
 page.expose_function('__sidebar_backend',backend)
 page.evaluate('''() => {const mem = {};Object.defineProperty(window,'localStorage',{value:{getItem:k=>mem[k]??null,setItem:(k,v)=>mem[k]=String(v),removeItem:k=>delete mem[k]}});window.fetch=async(url,opts={})=>{let b=await window.__sidebar_backend({url:String(url),method:opts.method||'GET',body:opts.body||null,headers:opts.headers||{}});return new Response(b.body,{status:b.status,headers:{'Content-Type':'application/json'}})}}''')
 page.add_style_tag(content=(B/'app/static/assets/app.css').read_text())
 page.add_script_tag(content=(B/'app/static/assets/app.js').read_text())
 page.wait_for_function("!!document.querySelector('[data-section=home]')",timeout=15000)
 page.wait_for_function("!document.querySelector('#view .loading')",timeout=15000)
 page.screenshot(path=str(OUT/'sidebar_home.png'),full_page=True)
 def wait():
  try:page.wait_for_function("!document.querySelector('#view .loading')",timeout=18000)
  except Exception:return 'load_timeout'
  return 'loaded'
 def check(section,tab=None):
  print('PAGE',section,tab,'requests',len(calls),flush=True)
  before=len(calls);beforeErr=len(errors)
  try:
   if tab is None:page.locator(f'[data-section="{section}"]').click(timeout=4000)
   else:
    # expands group if necessary
    b=page.locator(f'[data-tab="{tab}"][data-parent="{section}"]')
    if not b.is_visible():page.locator(f'[data-section="{section}"]').click(timeout=4000)
    b.click(timeout=4000)
   state=wait()
   content=page.locator('#view').inner_text(timeout=3000)
   errorsUI=page.locator('#view .notice.error').all_inner_texts()
   internal=[x for x in calls[before:] if x['status']>=500]
   forbidden=bool(re.search(r'\bphases?\b',page.locator('#view').inner_text()+' '+page.locator('.top-breadcrumb').inner_text(),flags=re.I))
   cloud_warn=(section=='admin' and tab=='ai-models' and any('Unable to locate credentials' in x for x in errorsUI))
   outcome='pass_with_external_warning' if cloud_warn and state=='loaded' and not internal and len(errors)==beforeErr and not forbidden else ('pass' if state=='loaded' and not errorsUI and not internal and len(errors)==beforeErr and not forbidden else 'fail')
   print('RESULT',section,tab,outcome,'requests',len(calls),flush=True)
   results.append({'section':section,'tab':tab,'result':outcome,'loading':state,'ui_errors':errorsUI[:2],'api_5xx':internal[:3],'page_errors':errors[beforeErr:],'stage_word_visible':forbidden,'preview':content[:100]})
  except Exception as e:
   print('ERROR PAGE',section,tab,str(e)[:180],flush=True)
   results.append({'section':section,'tab':tab,'result':'fail','error':str(e)[:350]})
 check('ask');check('home')
 groups={
  'reports':['dashboards','lineage'],
  'data':['estate','catalog','profile','contracts','evidence','quality','pipeline','sources'],
  'semantics':['model','ontology','trust','questions','ontology-graph','governed-ask','plan-lab','golden','ontology-releases','impact-agent','studio','graph','relationships','governance','branches'],
  'operate':['job-center','federation','enterprise-search','connector-bench','readiness'],
  'monitor':['overview','evaluation','queries','audit'],
  'admin':['onboarding','ai-models','actions','tools','settings']
 }
 for section,tabs in groups.items():
  for tab in tabs:
   check(section,tab)
   if section=='data' and tab=='profile':page.screenshot(path=str(OUT/'sidebar_data_profiling.png'),full_page=True)
   if section=='semantics' and tab=='ontology':page.screenshot(path=str(OUT/'sidebar_ontology_studio.png'),full_page=True)
   if section=='operate' and tab=='job-center':page.screenshot(path=str(OUT/'sidebar_job_center.png'),full_page=True)
 # critical interactions (safe and limited scope)
 flows=[]
 def settle():
  page.wait_for_timeout(900);wait()
 def flow(name,fn):
  before=len(errors);start=len(calls)
  try:
   fn();wait(); bad=[x for x in calls[start:] if x['status']>=400]
   flows.append({'flow':name,'result':'pass' if len(errors)==before and not bad else 'fail','api_failures':bad,'errors':errors[before:]})
  except Exception as e:
   print('FAILED FLOW',name,repr(e),flush=True)
   flows.append({'flow':name,'result':'fail','error':repr(e)[:400],'trace':traceback.format_exc(limit=3)[:500]})
 def profile():
  page.locator('[data-tab="profile"]').click();wait();page.locator('#p2-profile-run').click();wait();page.wait_for_timeout(300)
 def contract():
  page.locator('[data-tab="contracts"]').click();wait()
  page.locator('#p2-owner').fill('QA Data Steward')
  page.locator('#p2-contract-save').click();settle()
  page.locator('#p2-contract-note').fill('QA reviewed measured physical metadata')
  page.locator('.p2-contract-transition[data-transition="reviewed"]').click();settle()
  page.locator('#p2-contract-note').fill('QA certified measured physical schema')
  page.locator('.p2-contract-transition[data-transition="certified"]').click();settle()
  assert 'certified' in page.locator('#view').inner_text()
 def quality():
  page.locator('[data-tab="quality"]').click();wait()
  page.locator('#p2-rule-type').select_option('row_count_min')
  page.locator('#p2-rule-threshold').fill('1')
  page.locator('#p2-rule-desc').fill('QA minimum row count')
  page.locator('#p2-rule-create').click();settle()
  assert page.locator('#p2-quality-run').is_enabled()
  page.locator('#p2-quality-run').click();settle()
  assert page.locator('#view').get_by_text('Passed').count()>0
 def relationships():
  page.locator('[data-tab="evidence"]').click();wait()
  b=page.locator('.p2-rel-validate').first
  assert b.count()>0,'No relationship candidates'
  b.click();settle()
  assert 'coverage' in page.locator('#view').inner_text().lower()
 def proposals():
  page.locator('[data-tab="ontology"]').click();wait()
  page.locator('#p3-propose').click();settle()
  assert page.locator('#view').get_by_text('Workspace ontology').count()>0
 def graph_modes():
  page.locator('[data-tab="ontology-graph"]').click();wait()
  for mode in ('conceptual','logical','evidence','dependency'):
   page.locator(f'.p3-mode[data-mode="{mode}"]').click();wait()
   assert page.locator('.p3-graph-wrap svg').count()==1
 def enqueue():
  page.locator('[data-tab="job-center"]').click();wait();page.locator('#p5-enqueue').click();wait()
  from app.workers.phase5_worker import process_one
  from app.services.phase5_service import Phase5Service
  result=process_one(Phase5Service(),'qa-windows-worker')
  assert result and result['status']=='succeeded'
  page.locator('#p5-refresh').click();wait()
  assert 'succeeded' in page.locator('#view').inner_text()
 def search():
  page.locator('[data-tab="enterprise-search"]').click();wait();page.locator('#p5-search').click();wait()
 def global_search():
  page.locator('#globalSearch').click()
  page.locator('#searchInput').fill('Orders')
  page.wait_for_timeout(500)
  assert page.locator('.search-result').count()>0
  page.locator('.search-result').first.click();wait()
  assert not page.locator('.search-modal').count()
  assert page.locator('.nav-child.active').count()==1
 def sidebar():
  page.locator('[data-section="data"]').click()
  assert page.locator('[data-tab="catalog"]').is_visible()
  page.locator('[data-tab="profile"]').click();wait()
  page.locator('[data-section="data"]').click()
  assert not page.locator('[data-tab="catalog"]').is_visible()
  page.locator('[data-section="data"]').click()
  assert page.locator('[data-tab="catalog"]').is_visible()
  assert page.locator('[data-tab="profile"]').get_attribute('aria-current')=='page'
  page.locator('[data-tab="catalog"]').click();wait()
  assert page.locator('[data-tab="catalog"]').get_attribute('aria-current')=='page'
 def collapse():
  page.locator('#toggleSidebar').click();assert page.locator('.app-shell').evaluate('(n)=>n.classList.contains("sidebar-collapsed")')
  page.locator('#toggleSidebar').click();assert not page.locator('.app-shell').evaluate('(n)=>n.classList.contains("sidebar-collapsed")')
 for f,fn in [('profiling',profile),('contract_certification',contract),('quality_create_and_run',quality),('relationship_measurement',relationships),('ontology_candidate_generation',proposals),('ontology_graph_modes',graph_modes),('job_enqueue_worker_execute',enqueue),('enterprise_search',search),('global_search_result_navigation',global_search),('group_expansion',sidebar),('collapse_expand',collapse)]:
  print('FLOW',f,flush=True)
  flow(f,fn)
 # mobile viewport
 page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300)
 mobile={'horizontal_overflow':page.evaluate('document.documentElement.scrollWidth > innerWidth'),'nav_visible':page.locator('.sidebar-nav').is_visible()}
 page.screenshot(path=str(OUT/'sidebar_mobile.png'),full_page=True)
 browser.close()
report={'count':len(results),'passed':sum(x['result']=='pass' for x in results),'external_warning':sum(x['result']=='pass_with_external_warning' for x in results),'failed':sum(x['result']=='fail' for x in results),'page_results':results,'flows':flows,'javascript_errors':errors,'console_errors':console[:30],'requests':len(calls),'status_counts':{str(s):sum(1 for x in calls if x['status']==s) for s in sorted(set(x['status'] for x in calls))},'mobile':mobile}
(OUT/'browser_qa.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items() if k not in ['page_results','console_errors']},indent=2))
print('PAGE FAILURES',json.dumps([x for x in results if x['result']=='fail'],indent=2))
