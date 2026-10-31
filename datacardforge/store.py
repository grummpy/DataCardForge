"""Build, merge, and write a data card without dropping user edits."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from datacardforge import __version__
from datacardforge.render import render_html, render_markdown
from datacardforge.scan_images import scan as scan_images
from datacardforge.scan_tabular import scan as scan_tabular
from datacardforge.stats import (
    SPDX_LICENSES,
    missing_warnings,
    small_image_warning,
    thresholds,
)

SCHEMA_VERSION = "1.0.0"
CARD_OUTPUTS = ("DATACARD.md", "DATACARD.html", "datacard.json")
_CARD_NAMES = set(CARD_OUTPUTS)

README_NAMES = ("README.md", "README.rst", "README.txt", "README")
LICENSE_NAMES = (
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
    "LICENCE",
    "LICENCE.txt",
    "COPYING",
    "COPYING.txt",
)
SOURCE_NAMES = ("source.txt", "SOURCE.txt", "sources.txt", "SOURCES.txt")

_TEXT_FIELDS = (
    ("overview", "name"),
    ("overview", "version"),
    ("overview", "description"),
    ("overview", "created"),
    ("intended_use",),
    ("out_of_scope_use",),
)

_LICENSE_PATTERNS = (
    ("MIT", re.compile(r"\bMIT License\b|Permission is hereby granted, free of charge", re.I)),
    ("Apache-2.0", re.compile(r"Apache License", re.I)),
    ("LGPL-3.0-only", re.compile(r"GNU LESSER GENERAL PUBLIC LICENSE", re.I)),
    ("LGPL-2.1-only", re.compile(r"GNU LESSER GENERAL PUBLIC LICENSE.{0,40}Version 2", re.I | re.S)),
    ("GPL-3.0-only", re.compile(r"GNU GENERAL PUBLIC LICENSE.{0,80}Version 3", re.I | re.S)),
    ("GPL-2.0-only", re.compile(r"GNU GENERAL PUBLIC LICENSE.{0,80}Version 2", re.I | re.S)),
    ("MPL-2.0", re.compile(r"Mozilla Public License", re.I)),
    ("CC0-1.0", re.compile(r"CC0 1\.0|Creative Commons Zero", re.I)),
    ("CC-BY-SA-4.0", re.compile(r"Attribution-ShareAlike 4\.0|CC-BY-SA-4\.0", re.I)),
    ("CC-BY-4.0", re.compile(r"Creative Commons Attribution 4\.0|CC-BY-4\.0", re.I)),
    ("Unlicense", re.compile(r"The Unlicense|unencumbered software released into the public domain", re.I)),
    ("BSD-3-Clause", re.compile(r"BSD 3-Clause|Redistribution and use in source and binary forms", re.I)),
    ("BSD-2-Clause", re.compile(r"BSD 2-Clause", re.I)),
    ("ISC", re.compile(r"\bISC License\b", re.I)),
)


def scan_and_merge(root: Path, *, discard_edits: bool = False) -> dict:
    root = ensure_dataset_dir(root)
    fresh = build_fresh_card(root)
    previous = None if discard_edits else read_card(root)
    card = merge_cards(previous, fresh)
    write_outputs(root, card)
    return card


def save_edits(root: Path, edits: dict) -> dict:
    root = ensure_dataset_dir(root)
    card = read_card(root)
    if card is None:
        raise ValueError("Scan the dataset before saving edits.")
    updated = apply_edits(card, edits)
    write_outputs(root, updated)
    return updated


def preview_card(root: Path, edits: dict | None = None) -> dict:
    root = ensure_dataset_dir(root)
    card = read_card(root)
    if card is None:
        raise ValueError("Scan the dataset before preview.")
    if edits:
        return apply_edits(card, edits)
    return card


def build_fresh_card(root: Path) -> dict:
    root = root.resolve()
    tabular = scan_tabular(root)
    images = scan_images(root)
    kind = _kind(tabular, images)
    sources = collect_sources(root)
    detected = detect_license(root)
    balance = _primary_balance(tabular, images)
    bytes_on_disk, file_count, mtimes = measure_folder(root)
    description = _auto_description(root.name or str(root), kind, sources)
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": "datacardforge",
        "generator_version": __version__,
        "dataset_path": str(root),
        "kind": kind,
        "scanned_at": _now(),
        "overview": {
            "name": _text(root.name or str(root)),
            "version": _text("0.1.0"),
            "description": _text(description),
            "created": _text(_earliest_date(mtimes)),
        },
        "size": {
            "bytes": bytes_on_disk,
            "files": file_count,
            "rows": tabular["rows"],
            "columns": tabular["columns"],
            "tables": tabular["table_count"],
            "images": images["readable"],
            "unreadable_images": images["unreadable"],
            "resolution": images["resolution"],
        },
        "schema": tabular["schema"],
        "class_balance": balance,
        "missingness": tabular["missingness"],
        "duplicates": {"rows": tabular["duplicates"], "images": images["duplicates"]},
        "sources": {"auto": sources, "user": []},
        "license": {
            "value": detected["spdx"],
            "source": "auto",
            "auto_value": detected["spdx"],
            "detected_from": detected["path"],
        },
        "known_gaps": {"auto": _gaps(balance, tabular, images), "user": ""},
        "intended_use": _text(""),
        "out_of_scope_use": _text(""),
        "pii_hints": tabular["pii"],
        "errors": tabular["errors"] + images["errors"],
        "thresholds": thresholds(),
    }


def merge_cards(previous: dict | None, fresh: dict) -> dict:
    if not previous:
        return fresh
    merged = copy.deepcopy(fresh)
    for path in _TEXT_FIELDS:
        _preserve_text(_dig(previous, path), _dig(merged, path))
    old_license = previous.get("license") if isinstance(previous.get("license"), dict) else {}
    if old_license.get("source") == "user":
        value = str(old_license.get("value") or "unknown")
        merged["license"]["value"] = value
        merged["license"]["source"] = "auto" if value == merged["license"].get("auto_value") else "user"
    old_gaps = previous.get("known_gaps") if isinstance(previous.get("known_gaps"), dict) else {}
    user_gap = old_gaps.get("user", "")
    merged["known_gaps"]["user"] = user_gap if isinstance(user_gap, str) else str(user_gap or "")
    merged["sources"]["user"] = _clean_user_sources(
        (previous.get("sources") or {}).get("user") if isinstance(previous.get("sources"), dict) else []
    )
    return merged


def apply_edits(card: dict, edits: dict) -> dict:
    if not isinstance(edits, dict):
        raise ValueError("Edits must be an object.")
    updated = copy.deepcopy(card)
    mapping = {
        "name": ("overview", "name", 200, False),
        "version": ("overview", "version", 80, False),
        "description": ("overview", "description", 5000, False),
        "created": ("overview", "created", 32, True),
        "intended_use": ("intended_use", None, 5000, False),
        "out_of_scope_use": ("out_of_scope_use", None, 5000, False),
    }
    for key, (parent, child, limit, is_date) in mapping.items():
        if key not in edits or edits[key] is None:
            continue
        field = updated[parent] if child is None else updated[parent][child]
        _assign_text(field, edits[key], limit=limit, is_date=is_date, label=key)
    if "known_gaps_user" in edits and edits["known_gaps_user"] is not None:
        _assign_plain(updated["known_gaps"], "user", edits["known_gaps_user"], limit=5000, label="known gaps")
    if "license" in edits and edits["license"] is not None:
        _assign_license(updated["license"], edits["license"])
    if "sources_user" in edits and edits["sources_user"] is not None:
        updated["sources"]["user"] = _parse_user_sources(edits["sources_user"])
    return updated


def read_card(root: Path) -> dict | None:
    path = Path(root) / "datacard.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"datacard.json could not be read ({exc}). Scan again with discard to rebuild it."
        ) from exc
    if not isinstance(data, dict):
        raise ValueError("datacard.json is not an object.")
    return data


def write_outputs(root: Path, card: dict) -> None:
    root = Path(root)
    payload = json.dumps(card, indent=2, ensure_ascii=False) + "\n"
    _write(root / "datacard.json", payload)
    _write(root / "DATACARD.md", render_markdown(card))
    _write(root / "DATACARD.html", render_html(card))


def output_paths(root: Path) -> dict[str, str]:
    root = Path(root)
    return {
        "markdown": str(root / "DATACARD.md"),
        "html": str(root / "DATACARD.html"),
        "json": str(root / "datacard.json"),
    }


def ensure_dataset_dir(root: Path) -> Path:
    path = Path(root).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Folder does not exist: {path}")
    if not path.is_dir():
        raise ValueError(f"Not a folder: {path}")
    return path


def measure_folder(root: Path) -> tuple[int, int, list[float]]:
    total = 0
    files = 0
    mtimes: list[float] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.name in _CARD_NAMES:
            continue
        stat = path.stat()
        total += stat.st_size
        files += 1
        mtimes.append(stat.st_mtime)
    return total, files, mtimes


def collect_sources(root: Path) -> list[dict]:
    found = []
    readme = _first_file(root, README_NAMES)
    if readme:
        found.append(_source_record("readme", readme))
    license_file = _first_file(root, LICENSE_NAMES)
    if license_file:
        found.append(_source_record("license", license_file))
    source = _first_file(root, SOURCE_NAMES)
    if source:
        found.append(_source_record("source", source))
    return found


def detect_license(root: Path) -> dict:
    license_file = _first_file(root, LICENSE_NAMES)
    if not license_file:
        return {"spdx": "unknown", "path": None}
    text = license_file.read_text(encoding="utf-8", errors="replace")[:8000]
    return {"spdx": license_id_from_text(text) or "unknown", "path": license_file.name}


def license_id_from_text(text: str) -> str | None:
    match = re.search(r"SPDX-License-Identifier:\s*([A-Za-z0-9.\-+]+)", text)
    if match:
        return match.group(1)
    for spdx, pattern in _LICENSE_PATTERNS:
        if pattern.search(text):
            return spdx
    return None


def excerpt(text: str, limit: int = 400) -> str:
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        kept.append(stripped)
    blob = re.sub(r"\s+", " ", " ".join(part for part in kept if part)).strip()
    if len(blob) > limit:
        return blob[: limit - 1].rstrip() + "…"
    return blob


def _primary_balance(tabular: dict, images: dict) -> dict:
    tabular_balance = tabular["balance"]
    image_balance = images["balance"]
    if tabular_balance["total"] > 0:
        if image_balance["total"] > 0 and image_balance["source"] == "folders":
            combined = dict(tabular_balance)
            combined["image_counts"] = image_balance["counts"]
            return combined
        return tabular_balance
    if image_balance["total"] > 0:
        return image_balance
    return tabular_balance


def _gaps(balance: dict, tabular: dict, images: dict) -> list[str]:
    gaps = list(balance.get("warnings") or [])
    image_balance = images["balance"]
    if image_balance.get("source") == "folders" and balance.get("source") != "folders":
        for warning in image_balance.get("warnings") or []:
            if warning not in gaps:
                gaps.append(warning)
    gaps.extend(missing_warnings(tabular["missingness"]["columns"]))
    gaps.extend(small_image_warning(images["resolution"]["small_image_count"]))
    return gaps


def _kind(tabular: dict, images: dict) -> str:
    has_tables = tabular["table_count"] > 0
    has_images = images["readable"] > 0 or images["unreadable"] > 0
    if has_tables and has_images:
        return "mixed"
    if has_tables:
        return "tabular"
    if has_images:
        return "images"
    return "empty"


def _auto_description(name: str, kind: str, sources: list[dict]) -> str:
    for source in sources:
        if source["kind"] == "readme" and source["excerpt"]:
            return source["excerpt"]
    if kind == "empty":
        return "No CSV, Parquet, or class-folder images were found in this folder."
    return f"Local {kind} dataset '{name}', scanned by DataCardForge."


def _text(value: str) -> dict:
    value = "" if value is None else str(value)
    return {"value": value, "source": "auto", "auto_value": value}


def _preserve_text(old_field, new_field) -> None:
    if not isinstance(old_field, dict) or not isinstance(new_field, dict):
        return
    if old_field.get("source") != "user":
        return
    value = old_field.get("value", "")
    if not isinstance(value, str):
        value = str(value)
    new_field["value"] = value
    new_field["source"] = "auto" if value == new_field.get("auto_value") else "user"


def _assign_text(field: dict, raw, *, limit: int, is_date: bool, label: str) -> None:
    if not isinstance(raw, str):
        raise ValueError(f"{label} must be a string.")
    value = raw.strip()
    if len(value) > limit:
        raise ValueError(f"{label} is longer than {limit} characters.")
    if is_date and value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Created date must be YYYY-MM-DD.")
    field["value"] = value
    field["source"] = "user" if value != field.get("auto_value", "") else "auto"


def _assign_plain(container: dict, key: str, raw, *, limit: int, label: str) -> None:
    if not isinstance(raw, str):
        raise ValueError(f"{label} must be a string.")
    value = raw.strip()
    if len(value) > limit:
        raise ValueError(f"{label} is longer than {limit} characters.")
    container[key] = value


def _assign_license(field: dict, raw) -> None:
    if not isinstance(raw, str):
        raise ValueError("License must be a string.")
    value = raw.strip() or "unknown"
    allowed = set(SPDX_LICENSES)
    allowed.add(str(field.get("auto_value") or ""))
    allowed.add(str(field.get("value") or ""))
    if value not in allowed:
        raise ValueError(f"Unknown SPDX license '{value}'.")
    field["value"] = value
    field["source"] = "user" if value != field.get("auto_value") else "auto"


def _parse_user_sources(raw) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("sources_user must be a list.")
    if len(raw) > 50:
        raise ValueError("At most 50 source notes.")
    cleaned = []
    for item in raw:
        text = item.get("text") if isinstance(item, dict) else item
        if text is None:
            continue
        if not isinstance(text, str):
            raise ValueError("Source notes must be strings.")
        note = text.strip()
        if not note:
            continue
        if len(note) > 500:
            raise ValueError("A source note is longer than 500 characters.")
        cleaned.append({"text": note})
    return cleaned


def _clean_user_sources(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
            cleaned.append({"text": item["text"].strip()})
        elif isinstance(item, str) and item.strip():
            cleaned.append({"text": item.strip()})
    return cleaned


def _source_record(kind: str, path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    return {"kind": kind, "path": path.name, "excerpt": excerpt(text)}


def _first_file(root: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        path = root / name
        if path.is_file():
            return path
    return None


def _earliest_date(mtimes: list[float]) -> str:
    if not mtimes:
        stamp = datetime.now(timezone.utc)
    else:
        stamp = datetime.fromtimestamp(min(mtimes), timezone.utc)
    return stamp.date().isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dig(payload: dict, path: tuple[str, ...]):
    current = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _write(path: Path, text: str) -> None:
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
