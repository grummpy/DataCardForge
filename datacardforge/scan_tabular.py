"""Read CSV and Parquet files sitting in a dataset folder."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from datacardforge.dupes import row_duplicates
from datacardforge.stats import (
    balance_from_counts,
    detect_label_column,
    empty_balance,
    percent,
    pii_hints,
)

TABULAR_EXTENSIONS = {".csv", ".parquet"}


def has_tabular_files(root: Path) -> bool:
    return any(_is_tabular(path) for path in _children(root))


def scan(root: Path) -> dict:
    tables = []
    errors: list[str] = []
    for path in _children(root):
        if not _is_tabular(path):
            continue
        try:
            tables.append(_scan_file(path))
        except Exception as exc:  # a bad file should not sink the whole card
            errors.append(f"{path.name}: {exc}")

    schema: list[dict] = []
    missing_columns: list[dict] = []
    pii: list[dict] = []
    duplicate_tables: list[dict] = []
    counts: dict[str, int] = {}
    unlabeled = 0
    labeled_sources: list[str] = []
    rows = 0
    missing_rows = 0

    for table in tables:
        rows += table["rows"]
        missing_rows += table["rows_with_any_missing"]
        schema.extend(table["schema"])
        missing_columns.extend(table["missing_columns"])
        pii.extend(table["pii"])
        duplicate_tables.append(
            {
                "table": table["name"],
                "extra_duplicate_rows": table["duplicates"]["extra_duplicate_rows"],
                "rows_in_duplicate_groups": table["duplicates"]["rows_in_duplicate_groups"],
                "duplicate_groups": table["duplicates"]["duplicate_groups"],
            }
        )
        if table["label_column"]:
            labeled_sources.append(table["label_column"])
            unlabeled += table["unlabeled"]
            for label, count in table["label_counts"].items():
                counts[label] = counts.get(label, 0) + count

    if len(tables) == 1:
        columns = tables[0]["column_count"]
    else:
        columns = sum(table["column_count"] for table in tables)

    if not labeled_sources:
        balance = empty_balance()
    elif len(tables) == 1:
        balance = balance_from_counts(
            counts, unlabeled=unlabeled, source=f"column:{labeled_sources[0]}"
        )
    else:
        same = {source for source in labeled_sources}
        source = f"column:{labeled_sources[0]}" if len(same) == 1 else "columns"
        balance = balance_from_counts(counts, unlabeled=unlabeled, source=source)

    return {
        "tables": [
            {"name": table["name"], "rows": table["rows"], "columns": table["column_count"]}
            for table in tables
        ],
        "table_count": len(tables),
        "rows": rows,
        "columns": columns,
        "schema": schema,
        "missingness": {
            "rows": rows,
            "rows_with_any_missing": missing_rows,
            "rows_with_any_missing_percent": percent(missing_rows, rows),
            "columns": missing_columns,
        },
        "duplicates": {
            "extra_duplicate_rows": sum(item["extra_duplicate_rows"] for item in duplicate_tables),
            "rows_in_duplicate_groups": sum(
                item["rows_in_duplicate_groups"] for item in duplicate_tables
            ),
            "duplicate_groups": sum(item["duplicate_groups"] for item in duplicate_tables),
            "tables": duplicate_tables,
        },
        "balance": balance,
        "pii": pii,
        "errors": errors,
    }


def _scan_file(path: Path) -> dict:
    arrow = _read_arrow(path)
    columns = list(arrow.column_names)
    records = arrow.to_pylist()
    rows = len(records)
    schema = []
    missing_columns = []
    missing_rows = 0
    for record in records:
        if any(_missing(record.get(column)) for column in columns):
            missing_rows += 1

    for name in columns:
        dtype = _friendly_type(arrow.schema.field(name).type)
        examples: list[str] = []
        seen: set = set()
        nulls = 0
        for record in records:
            value = record.get(name)
            if _missing(value):
                nulls += 1
                continue
            key = _hashable(value)
            if key in seen:
                continue
            seen.add(key)
            if len(examples) < 3:
                examples.append(_example(value))
        schema.append(
            {
                "table": path.name,
                "column": name,
                "dtype": dtype,
                "examples": examples,
                "unique_count": len(seen),
                "null_count": nulls,
                "non_null_count": rows - nulls,
            }
        )
        missing_columns.append(
            {
                "table": path.name,
                "column": name,
                "null_count": nulls,
                "null_percent": percent(nulls, rows),
                "rows": rows,
            }
        )

    label_column = detect_label_column(columns)
    label_counts: dict[str, int] = {}
    unlabeled = 0
    if label_column:
        for record in records:
            value = record.get(label_column)
            if _missing(value):
                unlabeled += 1
                continue
            label = _example(value)
            label_counts[label] = label_counts.get(label, 0) + 1

    return {
        "name": path.name,
        "rows": rows,
        "column_count": len(columns),
        "schema": schema,
        "missing_columns": missing_columns,
        "rows_with_any_missing": missing_rows,
        "duplicates": row_duplicates(records, columns),
        "label_column": label_column,
        "label_counts": label_counts,
        "unlabeled": unlabeled,
        "pii": pii_hints(path.name, columns, records, label_column=label_column),
    }


def _read_arrow(path: Path) -> pa.Table:
    if path.suffix.lower() == ".csv":
        convert = pacsv.ConvertOptions(null_values=[""], strings_can_be_null=True)
        read = pacsv.ReadOptions(encoding="utf-8")
        return pacsv.read_csv(path, read_options=read, convert_options=convert)
    return pq.read_table(path)


def _friendly_type(dtype: pa.DataType) -> str:
    if pa.types.is_dictionary(dtype):
        dtype = dtype.value_type
    if pa.types.is_integer(dtype):
        return "integer"
    if pa.types.is_floating(dtype):
        return "float"
    if pa.types.is_boolean(dtype):
        return "boolean"
    if pa.types.is_temporal(dtype):
        return "datetime"
    if pa.types.is_string(dtype) or pa.types.is_large_string(dtype) or pa.types.is_null(dtype):
        return "string"
    return str(dtype)


def _children(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted((path for path in root.iterdir() if path.is_file()), key=lambda path: path.name.lower())


def _is_tabular(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in TABULAR_EXTENSIONS


def _missing(value) -> bool:
    if value is None:
        return True
    return isinstance(value, float) and value != value


def _hashable(value):
    if isinstance(value, (str, int, float, bool, bytes)):
        return value
    return str(value)


def _example(value) -> str:
    if isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = str(value)
    text = " ".join(text.split())
    if len(text) > 80:
        return text[:79] + "…"
    return text
