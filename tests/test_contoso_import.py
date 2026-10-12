"""Typed archive import and governed execution; fixtures are independently generated."""
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
import shutil
import sqlite3

import py7zr
import pytest

from app.services.contoso_import_service import import_archive, sha256_file
from app.services.contoso_sample_service import ContosoSampleService, installed_datasets
from app.services.data_source_service import DataSourceService
from app.services.enterprise_catalog_service import EnterpriseCatalogService


def archive_files(tmp_path, files):
    source = tmp_path / "source"
    source.mkdir(exist_ok=True)
    archive = tmp_path / (uuid4().hex + ".7z")
    with py7zr.SevenZipFile(archive, "w") as handle:
        for name, contents in files.items():
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents if isinstance(contents, bytes) else contents.encode("utf-8"))
            handle.write(path, arcname=name)
    return archive


@pytest.fixture
def imported(tmp_path, monkeypatch):
    archive = archive_files(tmp_path, {
        "sales.csv": "OrderKey,LineNumber,Quantity,NetPrice,ExchangeRate,CurrencyCode,OrderDate,ProductKey\n1,0,2,100.50,2.0,EUR,2024-01-01,1\n1,1,1,40.0,2.0,EUR,2024-01-01,1\n2,0,3,20.0,1.0,USD,2024-02-01,2\n",
        "product.csv": "ProductKey,ProductCode,Category\n1,0101001,Audio\n2,0202002,Video\n",
        "notes.md": "This document is not a database table or an instruction to the importer.\n"})
    destination = tmp_path / "datasets"
    manifest = import_archive(archive, "contoso_test", destination)
    monkeypatch.setattr("app.services.contoso_sample_service.SAMPLE_DIR", destination)
    return destination, manifest


def test_archive_roundtrip_preserves_numeric_types_dates_and_identifier_codes(imported):
    destination, manifest = imported
    assert manifest["total_rows"] == 5
    assert set(manifest["tables"]) == {"sales", "product"}
    assert manifest["upstream_checksum_verified"] is False
    details = ContosoSampleService().table_details("sales", "contoso_test")
    types = {column["name"]: column["type"] for column in details["columns"]}
    assert types["OrderKey"] == "INTEGER" and types["NetPrice"] == "REAL" and types["OrderDate"] == "DATE"
    source = DataSourceService()
    result = source.execute("contoso", "SELECT SUM(Quantity * NetPrice / ExchangeRate) AS value FROM contoso_test.sales", "contoso_test")
    assert result["rows"] == [{"value": 180.5}]
    assert source.execute("contoso", "SELECT ProductCode FROM product ORDER BY ProductKey", "contoso_test")["rows"] == [{"ProductCode": "0101001"}, {"ProductCode": "0202002"}]
    assert details["foreign_keys"] == []  # Evidence is not an invented declaration.
    assert not list(destination.glob(".contoso-import-*"))


def test_catalog_source_and_scoped_discovery_publish_named_dataset(imported):
    catalog = EnterpriseCatalogService()
    assert catalog.databases("contoso")["items"] == [{"name": "contoso_test"}]
    assert len(catalog.tables("contoso", database="contoso_test")["items"]) == 2
    registry = next(item for item in DataSourceService().sources() if item["id"] == "contoso")
    assert registry["configured"] and registry["optional"] and not registry["bundled_dataset"]
    assert registry["installed_datasets"][0]["database"] == "contoso_test"
    discovery = DataSourceService().discover("contoso", ["contoso_test"])
    assert discovery["scope"] == ["contoso_test"]
    assert {item["database"] for item in discovery["objects"]} == {"contoso_test"}
    with pytest.raises(ValueError, match="explicitly"):
        DataSourceService().discover("contoso")


def test_import_never_replaces_existing_dataset(imported, tmp_path):
    destination, manifest = imported
    before = sha256_file(destination / "contoso_test.sqlite3")
    archive = archive_files(tmp_path, {"sales.csv": "OrderKey\n999\n"})
    with pytest.raises(ValueError, match="already exists"):
        import_archive(archive, "contoso_test", destination)
    assert sha256_file(destination / "contoso_test.sqlite3") == before


def test_entire_file_is_typed_and_all_batches_are_imported(tmp_path):
    rows = ["OrderKey,Amount,LargeMixed,Code"]
    rows.extend(f"{i},1.25,9007199254740993,001" for i in range(4000))
    rows.append("4000,late-invalid,1.5,002")
    archive = archive_files(tmp_path, {"sales.csv": "\n".join(rows) + "\n"})
    destination = tmp_path / "datasets"
    report = import_archive(archive, "contoso_late", destination)
    assert report["tables"]["sales"]["rows"] == 4001
    types = {column["name"]: column["type"] for column in report["tables"]["sales"]["columns"]}
    assert types == {"OrderKey": "INTEGER", "Amount": "TEXT", "LargeMixed": "TEXT", "Code": "TEXT"}
    with sqlite3.connect(destination / "contoso_late.sqlite3") as db:
        assert db.execute("SELECT Amount FROM sales WHERE OrderKey=4000").fetchone() == ("late-invalid",)
        assert db.execute("SELECT LargeMixed FROM sales WHERE OrderKey=0").fetchone() == ("9007199254740993",)


