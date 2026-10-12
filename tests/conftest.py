"""7.0 tests build a synthetic runtime source; production data remains empty."""
import os, shutil, sqlite3, tempfile, atexit
from pathlib import Path

TEST_ROOT=Path(tempfile.mkdtemp(prefix='dip-regression-'))
atexit.register(shutil.rmtree, TEST_ROOT, ignore_errors=True)
TEST_STATE=str(TEST_ROOT/'state')
TEST_DB=TEST_ROOT/'test.db'
TEST_ROOT.mkdir(parents=True,exist_ok=True)
shutil.rmtree(TEST_STATE,ignore_errors=True)
try: TEST_DB.unlink()
except FileNotFoundError: pass

os.environ['APP_ENV']='development'
os.environ['APP_MODE']='local'
os.environ['ENABLE_SAMPLE_EXECUTION']='true'
os.environ['DATA_DIR']=str(Path(__file__).resolve().parents[1]/'data')
os.environ['STATE_DIR']=TEST_STATE
os.environ['POSTGRES_URL']=f"sqlite:///{TEST_DB.as_posix()}"
os.environ['ALLOW_DEV_IDENTITY_HEADERS']='true'
os.environ['CORS_ORIGINS']='http://localhost:3000'
os.environ['PERSIST_LOCAL_STATE']='true'
os.environ['ALLOW_SAMPLE_VALUES']='false'

conn=sqlite3.connect(str(TEST_DB))
conn.executescript('''
CREATE TABLE customers (
  customer_id INTEGER PRIMARY KEY,
  customer_name TEXT,
  email TEXT,
  region TEXT
);
CREATE TABLE orders (
  order_id INTEGER PRIMARY KEY,
  customer_id INTEGER,
  status TEXT,
  amount REAL,
  order_date TEXT,
  FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
);
INSERT INTO customers VALUES (1,'Acme','ops@example.test','west'),(2,'Nova','team@example.test','east');
INSERT INTO orders VALUES (101,1,'open',120.5,'2026-01-10'),(102,1,'closed',80.0,'2026-01-11'),(103,2,'open',50.0,'2026-02-01');
''')
conn.commit(); conn.close()

from fastapi import testclient as _testclient
_OriginalTestClient=_testclient.TestClient
class _StableClient:
    __test__=False
    def __init__(self,app,*args,**kwargs): self.app=app; self.args=args; self.kwargs=kwargs
    def request(self,method,url,**kwargs):
        with _OriginalTestClient(self.app,*self.args,**self.kwargs) as client: return client.request(method,url,**kwargs)
    def get(self,url,**kwargs): return self.request('GET',url,**kwargs)
    def post(self,url,**kwargs): return self.request('POST',url,**kwargs)
    def delete(self,url,**kwargs): return self.request('DELETE',url,**kwargs)
    def put(self,url,**kwargs): return self.request('PUT',url,**kwargs)
    def patch(self,url,**kwargs): return self.request('PATCH',url,**kwargs)
_testclient.TestClient=_StableClient

# Create the runtime workspace exactly through the production onboarding service.
from app.services.onboarding_service import OnboardingService
BOOTSTRAP=OnboardingService().bootstrap_source('postgres','test-lab','Test Analytics',['main'],discover_relationships=True)

# Live-provider contract fixtures; model output is explicitly mocked for tests.
from governed_fixtures import business, bedrock_contract
