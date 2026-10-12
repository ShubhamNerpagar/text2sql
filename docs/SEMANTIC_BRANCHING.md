# Semantic branching

Branches isolate semantic changes from the active market model.

Workflow:
1. Create a branch.
2. Add `set`/`delete` patches against semantic paths.
3. Validate structural integrity and warnings.
4. Review the branch diff.
5. Merge with publish permission.
6. The merged branch becomes an approved semantic overlay consumed by the runtime.

This avoids modifying the generated runtime workspace directly from a running application instance and creates an auditable merge artifact. Semantic releases can then snapshot the merged control plane.
