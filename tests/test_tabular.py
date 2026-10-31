import csv
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from datacardforge.stats import percent
from datacardforge.store import scan_and_merge

HEADERS = ["sample_id", "width_px", "label", "contact_email", "phone", "person_name", "notes"]
ROWS = [
    ["s01", "64", "cat", "rowan@example.com", "555-0100", "Rowan Kepler", "alpha"],
    ["s02", "64", "cat", "mina@example.com", "555-0101", "Mina Quill", "beta"],
    ["s02", "64", "cat", "mina@example.com", "555-0101", "Mina Quill", "beta"],
    ["s03", "32", "cat", "theo@example.com", "555-0102", "Theo Byte", "gamma"],
    ["s04", "48", "cat", "nia@example.com", "555-0103", "Nia Forge", "delta"],
    ["s05", "80", "cat", "", "", "", ""],
    ["s06", "16", "dog", "ed@example.com", "555-0104", "Ed Pixel", "epsilon"],
    ["s07", "", "dog", "flo@example.com", "", "Flo Night", ""],
    ["s08", "24", "dog", "gy@example.com", "555-0105", "Gy Rate", "zeta"],
    ["s08", "24", "dog", "gy@example.com", "555-0105", "Gy Rate", "zeta"],
    ["s09", "40", "bird", "hi@example.com", "555-0106", "Hi Vector", "eta"],
    ["s10", "72", "cat", "", "", "", ""],
]


def write_csv(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "measurements.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        writer.writerows(ROWS)
    return path


def column(card, name):
    return next(item for item in card["schema"] if item["column"] == name)


def missing(card, name):
    return next(item for item in card["missingness"]["columns"] if item["column"] == name)


def test_csv_size_schema_balance_missingness_and_dupes(tmp_path):
    path = write_csv(tmp_path / "shapes")
    card = scan_and_merge(path.parent)
    assert card["kind"] == "tabular"
    assert card["schema_version"] == "1.0.0"
    assert card["size"]["rows"] == 12
    assert card["size"]["columns"] == 7
    assert card["size"]["files"] == 1
    assert card["size"]["bytes"] == path.stat().st_size
    assert card["size"]["images"] == 0

    label = column(card, "label")
    assert label["dtype"] == "string"
    assert label["unique_count"] == 3
    assert label["examples"] == ["cat", "dog", "bird"]
    assert column(card, "width_px")["dtype"] == "integer"
    assert column(card, "width_px")["null_count"] == 1

    balance = card["class_balance"]
    assert balance["source"] == "column:label"
    assert balance["total"] == 12
    counts = {row["label"]: row for row in balance["counts"]}
    assert counts["cat"]["count"] == 7
    assert counts["dog"]["count"] == 4
    assert counts["bird"]["count"] == 1
    assert counts["bird"]["percent"] == percent(1, 12)
    assert balance["imbalance_ratio"] == 7.0

    assert missing(card, "phone")["null_count"] == 3
    assert missing(card, "phone")["null_percent"] == 25.0
    assert missing(card, "notes")["null_percent"] == 25.0
    assert missing(card, "contact_email")["null_percent"] == percent(2, 12)
    assert card["missingness"]["rows_with_any_missing"] == 3
    assert card["missingness"]["rows_with_any_missing_percent"] == 25.0

    dupes = card["duplicates"]["rows"]
    assert dupes["extra_duplicate_rows"] == 2
    assert dupes["duplicate_groups"] == 2
    assert dupes["rows_in_duplicate_groups"] == 4

    hinted = {hint["column"]: hint["kind"] for hint in card["pii_hints"]}
    assert hinted["contact_email"] == "email"
    assert hinted["phone"] == "phone"
    assert hinted["person_name"] == "name"
    assert "label" not in hinted
    assert "sample_id" not in hinted

    gaps = " ".join(card["known_gaps"]["auto"])
    assert "Rare class 'bird'" in gaps
    assert "phone" in gaps
    assert "notes" in gaps
    assert "7.000" in gaps


def test_parquet_class_column_nulls_and_duplicate(tmp_path):
    folder = tmp_path / "parquet"
    folder.mkdir()
    rows = [
        {"sample_id": "p1", "score": 1.5, "class": "red"},
        {"sample_id": "p2", "score": 2.5, "class": "red"},
        {"sample_id": "p2", "score": 2.5, "class": "red"},
        {"sample_id": "p3", "score": None, "class": "blue"},
    ]
    schema = pa.schema(
        [("sample_id", pa.string()), ("score", pa.float64()), ("class", pa.string())]
    )
    path = folder / "shapes.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    card = scan_and_merge(folder)
    assert card["kind"] == "tabular"
    assert card["size"]["rows"] == 4
    assert card["size"]["columns"] == 3
    assert card["size"]["bytes"] == path.stat().st_size
    assert column(card, "score")["dtype"] == "float"
    assert column(card, "score")["null_count"] == 1
    assert card["class_balance"]["source"] == "column:class"
    counts = {row["label"]: row["count"] for row in card["class_balance"]["counts"]}
    assert counts == {"red": 3, "blue": 1}
    assert card["class_balance"]["imbalance_ratio"] == 3.0
    assert card["class_balance"]["warnings"] == []
    assert card["missingness"]["rows_with_any_missing"] == 1
    assert missing(card, "score")["null_percent"] == 25.0
    assert card["duplicates"]["rows"]["extra_duplicate_rows"] == 1
    assert any("score" in gap for gap in card["known_gaps"]["auto"])


def test_header_only_csv_and_unlabeled_table(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "only.csv").write_text("id,label\n", encoding="utf-8")
    card = scan_and_merge(empty)
    assert card["size"]["rows"] == 0
    assert card["size"]["columns"] == 2
    assert card["duplicates"]["rows"]["extra_duplicate_rows"] == 0

    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "values.csv").write_text("width,height\n10,12\n", encoding="utf-8")
    unlabeled = scan_and_merge(plain)
    assert unlabeled["class_balance"]["source"] == "none"
    assert unlabeled["class_balance"]["total"] == 0
    assert unlabeled["pii_hints"] == []


def test_bad_tabular_file_is_reported(tmp_path):
    folder = tmp_path / "broken"
    folder.mkdir()
    (folder / "notes.csv").write_bytes(b"\xff\xfe not,really\n")
    (folder / "ok.csv").write_text("label\ncat\n", encoding="utf-8")
    card = scan_and_merge(folder)
    assert card["size"]["rows"] == 1
    assert card["errors"]
    assert any("notes.csv" in message for message in card["errors"])
