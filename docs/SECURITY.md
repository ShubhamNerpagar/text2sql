# Security model

Version 7.0 enforces identity and semantic policy before retrieval, planning and execution.

## Identity

Local development mode can use `X-User` and `X-Roles` for testing only. Production sets `ALLOW_DEV_IDENTITY_HEADERS=false`; identity should arrive from an authenticated ALB/OIDC layer and roles from the trusted header configured by `TRUSTED_ROLES_HEADER`.

## RBAC

Market semantic packages define role permissions for query, semantic review, branch management, publishing, action execution and PII access. Admin roles bypass application policy only; warehouse permissions still remain authoritative.

## Column-level policy

Column patterns such as email/phone are filtered from catalog and GraphRAG context and rejected if they appear in generated SQL for unauthorized roles.

## Row-level policy

`security.row_policies` can inject governed predicates into deterministic SQL. Keep native warehouse RLS/Lake Formation policies enabled as the final enforcement boundary.

## Defense in depth

The application accepts only read-only analytics SQL. Athena should use the dedicated cost-governed workgroup. Windows EC2 uses an IAM instance profile; no AWS access keys are required in the application configuration.
