# Optional bundled Contoso data and SQLBI official installer

- `contoso_demo.sqlite3` is a deterministic, **independently generated illustrative retail database** created by `scripts/generate_contoso_illustration.py`. It is NOT an official SQLBI sample and must not be marketed as one.
- It contains 10,000 Orders and eight selectable tables. Browsing metadata does not require an LLM; new natural-language questions require verified LLM access.
- To download **official SQLBI Contoso V2 CSV 10K data** into this application's sample-data directory, run `windows\Install-Contoso.ps1` after running the app installer. The installer uses GitHub's release API or the public release listing, verifies the published checksum when supplied, and imports complete CSVs with numeric/date types into `contoso_official.sqlite3`.
- Once installed, choose Contoso > `contoso_official` > table(s) in **Data > Catalog Explorer**. The downloaded archive, imported database and an attribution/type/count manifest remain in `sample-data/contoso/`; temporary extracted CSVs are removed after import.
- For an existing file, run `windows\Install-Contoso.ps1 -ArchivePath 'C:\Downloads\csv-1m.7z' -DatasetId contoso_1m`. Successful imports appear as separate optional datasets; existing dataset IDs and the demo cannot be overwritten.
- The official CSV 10K asset was downloaded, checksum-verified and installed in this cloud workspace on 2026-10-12. It contains 3,996 sales rows, 1,681 orders and 164,730 total rows. See [the full review](../../docs/CONTOSO_DATASET_REVIEW.md). Imported data is excluded from Git; run the installer on another machine.
- Generator: https://github.com/sql-bi/Contoso-Data-Generator-V2
- Official sample releases: https://github.com/sql-bi/Contoso-Data-Generator-V2-Data/releases/tag/ready-to-use-data
- Review upstream licensing terms for the data, scripts and original source files before redistribution.
- The Phase 1 scope picker reads only catalog metadata; selecting tables does not send sample business rows to an LLM.

The Contoso connector is optional and can be selected alongside enterprise connectors in 8.5.0. Browsing and profiling are deterministic setup operations; accepted natural-language questions always require verified Bedrock models. Leave Contoso unchecked to create a workspace entirely from your own datasets.
