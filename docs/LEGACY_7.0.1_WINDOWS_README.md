# Data Intelligence Platform 7.0.1 — Windows EC2 Native Edition

This package runs **directly on Windows Server with Python + Uvicorn**. Docker, Docker Desktop, Docker Compose and ECS are not required.

## Recommended first test architecture

```text
Your laptop / browser
        |
        | TCP 8000 (restrict EC2 Security Group to YOUR public IP)
        v
Windows EC2
  Python 3.12
  Uvicorn / FastAPI
  Data Intelligence Platform UI
        |
        +--> EC2 IAM Instance Profile
        +--> Glue Catalog
        +--> Athena
        +--> source S3 referenced by Glue
        +--> Athena-results S3
        |
        +--> local C:\...\state during first test
```

For the first validation, keep application state local on the EC2 disk. After the platform works with your real Athena/Glue data, you can enable the semantic S3 bucket and DynamoDB without changing application code.

---

## 1. EC2 prerequisites

Recommended:

- Windows Server 2022 or 2025 EC2 instance.
- Python **3.12 x64** installed with `python.exe` on PATH.
- At least 4 GB RAM; 8 GB is more comfortable for GraphRAG/testing.
- An EC2 IAM instance profile for AWS access. **Do not place AWS access keys in `.env`.**
- Outbound HTTPS access to AWS APIs and, if used, PostgreSQL/Snowflake/Databricks endpoints.

The app serves the backend and frontend together, so Node.js is **not required** to run it.

---

## 2. Extract the package

A simple path is recommended:

```powershell
C:\DataIntelligencePlatform
```

Open **PowerShell as Administrator**, then:

```powershell
cd C:\DataIntelligencePlatform
Set-ExecutionPolicy -Scope Process Bypass
```

---

## 3. Install the application

Run:

```powershell
.\windows\Install-App.ps1
```

The script:

1. checks Python,
2. creates `.venv`,
3. installs runtime dependencies,
4. installs test dependencies,
5. creates `.env` from the Windows test template if needed,
6. creates `state` and `logs`,
7. runs the automated application tests.

You can also double-click/run:

```text
windows\Setup.cmd
```

---

## 4. Configure `.env` for Athena

Edit:

```text
C:\DataIntelligencePlatform\.env
```

For the first real Athena test, the important values are:

```dotenv
APP_ENV=development
APP_MODE=aws
DEFAULT_DATA_SOURCE=athena
AWS_REGION=ap-south-1
ATHENA_CATALOG=AwsDataCatalog
ATHENA_WORKGROUP=primary
ATHENA_OUTPUT=s3://YOUR-ATHENA-RESULTS-BUCKET/data-intelligence/results/
DB_PREFIX=
PERSIST_LOCAL_STATE=true
ALLOW_SAMPLE_VALUES=false
EMBEDDING_PROVIDER=hash
AUTH_MODE=dev_headers
ALLOW_DEV_IDENTITY_HEADERS=true
```

### Do not put the source-data S3 path in `ATHENA_OUTPUT`

There are three different S3 purposes:

1. **Actual business data** — configured in the Glue table, for example:
   `s3://company-curated/orders/`
2. **Athena query results** — configured in `.env` as `ATHENA_OUTPUT`.
3. **Platform semantic artifacts** — optional for the first test; later configure `SEMANTIC_BUCKET`.

For the first Windows test, you can leave:

```dotenv
SEMANTIC_BUCKET=
LEARNING_TABLE=
PERSIST_LOCAL_STATE=true
```

This keeps generated ontology/workspace/control state under the application's local `state` directory.

---

## 5. Attach an EC2 IAM role

Attach an **instance profile** to the Windows EC2 instance. A template is included at:

```text
infra\windows\ec2-instance-role-policy.json
```

Replace its placeholders for your source-data bucket, Athena-results bucket, region and account. Optional S3/DynamoDB/Bedrock/SNS permissions can be removed until you use those features.

At minimum for Athena/Glue testing, the role needs:

- Glue read metadata permissions,
- Athena query execution/read permissions,
- read access to the S3 buckets used by the Glue tables,
- read/write access to the Athena-results bucket.

Boto3 automatically uses the EC2 instance profile. No static AWS access key is necessary.

---

## 6. Validate AWS before starting the UI

After editing `.env`:

```powershell
.\windows\Test-Aws.ps1
```

With local state enabled, S3 semantic persistence and DynamoDB are optional. The script validates the AWS identity and the configured Athena/Glue path without modifying your source data.

---

