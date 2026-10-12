> Historical report from the original attachment. For the updated release, see [VALIDATION_8.4.0.md](VALIDATION_8.4.0.md).

# Unified Ask acceptance — version 8.3.0

## Verified locally

- 152 Python regression tests passed (including 4 new unified API tests covering simple Count, grouped Sales, 4-table joins, follow-up, Bedrock mocked planning and negative permissions).
- Existing older advanced APIs and legacy service suites pass regression unchanged.
- Chromium used an in-process FastAPI bridge. It tested one Ask input, pinned release selector, four sequential question/answer turns, approved 3-join and 2-join SQL, and safe refusal of unsupported time logic.
- Browser test recorded **19 API calls**; **18 HTTP successes**, **one expected 400 refusal**, and **zero JavaScript exceptions**.
- Python compiled; JavaScript syntax checked by Node.

## Not proven / pending

- Live Bedrock model invocation (API permission, prompt handling, latency, cost and accuracy).
- Live warehouse SQL execution (currently preview-only), account isolation and connector-specific policy enforcement.
- Session turns are in-memory in the UI, not stored as durable governed conversation history.
- Report widgets still use the legacy Ask/query engine; certified unified answers are not automatically publishable to existing reports.
- Real Windows EC2, identity provider, live multi-host queue, warehouse benchmarking, load/soak and penetration testing.

**This is a locally tested application build, not a production certification.**