@pytest.mark.parametrize("contents", [
    "ID,Amount\n1,2\n2\n", "ID,Amount\n1,2\n2,3,4\n",
    "Key,key\n1,2\n", "First Name,First-Name\nA,B\n", b"ID,Name\n1,\xff\n"])
def test_invalid_csv_aborts_without_publishing_or_skipping_rows(tmp_path, contents):
    archive = archive_files(tmp_path, {"sales.csv": contents})
    destination = tmp_path / "datasets"
    with pytest.raises(ValueError):
        import_archive(archive, "contoso_invalid", destination)
    assert not list(destination.glob("*.sqlite3"))
    assert not list(destination.glob("*.manifest.json"))


@pytest.mark.parametrize("dataset_id", ["contoso_demo", "../contoso_bad", "contoso_bad;drop", "other_dataset"])
def test_invalid_dataset_id_cannot_replace_demo_or_escape_directory(tmp_path, dataset_id):
    archive = archive_files(tmp_path, {"sales.csv": "Key\n1\n"})
    with pytest.raises(ValueError, match="dataset ID"):
        import_archive(archive, dataset_id, tmp_path / "datasets")


def test_checksum_and_size_and_row_limits_fail_before_publication(tmp_path):
    archive = archive_files(tmp_path, {"sales.csv": "Key,Amount\n1,2.5\n2,3.5\n"})
    destination = tmp_path / "datasets"
    with pytest.raises(ValueError, match="SHA-256"):
        import_archive(archive, "contoso_checksum", destination, expected_sha256="0" * 64)
    with pytest.raises(ValueError, match="uncompressed size"):
        import_archive(archive, "contoso_bytes", destination, max_unpacked_bytes=1)
    with pytest.raises(ValueError, match="row limit"):
        import_archive(archive, "contoso_rows", destination, max_rows_per_table=1)
    assert not list(destination.glob("*.sqlite3"))


@pytest.mark.parametrize("expected_checksum", ["", "not-a-checksum", "0" * 63])
def test_invalid_expected_checksum_cannot_be_recorded_as_verified(tmp_path, expected_checksum):
    archive = archive_files(tmp_path, {"sales.csv": "Key\n1\n"})
    with pytest.raises(ValueError, match="SHA-256"):
        import_archive(archive, "contoso_bad_hash", tmp_path / "datasets", expected_sha256=expected_checksum)


def test_unsafe_archive_member_is_rejected(tmp_path):
    source = tmp_path / "sales.csv"
    source.write_text("Key\n1\n")
    archive = tmp_path / "unsafe.7z"
    with py7zr.SevenZipFile(archive, "w") as handle:
        handle.write(source, arcname="../escaped.csv")
    with pytest.raises(ValueError, match="Unsafe archive"):
        import_archive(archive, "contoso_unsafe", tmp_path / "datasets")
    assert not (tmp_path / "escaped.csv").exists()


def test_nonexistent_unregistered_and_path_traversal_datasets_are_hidden(imported):
    destination, _ = imported
    (destination / "contoso_unregistered.sqlite3").write_bytes(b"not a database")
    (destination / "contoso_invalid.sqlite3").write_bytes(b"not a database")
    (destination / "contoso_invalid.manifest.json").write_text('{"schema_version":1,"dataset_id":"wrong"}')
    assert [item["database"] for item in installed_datasets()] == ["contoso_test"]
    for name in ("contoso_unregistered", "contoso_invalid", "../contoso_test", "contoso_missing"):
        with pytest.raises(ValueError, match="Unknown/uninstalled"):
            ContosoSampleService().set_dataset(name)


def test_null_boolean_utf16_and_quoted_multiline_fields(tmp_path):
    contents = 'ID;Active;Empty;Description\n1;true;;"First line\nSecond line"\n2;false;;"Quoted;value"\n'
    archive = archive_files(tmp_path, {"example.csv": contents.encode("utf-16")})
    destination = tmp_path / "datasets"
    report = import_archive(archive, "contoso_utf16", destination)
    assert report["total_rows"] == 2
    with sqlite3.connect(destination / "contoso_utf16.sqlite3") as db:
        assert db.execute("SELECT ID,Active,Empty,Description FROM example ORDER BY ID").fetchall() == [
            (1, 1, None, "First line\nSecond line"), (2, 0, None, "Quoted;value")]


