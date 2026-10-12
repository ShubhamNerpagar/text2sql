from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

def _env_bool(name: str, default: bool=False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1","true","yes","on"}

def _env_csv(name: str, default: str="") -> tuple[str,...]:
    return tuple(x.strip() for x in os.getenv(name, default).split(',') if x.strip())

@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Data Intelligence Platform")
    app_env: str = os.getenv("APP_ENV", "development").strip().lower()
    app_mode: str = os.getenv("APP_MODE", "local").strip().lower()
    default_market: str = os.getenv("DEFAULT_MARKET", "").strip()
    default_data_source: str = os.getenv("DEFAULT_DATA_SOURCE", "").strip().lower()

    aws_region: str = os.getenv("AWS_REGION", "eu-west-1")
    bedrock_region: str = os.getenv("BEDROCK_REGION", os.getenv("AWS_REGION", "eu-west-1"))
    bedrock_model: str = os.getenv("BEDROCK_MODEL", "eu.amazon.nova-2-lite-v1:0")
    athena_catalog: str = os.getenv("ATHENA_CATALOG", "AwsDataCatalog")
    athena_output: str = os.getenv("ATHENA_OUTPUT", "").strip()
    athena_workgroup: str = os.getenv("ATHENA_WORKGROUP", "primary")
    db_prefix: str = os.getenv("DB_PREFIX", "")

    semantic_bucket: str = os.getenv("SEMANTIC_BUCKET", "").strip()
    ontology_key: str = os.getenv("ONTOLOGY_KEY", "runtime/ontology.json")
    relationships_key: str = os.getenv("RELATIONSHIPS_KEY", "runtime/relationships.json")
    workspace_key_prefix: str = os.getenv("WORKSPACE_KEY_PREFIX", "runtime/workspaces")
    graph_key_prefix: str = os.getenv("GRAPH_KEY_PREFIX", "runtime/semantic-graphs")

    graph_top_k: int = int(os.getenv("GRAPH_TOP_K", "12"))
    graph_embedding_dimensions: int = int(os.getenv("GRAPH_EMBEDDING_DIMENSIONS", "128"))
    graph_candidate_min_confidence: float = float(os.getenv("GRAPH_CANDIDATE_MIN_CONFIDENCE", "0.68"))
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "hash").strip().lower()
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "amazon.titan-embed-text-v2:0").strip()
    embedding_dimensions: int = int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))
    embedding_normalize: bool = _env_bool("EMBEDDING_NORMALIZE", True)
    embedding_fallback: bool = _env_bool("EMBEDDING_FALLBACK", True)
    graph_min_authority: float = float(os.getenv("GRAPH_MIN_AUTHORITY", "0.15"))
    graph_freshness_half_life_days: int = int(os.getenv("GRAPH_FRESHNESS_HALF_LIFE_DAYS", "180"))

    query_timeout_seconds: int = int(os.getenv("QUERY_TIMEOUT_SECONDS", "180"))
    max_result_rows: int = int(os.getenv("MAX_RESULT_ROWS", "5000"))
    max_query_bytes: int = int(os.getenv("MAX_QUERY_BYTES", str(5 * 1024 * 1024 * 1024)))
    query_cost_per_tb_usd: float = float(os.getenv("QUERY_COST_PER_TB_USD", "5.0"))
    max_llm_calls_per_query: int = int(os.getenv("MAX_LLM_CALLS_PER_QUERY", "3"))

    job_queue_backend: str = os.getenv("JOB_QUEUE_BACKEND", os.getenv("PHASE5_QUEUE_BACKEND", "dynamodb" if os.getenv("APP_ENV", "development").strip().lower() == "production" else "sqlite")).strip().lower()
    learning_table: str = os.getenv("LEARNING_TABLE", "").strip()
    max_learning_records: int = int(os.getenv("MAX_LEARNING_RECORDS", "500"))
    planner_min_confidence: float = float(os.getenv("PLANNER_MIN_CONFIDENCE", "0.48"))
    max_planner_tables: int = int(os.getenv("MAX_PLANNER_TABLES", "6"))
    allow_sample_values: bool = _env_bool("ALLOW_SAMPLE_VALUES", False)
    persist_local_state: bool = _env_bool("PERSIST_LOCAL_STATE", True)
    allow_inferred_analytics: bool = _env_bool("ALLOW_INFERRED_ANALYTICS", os.getenv("APP_ENV", "development").strip().lower() != "production")

    enable_sample_execution: bool = _env_bool("ENABLE_SAMPLE_EXECUTION", False)

    security_enabled: bool = _env_bool("SECURITY_ENABLED", True)
    allow_dev_identity_headers: bool = _env_bool("ALLOW_DEV_IDENTITY_HEADERS", os.getenv("APP_ENV", "development").strip().lower() != "production")
    trusted_roles_header: str = os.getenv("TRUSTED_ROLES_HEADER", "x-authenticated-roles").strip().lower()
    auth_mode: str = os.getenv("AUTH_MODE", "dev_headers" if os.getenv("APP_ENV", "development").strip().lower() != "production" else "alb_oidc").strip().lower()
    alb_expected_signer_arn: str = os.getenv("ALB_EXPECTED_SIGNER_ARN", "").strip()
    alb_expected_client_id: str = os.getenv("ALB_EXPECTED_CLIENT_ID", "").strip()
    alb_jwt_public_key_url_template: str = os.getenv("ALB_JWT_PUBLIC_KEY_URL_TEMPLATE", "https://public-keys.auth.elb.{region}.amazonaws.com/{kid}").strip()
    identity_role_claim: str = os.getenv("IDENTITY_ROLE_CLAIM", "roles").strip()
    default_roles: tuple[str,...] = _env_csv("DEFAULT_ROLES", "analyst")
    admin_roles: tuple[str,...] = _env_csv("ADMIN_ROLES", "admin,semantic_admin")
    cors_origins: tuple[str,...] = _env_csv("CORS_ORIGINS", "http://localhost:3000")

    action_lambda_arn: str = os.getenv("ACTION_LAMBDA_ARN", "").strip()
    report_alert_sns_topic_arn: str = os.getenv("REPORT_ALERT_SNS_TOPIC_ARN", "").strip()
    report_worker_token: str = os.getenv("REPORT_WORKER_TOKEN", "").strip()
    otel_enabled: bool = _env_bool("OTEL_ENABLED", False)
    otel_service_name: str = os.getenv("OTEL_SERVICE_NAME", "data-intelligence-platform").strip()
    otel_exporter_otlp_endpoint: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    graph_explorer_max_nodes: int = int(os.getenv("GRAPH_EXPLORER_MAX_NODES", "500"))
    postgres_url: str = os.getenv("POSTGRES_URL", "").strip()
    snowflake_url: str = os.getenv("SNOWFLAKE_URL", "").strip()
    databricks_url: str = os.getenv("DATABRICKS_URL", "").strip()

    data_dir: Path = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
    state_dir: Path = Path(os.getenv("STATE_DIR", str(BASE_DIR / "state")))

    @property
    def is_aws(self) -> bool:
        return self.app_mode == "aws"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

