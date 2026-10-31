import re
import shutil
from pathlib import Path

from datacardforge.store import scan_and_merge

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


def test_committed_samples_are_synthetic_and_scan(tmp_path):
    csv_path = SAMPLES / "colored-shapes-csv" / "measurements.csv"
    text = csv_path.read_text(encoding="utf-8")
    assert "@example.com" in text
    assert "@gmail" not in text.lower()
    assert "sk-" not in text
    assert re.search(r"\b\d{3}-\d{2}-\d{4}\b", text) is None

    csv_copy = _copy(tmp_path, "colored-shapes-csv")
    csv_card = scan_and_merge(csv_copy)
    assert csv_card["kind"] == "tabular"
    assert csv_card["license"]["auto_value"] == "MIT"
    assert csv_card["duplicates"]["rows"]["extra_duplicate_rows"] >= 1
    assert csv_card["missingness"]["rows_with_any_missing"] >= 1
    assert any(hint["kind"] == "email" for hint in csv_card["pii_hints"])
    assert any("triangle" in gap for gap in csv_card["known_gaps"]["auto"])
    assert (csv_copy / "DATACARD.md").is_file()
    assert (csv_copy / "DATACARD.html").is_file()
    assert (csv_copy / "datacard.json").is_file()
    assert "<svg" in (csv_copy / "DATACARD.html").read_text(encoding="utf-8")

    parquet_copy = _copy(tmp_path, "colored-shapes-parquet")
    parquet_card = scan_and_merge(parquet_copy)
    assert parquet_card["kind"] == "tabular"
    assert parquet_card["class_balance"]["source"] == "column:class"
    assert parquet_card["license"]["auto_value"] == "Apache-2.0"
    assert parquet_card["duplicates"]["rows"]["extra_duplicate_rows"] >= 1
    assert parquet_card["missingness"]["rows_with_any_missing"] >= 1

    image_copy = _copy(tmp_path, "colored-shapes-images")
    image_card = scan_and_merge(image_copy)
    assert image_card["kind"] == "images"
    assert image_card["size"]["images"] >= 3
    images = image_card["duplicates"]["images"]
    assert images["exact_extra_files"] == 1
    assert images["near_extra_files"] == 1
    assert images["near_groups"][0]["paths"] == [
        "circle/crimson.jpg",
        "circle/crimson_copy.jpg",
        "circle/crimson_near.jpg",
    ]
    assert image_card["size"]["resolution"]["small_image_count"] >= 1
    assert image_card["class_balance"]["total"] == image_card["size"]["images"]


def _copy(tmp_path: Path, name: str) -> Path:
    dest = tmp_path / name
    shutil.copytree(SAMPLES / name, dest)
    return dest