def test_disabled_sample_and_native_query_timeout_are_enforced(imported, monkeypatch):
    source = DataSourceService()
    source.s = replace(source.s, enable_sample_execution=False)
    assert next(item for item in source.health()["sources"] if item["id"] == "contoso")["status"] == "not_configured"
    with pytest.raises(ValueError, match="disabled"):
        source.execute("contoso", "SELECT COUNT(*) FROM sales", "contoso_test")
    from app.config import get_settings
    monkeypatch.setattr("app.services.contoso_sample_service.get_settings", lambda: replace(get_settings(), query_timeout_seconds=0))
    with pytest.raises(ValueError, match="timeout"):
        ContosoSampleService().execute("WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<1000000) SELECT SUM(x) FROM n", database="contoso_test")


def test_official_release_html_fallback_keeps_published_checksum(monkeypatch):
    import io
    from scripts import install_contoso_official as installer
    checksum = "a" * 64
    html = f'<a href="{installer.RELEASE_PATH}csv-10k.7z">CSV 10K</a><clipboard-copy aria-label="Copy to clipboard digest for csv-10k.7z" value="sha256:{checksum}"></clipboard-copy>'
    monkeypatch.setattr(installer, "download_json", lambda _: (_ for _ in ()).throw(OSError("API blocked")))
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(html.encode()))
    assert installer.release_asset() == {"name": "csv-10k.7z", "browser_download_url": "https://github.com" + installer.RELEASE_PATH + "csv-10k.7z", "digest": "sha256:" + checksum}


def test_imported_dataset_reaches_governed_compiler_and_llm_contract(imported, bedrock_contract):
    from app.services.scope_service import ScopeService
    from app.services.phase2_service import Phase2Service
    from app.services.phase3_service import Phase3Service
    from app.services.phase4_service import Phase4Service
    from app.services.unified_ask_service import UnifiedAskService
    from app.config import BASE_DIR
    # Imported data coexists with existing samples in production. Mirror those
    # databases so graph projections of existing test workspaces remain available.
    destination, _ = imported
    for path in (BASE_DIR / "sample-data" / "contoso").glob("contoso_*.sqlite3"):
        shutil.copy2(path, destination / path.name)
        manifest = path.with_suffix(".manifest.json")
        if manifest.is_file():
            shutil.copy2(manifest, destination / manifest.name)
    workspace = "imported-" + uuid4().hex[:8]
    scope = {"scope_id": workspace + "-scope", "workspace_id": workspace, "source_id": "contoso", "tables": [{"database": "contoso_test", "table": "sales"}]}
    p2, p3 = Phase2Service(), Phase3Service()
    try:
        ScopeService().save(scope)
        ScopeService().build(scope["scope_id"])
        asset = p2.assets(workspace)[0]["asset_id"]
        p2.profile(workspace, asset, "standard", "creator", 100)
        p2.save_contract(workspace, asset, {"owner": "test reviewer"}, "creator")
        p2.transition_contract(workspace, asset, "reviewed", "Fixture schema reviewed", "creator")
        p2.transition_contract(workspace, asset, "certified", "Independent fixture review", "reviewer")
        expression = {"op": "divide", "args": [{"op": "multiply", "args": [{"column": "Quantity"}, {"column": "NetPrice"}]}, {"column": "ExchangeRate"}]}
        obj = p3.create(workspace, {"object_id": "net_sales_usd", "kind": "measure", "label": "Net sales USD", "description": "Fixture rate expresses units of local currency per USD", "binding": {"asset_id": asset, "columns": ["OrderKey", "LineNumber", "Quantity", "NetPrice", "ExchangeRate"]}, "semantics": {"grain": ["OrderKey", "LineNumber"], "aggregation": "sum", "expression": expression, "unit": "USD", "additivity": "additive"}}, "creator")
        obj = p3.transition(workspace, obj["object_id"], "reviewed", "Formula and composite grain reviewed", "creator", obj["version"])
        p3.transition(workspace, obj["object_id"], "certified", "Independent fixture meaning review", "reviewer", obj["version"])
        p3.publish_snapshot(workspace, "v1", "Imported dataset fixture", "reviewer")
        release = Phase4Service().promote(workspace, "v1", "reviewer")["release_id"]
        bedrock_contract.plan = {"base_asset_id": asset, "metrics": [{"metric_id": "net_sales_usd", "alias": "value"}], "dimensions": [], "join_relationship_ids": [], "filters": [], "having": [], "order_by": [], "limit": 50}
        output = UnifiedAskService().ask(workspace, release, "Net sales in USD")
        assert output["rows"] == [{"value": 180.5}]
        assert output["plan"]["execution_engine"] == "native"
        assert bedrock_contract.calls == ["semantic_planning", "semantic_verification"]
    finally:
        with p2.repo.lock:
            store = p2.repo._local()
            for rows in store.values():
                for key, row in list(rows.items()):
                    if workspace in (row.get("workspace_id"), row.get("market"), row.get("workspace")) or key == workspace or key.startswith(workspace + "::"):
                        rows.pop(key)
            p2.repo._save(store)
