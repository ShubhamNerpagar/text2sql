from pydantic import BaseModel, Field
from typing import Literal, Any


class WorkspaceBootstrapRequest(BaseModel):
    source_id: Literal["athena","postgres","snowflake","databricks","contoso"]
    workspace_id: str = Field(min_length=2,max_length=80,pattern=r"^[A-Za-z0-9_-]+$")
    display_name: str | None = Field(default=None,max_length=120)
    schemas: list[str] = []
    discover_relationships: bool = True

class QueryRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    market: str = ""
    execute: bool = True
    database: str | None = None
    conversation_id: str | None = None
    data_source: str | None = None
    branch_id: str | None = None

class QueryFeedbackRequest(BaseModel):
    rating: Literal["up","down"]
    note: str | None = Field(default=None,max_length=2000)

class ResolveRequest(BaseModel):
    question: str = Field(min_length=2,max_length=4000)
    market: str = ""
    conversation_id: str | None = None
    branch_id: str | None = None

class RelationshipAction(BaseModel):
    action: Literal["verify", "reject", "validate", "certify", "deprecate"]
    note: str | None = None

class DescriptionGenerateRequest(BaseModel):
    market: str = ""
    database: str
    table: str
    column: str
    force_ai: bool = False

class DescriptionUpdateRequest(BaseModel):
    description: str = Field(min_length=2, max_length=3000)
    status: Literal["reviewed", "verified", "certified", "deprecated", "rejected"] = "reviewed"

class CatalogSyncRequest(BaseModel):
    market: str = ""
    databases: list[str] = []

class RelationshipDiscoveryRequest(BaseModel):
    market: str = ""
    max_candidates: int = Field(default=300, ge=1, le=2000)

class GraphSearchRequest(BaseModel):
    question: str = Field(min_length=2,max_length=4000)
    market: str = ""
    top_k: int = Field(default=12, ge=3, le=50)
    depth: int = Field(default=1, ge=0, le=3)

class GraphRebuildRequest(BaseModel):
    market: str = ""

class GraphNeighborhoodRequest(BaseModel):
    market: str = ""
    node_id: str = Field(min_length=2,max_length=1000)
    depth: int = Field(default=1,ge=1,le=3)

class SemanticReleaseRequest(BaseModel):
    market: str = ""
    version: str = Field(min_length=5,max_length=64)
    notes: str = Field(default="",max_length=3000)

class ConversationCreateRequest(BaseModel):
    market: str = ""
    title: str | None = Field(default=None,max_length=200)

class BranchCreateRequest(BaseModel):
    market: str = ""
    name: str = Field(min_length=2,max_length=100)
    description: str = Field(default="",max_length=1000)
    base_version: str | None = None

class BranchPatchRequest(BaseModel):
    path: str = Field(min_length=2,max_length=500)
    value: Any = None
    operation: Literal["set","delete"] = "set"

class BranchMergeRequest(BaseModel):
    note: str = Field(default="",max_length=1000)

class ActionExecuteRequest(BaseModel):
    market: str = ""
    parameters: dict[str,Any] = {}
    dry_run: bool = False

class OntologyInferRequest(BaseModel):
    market: str = ""
    max_suggestions: int = Field(default=100,ge=1,le=1000)

class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str,Any] = {}

class SuggestionReviewRequest(BaseModel):
    status: Literal["approved","rejected","certified","deprecated"]
    note: str = Field(default="",max_length=1000)


class ReportCreateRequest(BaseModel):
    market: str = ""
    title: str = Field(min_length=2,max_length=160)
    description: str = Field(default="",max_length=2000)

class ReportWidgetRequest(BaseModel):
    release_id: str | None = None
    question: str = Field(min_length=2,max_length=4000)
    title: str | None = Field(default=None,max_length=160)
    chart_type: Literal["auto","kpi","bar","line","table","donut"] = "auto"

class ReportStatusRequest(BaseModel):
    status: Literal["draft","published","certified","deprecated"]

class SemanticObjectUpsertRequest(BaseModel):
    workspace: str = Field(min_length=2,max_length=80)
    kind: Literal["entity","dimension","metric","concept","business_term","verified_query"]
    object_id: str = Field(min_length=1,max_length=120)
    spec: dict[str,Any] = {}

class SemanticTransitionRequest(BaseModel):
    workspace: str = Field(min_length=2,max_length=80)
    kind: Literal["entity","dimension","metric","concept","business_term","verified_query"]
    object_id: str = Field(min_length=1,max_length=120)
    status: Literal["draft","reviewed","approved","verified","certified","deprecated","rejected"]
    note: str = Field(default="",max_length=2000)

class SemanticSuggestionPromoteRequest(BaseModel):
    workspace: str = Field(min_length=2,max_length=80)
    suggestion_id: str = Field(min_length=2,max_length=240)

class ReportShareRequest(BaseModel):
    roles: list[str] = []

class ReportFiltersRequest(BaseModel):
    filters: list[dict[str,Any]] = []

class ReportScheduleRequest(BaseModel):
    enabled: bool = True
    cron: str = Field(default="0 8 * * *",max_length=80)
    timezone: str = Field(default="UTC",max_length=80)
    data_source: str | None = None

class ReportAlertRequest(BaseModel):
    enabled: bool = True
    widget_id: str
    operator: Literal[">",">=","<","<=","==","!="] = ">"
    threshold: float
    value_column: str | None = None
    message: str = Field(default="",max_length=500)