## 7. Start the application

Run:

```powershell
.\windows\Start-App.ps1
```

Default URL on the server:

```text
http://127.0.1.1:8000
```

The application binds to `0.0.0.0:8000`, so it can also be reached remotely if both Windows Firewall and the EC2 Security Group allow the port.

---

## 8. Test locally on the EC2 server

Keep the application running in one PowerShell window. Open a second PowerShell window:

```powershell
cd C:\DataIntelligencePlatform
.\windows\Test-App.ps1
```

You should see PASS checks for:

- `/api/health`,
- `/api/ready` response,
- authenticated bootstrap,
- data-source health.

Readiness can remain false until you have configured a source **and generated the first workspace**.

---

## 9. Open the UI from your own computer

For temporary testing only:

### Windows Firewall

On the EC2 server:

```powershell
.\windows\Open-Firewall.ps1 -Port 8000
```

### EC2 Security Group

Add an inbound rule:

```text
Type: Custom TCP
Port: 8000
Source: YOUR_PUBLIC_IP/32
```

Do **not** use `0.0.0.0/0` for a direct development deployment.

Then open:

```text
http://EC2_PUBLIC_IP:8000
```

For a production deployment, put the instance behind HTTPS ALB/OIDC or another authenticated reverse proxy and disable development identity headers.

---

## 10. Create the first real workspace

In the UI:

```text
Admin -> Onboarding
```

Choose:

```text
Amazon Athena + Glue Catalog
```

Then provide:

- Workspace ID, e.g. `finance-prod`
- Display name
- Optional Glue database scope
- Discover relationships = enabled

Click **Connect & Generate**.

The application then:

```text
Glue metadata
   ↓
Tables / columns / types / locations
   ↓
Physical ontology
   ↓
Generated semantic draft
   ↓
Relationship candidates
   ↓
GraphRAG graph
   ↓
Semantic Studio review/certification
```

`ALLOW_SAMPLE_VALUES=false` keeps onboarding metadata-only.

---

## 11. Test Semantic Studio

Go to:

```text
Semantics -> Semantic Studio
```

Review generated:

- entities,
- dimensions,
- metrics,
- concepts/business terms,
- relationships,
- verified queries.

The expected lifecycle is:

```text
inferred/draft -> reviewed -> approved/verified -> certified
```

A metadata resync records schema drift and preserves steward-owned reviewed/certified semantic objects rather than silently replacing them.

---

## 12. Test Ask / NL-to-SQL

After the workspace is generated and key semantic objects are reviewed, use **Ask**.

The query path is:

```text
Question
 -> GraphRAG retrieval
 -> semantic resolution
 -> trusted relationship planning
 -> structured plan
 -> security / RLS / CLS
 -> SQL safety
 -> Athena execution
 -> answer + SQL + execution metadata
```

For Athena, keep a hard bytes-scanned cutoff on the Athena Workgroup in addition to application-side cost reporting.

---

## 13. Run the full automated suite on Windows

At any time:

```powershell
.\windows\Run-Tests.ps1
```

This runs the automated regression suite and Python compilation checks using Windows-safe temporary paths.

---

## 14. Run a native load smoke test

With the application running:

```powershell
.\.venv\Scripts\python.exe scripts\load_test.py --base-url http://127.0.1.1:8000 --requests 500 --concurrency 25
```

This is an HTTP smoke/load test. It is not a substitute for a real Athena workload benchmark.

---

## 15. Run automatically after EC2 reboot

After manual testing succeeds, install the application as a Windows Scheduled Task running under `SYSTEM`:

```powershell
.\windows\Install-StartupTask.ps1 -Port 8000
```

The task:

- starts at Windows boot,
- restarts after failures,
- runs without an interactive desktop session,
- writes to `logs\app.log` and `logs\app-error.log`.

Remove it with:

```powershell
.\windows\Uninstall-StartupTask.ps1
```

Because the process runs under `SYSTEM`, use an EC2 **instance profile**, not user-specific AWS credential files.

---

## 16. Scheduled BI reports

After report scheduling is configured in the application, install the native report worker:

```powershell
.\windows\Install-ReportWorkerTask.ps1 -EveryMinutes 5
```

The task executes `scripts\run_report_worker.py` periodically. Logs are written under `logs`.

If `REPORT_ALERT_SNS_TOPIC_ARN` is configured and the instance role permits `sns:Publish`, report alerts can publish to SNS.

---

## 17. PostgreSQL / Aurora

Set:

```dotenv
DEFAULT_DATA_SOURCE=postgres
POSTGRES_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE
```

