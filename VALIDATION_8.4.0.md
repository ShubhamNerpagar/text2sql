# Validation — Data Intelligence Platform 8.4.0

- **189 automated tests passed**, zero failed or skipped; one dependency deprecation warning. Full suite: `python -m pytest -q`, 127.07 seconds.
- **10 Chromium browser checks passed**, with zero JavaScript page errors. Checks cover a net-sales result of 350, city follow-up results of 90 and 260, guided onboarding, executable definition authoring, relationship authoring, result benchmarks, plan preview, model settings, and disabling Ask when the model is unavailable.
- Python compilation, JavaScript syntax and whitespace checks passed.
- The unconfigured HTTP server reports health/version correctly, requires source onboarding, and reports `offline_fallback: false` with LLM readiness false. Missing source/semantic workspace makes `/api/ready` false as expected.

The business tests check formulas and required predicates, distinct counts, weighted averages, ratios, exact date filters, retained/removable follow-up filters, clause loss, review rejection, parent measure repetition, role-playing and composite joins, exact duplicate rejection and evidence revocation, shared identities, report permissions, blocked model access, cross-asset code vocabularies and concurrent/failed control-state writes. Old tests that expected offline or inferred execution were migrated to the new governed contracts; no tests are disabled to obtain these results.

Browser and planner tests use **mocked Bedrock responses**. Compiler results execute against isolated SQLAlchemy/SQLite and explicitly enabled synthetic fixtures with independently checked values. These checks establish the compiler and integration contract; they do not establish live LLM interpretation accuracy.

Live Bedrock, live enterprise warehouse connectors and Windows EC2/PowerShell acceptance were **not run**. The inherited AWS profile was unavailable and an alternate usable credential chain was absent. Windows timezone data and process-lock dependencies are included; the existing Windows CI/deployment scripts remain available for native acceptance. Run your reference-SQL business benchmarks after connecting the real models and sources.

Cloud installation was exercised and reusable `install_script`, `start_skill` and network settings were saved as a reviewable draft. Saving does not publish the environment. The original GitHub checkout remains unchanged; implementation work is in the uploaded application's extracted source.

See [the model connection guide](docs/LLM_CONNECTION.md), [the business definitions and migration guide](docs/BUSINESS_ACCURACY.md), [machine-readable results](VALIDATION_8.4.0.json), [the complete test log](qa_results/pytest_8.4.0.txt) and [browser results](qa_results/browser_8.4.0.json). Older QA reports/screenshots are historical.

## GitHub checkout verification — 12 October 2026

The full application source was imported into the `ShubhamNerpagar/text2sql` checkout, together with the UI walkthrough and pending-work audit. Running `python -m pytest -q` from that checkout passed **189 tests**, with one dependency deprecation warning, in **152.12 seconds**. Python compilation, JavaScript syntax, staged whitespace and the source manifest were also checked. See [the handoff test log](qa_results/pytest_github_handoff_8.4.0.txt).

The earlier statement that the selected GitHub checkout remained unchanged records the pre-handoff validation state. The live AWS, warehouse, Windows acceptance and feature limitations remain documented in [the pending-work audit](docs/PENDING_WORK_8.4.0.md).
