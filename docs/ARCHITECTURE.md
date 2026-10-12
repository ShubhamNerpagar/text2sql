# Architecture — 7.0 Runtime Semantic Control Plane

```text
                         UI / MCP / REST
                               │
                         Identity context
                               │
                  ┌────────────┴────────────┐
                  │                         │
             Conversation               Actions
                  │                         │
                  ▼                         ▼
          Query feature router        Governed handlers
                  │                   audit / Lambda
                  ▼
             GraphRAG 3.0
  relevance × confidence × authority × freshness
                  │
                  ▼
        Logical semantic resolver
     entity / dimension / metric / value
                  │
                  ▼
         Trusted relationship graph
                  │
                  ▼
          Structured semantic plan
                  │
       ┌──────────┼──────────────┐
       ▼          ▼              ▼
 trusted SQL   deterministic    bounded agent
 template      compiler         reasoning
       │          │              │
       └──────────┴──────┬───────┘
                         ▼
                  security + SQL gate
                         │
                  source adapter layer
         ┌───────────────┼────────────────┐
         ▼               ▼                ▼
      Athena          PostgreSQL       Snowflake /
       Glue            Aurora          Databricks
```

## Control-plane persistence

```text
Semantic source package        S3 packaged semantics / graph / releases
Conversations + branches       ControlRepository -> JSON locally / DynamoDB AWS
Actions + audit                ControlRepository -> JSON locally / DynamoDB AWS
Feedback + evaluations         LearningRepository -> JSON locally / DynamoDB AWS
```

## Semantic layers

1. **Business/logical model** — entities, dimensions, metrics, concepts, hierarchies.
2. **Knowledge graph** — inferred/verified knowledge and provenance.
3. **Physical model** — sources, databases, tables and columns.
4. **Governance** — status, confidence, authority, freshness, owner and branch/release history.
5. **Security** — identity-aware semantic visibility and row/column constraints.

## GraphRAG authority boundary

GraphRAG can retrieve and propose knowledge. Runtime joins are accepted only from governed, verified, certified or data-validated relationship states recognized by `RelationshipService`/`JoinPlanner`.

## Deployment invariant

There is one application codebase. `APP_MODE`, IAM, source credentials and persistence settings determine whether it runs in local/native test mode or durable AWS production mode; business logic is not forked per environment.
