"""Import user-supplied Contoso CSV archives without inventing business meanings."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sqlite3
import tempfile
import time
from contextlib import closing, contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path, PurePosixPath

from filelock import FileLock

DATASET_ID = re.compile(r"contoso_[a-z0-9_]{1,48}\Z")
INTEGER = re.compile(r"[+-]?(?:0|[1-9][0-9]*)\Z")
NUMBER = re.compile(r"[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")


def identifier(value):
    name = re.sub(r"[^A-Za-z0-9_]", "_", value.strip()).strip("_")[:62]
    if not name:
        raise ValueError("Empty CSV table or column identifier")
    return "T_" + name if name[0].isdigit() else name


def quote(value):
    return '"' + value.replace('"', '""') + '"'


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def value_type(value):
    if value == "":
        return None
    # Leading zero identifiers and surrounding whitespace remain verbatim text.
    if INTEGER.fullmatch(value):
        return "INTEGER" if -(2**63) <= int(value) < 2**63 else "TEXT"
    if NUMBER.fullmatch(value):
        number = Decimal(value)
        approximate = float(number)
        if math.isfinite(approximate) and (approximate != 0 or number == 0):
            return "REAL"
        return "TEXT"
    if value.lower() in {"true", "false"}:
        return "BOOLEAN"
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            date.fromisoformat(value)
            return "DATE"
        if re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", value):
            parsed = datetime.fromisoformat(value)
            return "TIMESTAMPTZ" if parsed.tzinfo else "TIMESTAMP"
    except ValueError:
        pass
    return "TEXT"


@contextmanager
def csv_rows(path):
    with path.open("rb") as handle:
        prefix = handle.read(4)
    encoding = "utf-16" if prefix.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    with path.open(encoding=encoding, newline="", errors="strict") as handle:
        probe = handle.read(65536)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(probe, delimiters=",;\t|")
        except csv.Error:
            # Malformed data is still rejected by the width and strict parser checks.
            dialect = csv.excel
        reader = csv.reader(handle, dialect, strict=True)
        headers = next(reader, None)
        if not headers or len(headers) > 1024:
            raise ValueError(f"Missing or excessive CSV headers: {path.name}")
        columns = [identifier(header) for header in headers]
        if len({name.lower() for name in columns}) != len(columns):
            raise ValueError(f"CSV column names collide after normalization: {path.name}")
        yield reader, headers, columns


def inspect_csv(path, max_rows):
    with csv_rows(path) as (reader, headers, columns):
        kinds = [set() for _ in columns]
        nulls = [0 for _ in columns]
        large_integers = [False for _ in columns]
        rows = 0
        for row in reader:
            if len(row) != len(columns):
                raise ValueError(f"Malformed CSV row in {path.name}, line {reader.line_num}: expected {len(columns)} fields, got {len(row)}")
            rows += 1
            if rows > max_rows:
                raise ValueError(f"CSV row limit exceeded: {path.name}")
            for i, value in enumerate(row):
                kind = value_type(value)
                if kind is None:
                    nulls[i] += 1
                else:
                    kinds[i].add(kind)
                    if kind == "INTEGER" and abs(int(value)) > 2**53:
                        large_integers[i] = True
        types = []
        for i, seen in enumerate(kinds):
            if len(seen) == 1:
                types.append(next(iter(seen)))
            elif seen == {"INTEGER", "REAL"} and not large_integers[i]:
                types.append("REAL")
            else:
                types.append("TEXT")
        return {"rows": rows, "columns": [
            {"name": name, "source_name": header, "type": typ, "null_count": nulls[i],
             "mixed_types": len(kinds[i]) > 1}
            for i, (name, header, typ) in enumerate(zip(columns, headers, types))]}


def converted(value, typ):
    if value == "":
        return None
    if typ == "INTEGER":
        return int(value)
    if typ == "REAL":
        return float(value)
    if typ == "BOOLEAN":
        return int(value.lower() == "true")
    return value


def load_csv(connection, path, table, details):
    columns = details["columns"]
    connection.execute(f"CREATE TABLE {quote(table)} (" + ", ".join(
        f"{quote(column['name'])} {column['type']}" for column in columns) + ")")
    sql = f"INSERT INTO {quote(table)} VALUES (" + ",".join("?" for _ in columns) + ")"
    with csv_rows(path) as (reader, headers, names):
        if names != [column["name"] for column in columns]:
            raise ValueError(f"CSV headers changed during import: {path.name}")
        batch = []
        count = 0
        for row in reader:
            if len(row) != len(columns):
                raise ValueError(f"Malformed CSV row during import: {path.name}, line {reader.line_num}")
            batch.append(tuple(converted(value, column["type"]) for value, column in zip(row, columns)))
            count += 1
            if len(batch) == 2000:
                connection.executemany(sql, batch)
                batch.clear()
        if batch:
            connection.executemany(sql, batch)
    if count != details["rows"]:
        raise ValueError(f"CSV row count changed during import: {path.name}")
    # Ordinary indexes improve key joins; they do not assert PK/FK or uniqueness.
    for column in columns:
        if re.search(r"(?:key|_id)$", column["name"], re.I):
            index = "idx_" + table + "_" + column["name"]
            connection.execute(f"CREATE INDEX {quote(index)} ON {quote(table)} ({quote(column['name'])})")
    actual = connection.execute(f"SELECT COUNT(*) FROM {quote(table)}").fetchone()[0]
    if actual != count:
        raise ValueError(f"Imported table count mismatch: {table}")


def extract_csvs(archive, destination, max_unpacked_bytes):
    try:
        import py7zr
    except ImportError as exc:
        raise ValueError("Install archive support: python -m pip install -r requirements-contoso.txt") from exc
    with py7zr.SevenZipFile(archive, mode="r") as handle:
        if handle.needs_password():
            raise ValueError("Encrypted Contoso archives are not supported")
        members = handle.list()
        names = set()
        csv_names = []
        unpacked = 0
        for member in members:
            name = member.filename
            path = PurePosixPath(name.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or ":" in name or member.is_symlink:
                raise ValueError("Unsafe archive member rejected")
            if name.casefold() in names:
                raise ValueError("Duplicate archive member rejected")
            names.add(name.casefold())
            if not member.is_directory:
                unpacked += member.uncompressed
            if not member.is_directory and path.suffix.lower() == ".csv":
                csv_names.append(name)
        if unpacked > max_unpacked_bytes:
            raise ValueError("Archive exceeds configured uncompressed size limit")
        if not csv_names or len(csv_names) > 256:
            raise ValueError("Archive must contain between 1 and 256 CSV files")
        # Documents and executable files in an attachment are never imported or run.
        handle.extract(path=destination, targets=csv_names)
    csvs = sorted(path for path in destination.rglob("*") if path.suffix.lower() == ".csv")
    if len(csvs) != len(csv_names) or any(path.is_symlink() for path in csvs):
        raise ValueError("Archive extraction did not produce the expected CSV files")
    if sum(path.stat().st_size for path in csvs) > max_unpacked_bytes:
        raise ValueError("Extracted CSV size limit exceeded")
    return csvs


def import_archive(archive, dataset_id, destination, *, expected_sha256=None,
                   provenance="user-supplied archive; upstream origin not independently verified",
                   max_unpacked_bytes=8 * 1024**3, max_rows_per_table=10_000_000):
    """Publish a new dataset only after complete inference, import and integrity checks.

    Existing dataset IDs cannot be replaced: changing physical data under a certified
    workspace requires explicit migration and a fresh review, not a silent import.
    """
    archive = Path(archive).resolve()
    destination = Path(destination).resolve()
    if not DATASET_ID.fullmatch(dataset_id) or dataset_id == "contoso_demo":
        raise ValueError("Use a dataset ID such as contoso_1m; the bundled demo cannot be replaced")
    if not archive.is_file() or archive.suffix.lower() != ".7z":
        raise ValueError("Provide an existing .7z CSV archive")
    if archive.stat().st_size > 2 * 1024**3:
        raise ValueError("Compressed archive exceeds the 2 GiB limit")
    checksum = sha256_file(archive)
    if expected_sha256 is not None and (not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha256)
                                        or checksum != expected_sha256.lower()):
        raise ValueError("Archive SHA-256 mismatch")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / (dataset_id + ".sqlite3")
    manifest_path = destination / (dataset_id + ".manifest.json")
    started = time.monotonic()
    with FileLock(str(destination / ".contoso-import.lock"), timeout=30):
        if target.exists() or manifest_path.exists():
            raise ValueError("Dataset ID already exists; use a new ID to preserve existing workspaces")
        with tempfile.TemporaryDirectory(prefix=".contoso-import-", dir=destination) as temporary:
            staging = Path(temporary)
            extracted = staging / "csv"
            extracted.mkdir()
            csvs = extract_csvs(archive, extracted, max_unpacked_bytes)
            tables = {}
            total_rows = 0
            database = staging / target.name
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("PRAGMA journal_mode=OFF")
                connection.execute("PRAGMA synchronous=OFF")
                connection.execute("PRAGMA cache_size=-65536")
                for csv_path in csvs:
                    table = identifier(csv_path.stem)
                    if table.lower() in {name.lower() for name in tables}:
                        raise ValueError("CSV table names collide after normalization")
                    details = inspect_csv(csv_path, max_rows_per_table)
                    details["source_file"] = csv_path.relative_to(extracted).as_posix()
                    total_rows += details["rows"]
                    if total_rows > 40_000_000:
                        raise ValueError("Archive exceeds the 40 million total row limit")
                    load_csv(connection, csv_path, table, details)
                    tables[table] = details
                    connection.commit()
                if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise ValueError("Imported SQLite integrity check failed")
            if sha256_file(archive) != checksum:
                raise ValueError("Archive changed during import")
            manifest = {
                "schema_version": 1, "dataset_id": dataset_id, "database": target.name,
                "archive": archive.name, "archive_sha256": checksum,
                "upstream_checksum_verified": expected_sha256 is not None,
                "provenance": provenance, "installed_at": datetime.now(timezone.utc).isoformat(),
                "total_rows": total_rows, "tables": tables,
                "database_bytes": database.stat().st_size,
                "import_seconds": round(time.monotonic() - started, 3),
                "notes": ["Types inferred from every nonempty value, not a row sample.",
                          "Empty fields become NULL; compatible numeric mixtures become REAL; other mixed/unsafe values remain TEXT.",
                          "REAL is binary floating point, not exact decimal arithmetic.",
                          "No PK/FK, relationship, metric or concept is automatically certified."]}
            staged_manifest = staging / manifest_path.name
            staged_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            staged_manifest.replace(manifest_path)
            try:
                database.replace(target)
            except BaseException:
                manifest_path.unlink(missing_ok=True)
                raise
    return manifest