def production_configuration_errors(s: Settings) -> list[str]:
    """Fail-closed prerequisites, validated before accepting production requests."""
    if not s.is_production:
        return []
    errors=[]
    def require(ok: bool, message: str):
        if not ok: errors.append(message)
    def valid(value: str) -> bool:
        return bool(value) and '<' not in value and '>' not in value and 'YOUR_' not in value.upper()
    require(s.security_enabled, 'SECURITY_ENABLED must be true')
    require(not s.allow_dev_identity_headers, 'ALLOW_DEV_IDENTITY_HEADERS must be false')
    require(s.auth_mode == 'alb_oidc', 'AUTH_MODE must be alb_oidc')
    require(valid(s.alb_expected_signer_arn) and s.alb_expected_signer_arn.startswith('arn:aws:elasticloadbalancing:'), 'ALB_EXPECTED_SIGNER_ARN must pin an actual ALB ARN')
    require(valid(s.alb_expected_client_id), 'ALB_EXPECTED_CLIENT_ID must be set')
    require(s.aws_region and f':{s.aws_region}:' in s.alb_expected_signer_arn, 'ALB_EXPECTED_SIGNER_ARN must match AWS_REGION')
    require(s.alb_jwt_public_key_url_template == 'https://public-keys.auth.elb.{region}.amazonaws.com/{kid}', 'ALB public key endpoint must use the official regional AWS hostname')
    require(bool(s.cors_origins) and all(x.startswith('https://') and '*' not in x and '<' not in x for x in s.cors_origins), 'CORS_ORIGINS must contain concrete HTTPS origins')
    require(not s.allow_sample_values, 'ALLOW_SAMPLE_VALUES must be false')
    require(not s.enable_sample_execution, 'ENABLE_SAMPLE_EXECUTION must be false')
    require(not s.allow_inferred_analytics, 'ALLOW_INFERRED_ANALYTICS must be false')
    if s.is_aws:
        require(valid(s.semantic_bucket), 'SEMANTIC_BUCKET must be configured')
        require(valid(s.learning_table), 'LEARNING_TABLE must be configured')
        require(not s.persist_local_state, 'PERSIST_LOCAL_STATE must be false')
        if s.default_data_source == 'athena':
            require(s.athena_output.startswith('s3://') and valid(s.athena_output), 'ATHENA_OUTPUT must specify an S3 results prefix')
    require(s.job_queue_backend == 'dynamodb', 'JOB_QUEUE_BACKEND must be dynamodb in production to avoid host-local queue loss')
    require(s.app_mode == 'aws', 'APP_MODE must be aws for this production profile')
    return errors


def validate_production_config(s: Settings) -> None:
    # In particular reject APP_ENV=prod, which otherwise silently uses development identity defaults.
    if s.app_env not in {'development', 'test', 'production'}:
        raise RuntimeError('APP_ENV must be development, test, or production (no aliases).')
    if s.app_mode not in {'local', 'aws'}:
        raise RuntimeError('APP_MODE must be local or aws.')
    errors = production_configuration_errors(s)
    if errors:
        raise RuntimeError('Production configuration rejected: ' + '; '.join(errors))

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.state_dir.mkdir(parents=True, exist_ok=True)
    return s