Prefer retrieving credentials securely rather than committing them anywhere. For a temporary test, `.env` is gitignored, but Windows file permissions should still be restricted.

---

## 18. Snowflake

Set the SQLAlchemy URL supported by `snowflake-sqlalchemy`:

```dotenv
DEFAULT_DATA_SOURCE=snowflake
SNOWFLAKE_URL=snowflake://...
```

The Windows setup installs the Snowflake connector dependency automatically.

---

## 19. Databricks

Set the SQLAlchemy connection URL for your Databricks SQL Warehouse:

```dotenv
DEFAULT_DATA_SOURCE=databricks
DATABRICKS_URL=databricks://...
```

The Windows setup installs the Databricks SQL/SQLAlchemy packages automatically.

---

## 20. Bedrock

First test with:

```dotenv
EMBEDDING_PROVIDER=hash
```

After the application and Athena connection work, enable Bedrock:

```dotenv
EMBEDDING_PROVIDER=bedrock
BEDROCK_REGION=ap-south-1
EMBEDDING_MODEL=amazon.titan-embed-text-v2:0
EMBEDDING_DIMENSIONS=1024
```

Your account/region must have access to the configured models.

---

## 21. Moving from EC2 test mode to durable production mode

After the native Windows test succeeds, change to:

```dotenv
APP_ENV=production
SEMANTIC_BUCKET=your-semantic-bucket-name
LEARNING_TABLE=data-intelligence-control
PERSIST_LOCAL_STATE=false
EMBEDDING_PROVIDER=bedrock
OTEL_ENABLED=true
ALLOW_DEV_IDENTITY_HEADERS=false
AUTH_MODE=alb_oidc
ALB_EXPECTED_SIGNER_ARN=...
CORS_ORIGINS=https://your-domain.example
```

Recommended production ingress:

```text
Internet / corporate network
        ↓
HTTPS ALB
        ↓
OIDC / Cognito authentication
        ↓
private Windows EC2
        ↓
Uvicorn / FastAPI on port 8000
```

Do not expose the production instance directly on port 8000.

---

## 22. Logs and troubleshooting

Foreground run:

```text
PowerShell console
```

Startup-task logs:

```text
logs\app.log
logs\app-error.log
```

Report-worker logs:

```text
logs\report-worker.log
logs\report-worker-error.log
```

### App does not start

Run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.1.1 --port 8000
```

The traceback will be shown directly.

### Browser cannot reach EC2

Check all three:

1. Uvicorn is running on `0.0.0.0:8000`.
2. Windows Firewall allows TCP 8000.
3. EC2 Security Group allows TCP 8000 from your IP.

### Athena shows not configured

Check:

```dotenv
APP_MODE=aws
ATHENA_OUTPUT=s3://...
```

Then run:

```powershell
.\windows\Test-Aws.ps1
```

### Glue metadata is empty

Check the instance role's Glue permissions and `DB_PREFIX`. An incorrect `DB_PREFIX` can hide all databases.

### Access denied reading source data

The Athena execution role/EC2 instance profile must be able to read every S3 location referenced by the queried Glue tables, including KMS permissions when the objects are encrypted with a customer-managed key.

---

## 23. Files you normally edit

For a first Athena test, you mainly edit only:

```text
.env
```

You should normally **not** edit Python source code to configure a deployment.

Important supporting files:

```text
.env.windows.test.example
.env.windows.production.example
infra\windows\ec2-instance-role-policy.json
windows\Install-App.ps1
windows\Start-App.ps1
windows\Test-App.ps1
windows\Test-Aws.ps1
```

---

## 24. Quick-start summary

```powershell
cd C:\DataIntelligencePlatform
Set-ExecutionPolicy -Scope Process Bypass
.\windows\Install-App.ps1
notepad .env
.\windows\Test-Aws.ps1
.\windows\Start-App.ps1
```

Then, in a second PowerShell window:

```powershell
cd C:\DataIntelligencePlatform
.\windows\Test-App.ps1
```

Finally open the UI and use **Admin -> Onboarding** to generate your first real workspace.

---

## 7.0.1 semantic-runtime upgrade note

If upgrading a workspace created by 7.0.0, keep the existing `.env` and state directory, add `ALLOW_INFERRED_ANALYTICS=true` for test/development, restart the application, then use **Admin → Onboarding → Resync metadata** once. This materializes the repaired inferred metric definitions. See `SEMANTIC_FIX_7.0.1.md` for the exact behavior changes and validation examples.
