"""Thresholds, class balance, missingness, and PII hint rules."""

from __future__ import annotations

import re
from collections import Counter

IMBALANCE_RATIO_WARN = 3.0
RARE_CLASS_PERCENT = 10.0
HIGH_MISSING_PERCENT = 20.0
SMALL_IMAGE_MIN_SIDE = 32

# Near-duplicate images must satisfy both a structural perceptual hash
# and a coarse color distance, so a recolored shape is not a near copy.
NEAR_HAMMING_MAX = 8
# 14 keeps a uniform +12 brightness shift (MAE about 12, including JPEG noise)
# while a recolored shape of the same outline stays above it.
NEAR_COLOR_MAE_MAX = 14.0

LABEL_COLUMNS = ("label", "class", "target")

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(
    r"^(?:"
    r"\+?\d{1,3}[\s.\-]?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}"
    r"|\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}"
    r"|\d{3}[\s.\-]\d{4}"
    r")$"
)
NAME_VALUE_RE = re.compile(r"^[A-Z][a-z]+(?:[ '\-][A-Z][a-z]+)+$")
NAME_COLUMN_RE = re.compile(
    r"(^|[_\s-])(full_?name|first_?name|last_?name|given_?name|family_?name|"
    r"surname|person_?name|artist_?name|contact_?name|customer_?name)($|[_\s-])",
    re.IGNORECASE,
)
EMAIL_COLUMN_RE = re.compile(r"e-?mail", re.IGNORECASE)
PHONE_COLUMN_RE = re.compile(
    r"(^|[_\s-])(phone|mobile|tel|telephone)($|[_\s-]|$)",
    re.IGNORECASE,
)

SPDX_LICENSES = [
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "GPL-2.0-only",
    "GPL-3.0-only",
    "LGPL-2.1-only",
    "LGPL-3.0-only",
    "MPL-2.0",
    "CDDL-1.0",
    "EPL-2.0",
    "ISC",
    "Zlib",
    "BSL-1.0",
    "CC0-1.0",
    "CC-BY-4.0",
    "CC-BY-SA-4.0",
    "Unlicense",
    "LicenseRef-proprietary",
    "unknown",
]


