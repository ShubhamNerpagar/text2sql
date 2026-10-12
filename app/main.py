from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.config import get_settings, validate_production_config
from app.api.routes import router
from app.models import MCPRequest
from app.services.mcp_service import MCPService
from app.services.security_service import SecurityService
from app.services.telemetry_service import configure_telemetry

s=get_settings()
validate_production_config(s)
app=FastAPI(title=s.app_name,version="8.4.0",docs_url=None if s.is_production else "/api/docs",openapi_url=None if s.is_production else "/api/openapi.json")
app.add_middleware(CORSMiddleware,allow_origins=list(s.cors_origins),allow_credentials=False,allow_methods=["GET","POST","DELETE","OPTIONS"],allow_headers=["Content-Type","Authorization","X-User","X-Roles",s.trusted_roles_header,"X-Market","X-Workspace","X-Amzn-Oidc-Data","X-Amzn-Oidc-Identity"])
app.include_router(router)
telemetry_status=configure_telemetry(app)
static=Path(__file__).resolve().parent/"static"
app.mount("/assets",StaticFiles(directory=static/"assets"),name="assets")

mcp_service=MCPService(); security_service=SecurityService()

@app.middleware('http')
async def production_perimeter(request: Request, call_next):
    """All production API/MCP traffic is authenticated, including legacy routes.

    Access to the EC2 instance must also be restricted to the trusted ALB security
    group: clients must never be able to inject ALB headers via a direct origin.
    """
    path=request.url.path
    if s.is_production and request.method in {'POST','PUT','PATCH','DELETE'}:
        origin=request.headers.get('origin')
        fetch_site=request.headers.get('sec-fetch-site','')
        if (origin and origin not in s.cors_origins) or fetch_site == 'cross-site':
            return JSONResponse({'detail':'Cross-site mutation denied.'},status_code=403,headers={'Cache-Control':'no-store'})
    if s.is_production and (path.startswith('/api/') or path == '/mcp') and path != '/api/health' and request.method != 'OPTIONS':
        try:
            security_service.context_from_request(request)
        except PermissionError:
            return JSONResponse({'detail':'Authentication required or invalid.'},status_code=401,headers={'Cache-Control':'no-store'})
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    if s.is_production:
        response.headers['Cache-Control']='no-store'
    return response

@app.post("/mcp",include_in_schema=False)
def mcp_root(body:MCPRequest,request:Request):
    try:
        u=security_service.context_from_request(request)
    except PermissionError:
        raise HTTPException(401,'Authentication required or invalid.')
    return mcp_service.handle(body.model_dump(),u)

@app.get("/",include_in_schema=False)
def index(): return FileResponse(static/"index.html")

@app.get("/{path:path}",include_in_schema=False)
def spa(path:str):
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")
    candidate=(static/path).resolve()
    if not candidate.is_relative_to(static.resolve()):
        raise HTTPException(status_code=404,detail='Not found')
    if candidate.is_file(): return FileResponse(candidate)
    return FileResponse(static/"index.html")
