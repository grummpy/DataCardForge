from datacardforge.stats import (
    PHONE_RE,
    balance_from_counts,
    detect_label_column,
    percent,
    pii_hints,
)
from datacardforge.store import license_id_from_text


def test_percent_and_label_preference():
    assert percent(1, 12) == 8.33
    assert percent(2, 12) == 16.67
    assert percent(3, 12) == 25.0
    assert percent(0, 0) == 0.0
    assert detect_label_column(["id", "Class", "label", "target"]) == "label"
    assert detect_label_column(["id", "Target"]) == "Target"
    assert detect_label_column(["notes"]) is None


def test_phone_patterns_and_balance_warnings():
    assert PHONE_RE.match("555-0100")
    assert PHONE_RE.match("555-010-1234")
    assert PHONE_RE.match("(555) 010-1234")
    assert not PHONE_RE.match("cat")
    balance = balance_from_counts({"cat": 7, "dog": 4, "bird": 1}, source="column:label")
    assert balance["imbalance_ratio"] == 7.0
    assert balance["counts"][0]["label"] == "cat"
    assert any("bird" in warning for warning in balance["warnings"])
    assert any("7.000" in warning for warning in balance["warnings"])
    even = balance_from_counts({"red": 3, "blue": 1}, source="column:class")
    assert even["imbalance_ratio"] == 3.0
    assert even["warnings"] == []


def test_pii_hints_skip_plain_labels():
    records = [
        {"label": "Golden Circle", "contact_email": "rowan@example.com", "phone": "555-0100", "person_name": "Rowan Kepler"},
        {"label": "Blue Square", "contact_email": "mina@example.com", "phone": "555-0101", "person_name": "Mina Quill"},
    ]
    hints = pii_hints("t.csv", ["label", "contact_email", "phone", "person_name"], records, label_column="label")
    kinds = {(hint["column"], hint["kind"]) for hint in hints}
    assert ("contact_email", "email") in kinds
    assert ("phone", "phone") in kinds
    assert ("person_name", "name") in kinds
    assert all(hint["column"] != "label" or hint["kind"] != "name" for hint in hints)


def test_spdx_identifier_wins_over_nearby_words():
    text = "MIT License\nSPDX-License-Identifier: CC0-1.0\nPermission is hereby granted, free of charge\n"
    assert license_id_from_text(text) == "CC0-1.0"
    assert license_id_from_text("Apache License\nVersion 2.0\n") == "Apache-2.0"
    assert license_id_from_text("no license here") is None