def percent(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round(100.0 * part / whole, 2)


def detect_label_column(columns: list[str]) -> str | None:
    """Prefer `label`, then `class`, then `target` (case-insensitive, exact)."""
    by_lower = {column.lower(): column for column in columns}
    for name in LABEL_COLUMNS:
        if name in by_lower:
            return by_lower[name]
    return None


def balance_from_counts(counts: dict[str, int], *, unlabeled: int = 0, source: str) -> dict:
    items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    total = sum(counts.values())
    rows = [
        {"label": label, "count": count, "percent": percent(count, total)}
        for label, count in items
    ]
    if total <= 0 or not items:
        ratio = None
    elif len(items) == 1:
        ratio = 1.0
    else:
        ratio = round(items[0][1] / items[-1][1], 3)
    return {
        "source": source,
        "counts": rows,
        "total": total,
        "unlabeled": unlabeled,
        "imbalance_ratio": ratio,
        "warnings": balance_warnings(rows, total, ratio),
    }


def empty_balance() -> dict:
    return balance_from_counts({}, source="none")


def balance_warnings(rows: list[dict], total: int, ratio: float | None) -> list[str]:
    warnings: list[str] = []
    if ratio is not None and ratio > IMBALANCE_RATIO_WARN and len(rows) >= 2:
        warnings.append(
            f"Class imbalance ratio {ratio:.3f} exceeds {IMBALANCE_RATIO_WARN:.1f}."
        )
    if total > 0 and len(rows) >= 2:
        rare = [row for row in rows if row["percent"] < RARE_CLASS_PERCENT]
        rare.sort(key=lambda row: (row["percent"], row["label"]))
        for row in rare:
            warnings.append(
                f"Rare class '{row['label']}' has {row['count']} of {total} "
                f"({row['percent']:.2f}%), below {RARE_CLASS_PERCENT:.0f}%."
            )
    return warnings


def missing_warnings(columns: list[dict]) -> list[str]:
    flagged = [
        column
        for column in columns
        if column["null_percent"] > HIGH_MISSING_PERCENT and column["rows"] > 0
    ]
    flagged.sort(key=lambda column: (-column["null_percent"], column["column"]))
    messages = []
    for column in flagged:
        table = column.get("table")
        name = column["column"] if not table else f"{table}.{column['column']}"
        # A single table reads more clearly without the file prefix.
        if table and sum(1 for item in columns if item["column"] == column["column"]) == 1:
            name = column["column"]
        messages.append(
            f"Column '{name}' is {column['null_percent']:.2f}% missing "
            f"(threshold {HIGH_MISSING_PERCENT:.0f}%)."
        )
    return messages


def small_image_warning(count: int) -> list[str]:
    if count <= 0:
        return []
    return [
        f"{count} image(s) are smaller than {SMALL_IMAGE_MIN_SIDE}px on the shortest side."
    ]


def pii_hints(
    table: str,
    columns: list[str],
    records: list[dict],
    *,
    label_column: str | None = None,
) -> list[dict]:
    hints = []
    for column in columns:
        values = [record.get(column) for record in records]
        non_null = [value for value in values if not _missing(value)]
        texts = [str(value).strip() for value in non_null]
        email_hits = sum(1 for text in texts if EMAIL_RE.match(text))
        phone_hits = sum(1 for text in texts if PHONE_RE.match(text))
        name_hits = sum(1 for text in texts if NAME_VALUE_RE.match(text))
        email_pct = percent(email_hits, len(texts)) if texts else 0.0
        phone_pct = percent(phone_hits, len(texts)) if texts else 0.0
        name_pct = percent(name_hits, len(texts)) if texts else 0.0

        if EMAIL_COLUMN_RE.search(column) or (texts and email_pct >= 50.0 and email_hits >= 1):
            hints.append(
                _hint(table, column, "email", email_pct, len(texts), _email_reason(column, email_pct))
            )
        if PHONE_COLUMN_RE.search(column) or (texts and phone_pct >= 50.0 and phone_hits >= 1):
            hints.append(
                _hint(table, column, "phone", phone_pct, len(texts), _phone_reason(column, phone_pct))
            )
        if column != label_column and (
            NAME_COLUMN_RE.search(column) or (texts and name_pct >= 60.0 and name_hits >= 1 and _name_token(column))
        ):
            hints.append(
                _hint(table, column, "name", name_pct, len(texts), _name_reason(column, name_pct))
            )
    return hints


def _hint(table, column, kind, match_percent, non_null, reason) -> dict:
    return {
        "table": table,
        "column": column,
        "kind": kind,
        "match_percent": match_percent,
        "non_null": non_null,
        "reason": reason,
    }


def _email_reason(column: str, match_percent: float) -> str:
    if EMAIL_COLUMN_RE.search(column) and match_percent <= 0:
        return "column name looks like an email field"
    if EMAIL_COLUMN_RE.search(column):
        return "column name looks like an email field and values match an email pattern"
    return "values match an email pattern"


def _phone_reason(column: str, match_percent: float) -> str:
    if PHONE_COLUMN_RE.search(column) and match_percent <= 0:
        return "column name looks like a phone field"
    if PHONE_COLUMN_RE.search(column):
        return "column name looks like a phone field and values match a phone pattern"
    return "values match a phone pattern"


def _name_reason(column: str, match_percent: float) -> str:
    if NAME_COLUMN_RE.search(column) and match_percent <= 0:
        return "column name looks like a personal-name field"
    if NAME_COLUMN_RE.search(column):
        return "column name looks like a personal-name field and values look like personal names"
    return "values look like personal names"


def _name_token(column: str) -> bool:
    return bool(re.search(r"(^|[_\s-])names?($|[_\s-])", column, re.IGNORECASE))


def _missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and value != value:
        return True
    return False


def thresholds() -> dict:
    return {
        "imbalance_ratio": IMBALANCE_RATIO_WARN,
        "rare_class_percent": RARE_CLASS_PERCENT,
        "high_missing_percent": HIGH_MISSING_PERCENT,
        "small_image_min_side": SMALL_IMAGE_MIN_SIDE,
        "near_duplicate_hamming": NEAR_HAMMING_MAX,
        "near_duplicate_color_mae": NEAR_COLOR_MAE_MAX,
    }
