# Optional bundled Contoso data and SQLBI official installer

- `contoso_demo.sqlite3` is a deterministic, **independently generated illustrative retail database** created by `scripts/generate_contoso_illustration.py`. It is NOT an official SQLBI sample and must not be marketed as one.
- It contains 10,000 Orders and eight select-able tables for testing the Phase 1 scope selection UI entirely offline.
- To download **official SQLBI Contoso V2 10K CSV data** into this application's sample-data directory, run `windows\Install-Contoso.ps1` after running the app installer. Outbound GitHub access is required. The script resolves the official release asset via GitHub's release API, checks its size and published SHA-256 (when available), decompresses it, and imports CSV files into `contoso_official.sqlite3`.
- Once installed, choose local source > `contoso_official` > table(s) in **Data > Enterprise Catalog**. The untouched downloaded archive, original CSV files and an attribution/verification manifest remain in `sample-data/contoso/`.
- Generator: https://github.com/sql-bi/Contoso-Data-Generator-V2
- Official sample releases: https://github.com/sql-bi/Contoso-Data-Generator-V2-Data/releases/tag/ready-to-use-data
- Review upstream licensing terms for the data, scripts and original source files before redistribution.
- The Phase 1 scope picker reads only catalog metadata; selecting tables does not send sample business rows to an LLM.

The Contoso connector is optional and can be selected alongside enterprise connectors in 8.5.0. Browsing and profiling are deterministic setup operations; accepted natural-language questions always require verified Bedrock models. Leave Contoso unchecked to create a workspace entirely from your own datasets.
