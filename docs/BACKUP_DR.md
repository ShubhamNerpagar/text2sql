# Backup and Disaster Recovery — Windows EC2 Native

## Test-mode local state

When `PERSIST_LOCAL_STATE=true`, generated application state lives under the local `state` directory. This is suitable for a controlled EC2 test, but it is tied to that instance/volume.

Before important testing sessions, snapshot the EBS volume or copy the `state` directory.

## Durable production state

For production use:

- `SEMANTIC_BUCKET` for ontology, relationships, workspace contexts and GraphRAG artifacts. Enable S3 Versioning, encryption and Block Public Access.
- `LEARNING_TABLE` for conversations, reports, audit, workspace registry and learning/control-plane data. Enable DynamoDB point-in-time recovery.
- EC2 application files should be treated as replaceable code, not the system of record.

## Recovery validation

1. Restore a previous S3 object version in a non-production prefix/bucket.
2. Restore the DynamoDB table to a temporary table using PITR.
3. Point a staging Windows instance at the restored stores.
4. Start the application and verify workspace inventory, certified semantics, reports and audit/history.
5. Record recovery time and any manual steps.
