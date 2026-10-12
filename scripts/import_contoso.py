"""Install an existing Contoso CSV .7z archive as an optional named dataset."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.contoso_import_service import import_archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Path to your existing csv-1m.7z")
    parser.add_argument("--dataset-id", default="contoso_1m", help="New dataset name; existing IDs are never overwritten")
    parser.add_argument("--destination", type=Path, default=ROOT / "sample-data" / "contoso")
    parser.add_argument("--sha256", help="Optional independently obtained expected archive checksum")
    args = parser.parse_args()
    try:
        result = import_archive(args.archive, args.dataset_id, args.destination, expected_sha256=args.sha256)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Contoso import failed: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
