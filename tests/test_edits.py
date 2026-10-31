from tests.test_tabular import write_csv

from datacardforge.store import read_card, save_edits, scan_and_merge


def _seed(folder):
    write_csv(folder)
    (folder / "README.md").write_text(
        "# Shapes\n\nToy measurements for the editor test.\n",
        encoding="utf-8",
    )
    (folder / "LICENSE").write_text(
        "MIT License\n\nPermission is hereby granted, free of charge, to test locally.\n",
        encoding="utf-8",
    )
    (folder / "source.txt").write_text("Synthetic rows only.\n", encoding="utf-8")


def test_three_outputs_and_user_edits_survive_rescan(tmp_path):
    folder = tmp_path / "shapes"
    _seed(folder)
    first = scan_and_merge(folder)
    assert first["license"]["auto_value"] == "MIT"
    assert first["license"]["detected_from"] == "LICENSE"
    assert any(item["kind"] == "source" for item in first["sources"]["auto"])
    assert "Toy measurements" in first["overview"]["description"]["value"]
    second = scan_and_merge(folder)
    assert second["size"]["bytes"] == first["size"]["bytes"]
    assert second["size"]["rows"] == 12

    saved = save_edits(
        folder,
        {
            "name": "Workshop shapes",
            "description": "Hand-written purpose",
            "license": "CC0-1.0",
            "intended_use": "Toy training demo",
            "out_of_scope_use": "Not for decisions about people",
            "known_gaps_user": "Dropped the night batch.",
            "sources_user": ["Notebook 4, synthetic only"],
        },
    )
    assert saved["overview"]["name"]["source"] == "user"
    assert saved["license"]["source"] == "user"
    for name in ("DATACARD.md", "DATACARD.html", "datacard.json"):
        text = (folder / name).read_text(encoding="utf-8")
        assert "Hand-written purpose" in text
    html = (folder / "DATACARD.html").read_text(encoding="utf-8")
    assert "<svg" in html
    assert "http://" not in html
    assert "https://" not in html
    assert "cdn" not in html.lower()
    assert 'id="overview"' in html
    markdown = (folder / "DATACARD.md").read_text(encoding="utf-8")
    for heading in (
        "Overview",
        "Size",
        "Schema",
        "Class balance",
        "Missingness",
        "Duplicates",
        "Sources",
        "License",
        "Known gaps",
        "Intended use",
        "Out-of-scope use",
        "PII hints",
    ):
        assert heading in markdown

    readme = folder / "README.md"
    readme.write_text("# Shapes\n\nRewritten readme after the edit.\n", encoding="utf-8")
    with (folder / "measurements.csv").open("a", encoding="utf-8") as handle:
        handle.write("s11,20,cat,new@example.com,555-0111,New Person,extra\n")

    again = scan_and_merge(folder)
    assert again["overview"]["name"]["value"] == "Workshop shapes"
    assert again["overview"]["description"]["value"] == "Hand-written purpose"
    assert again["overview"]["description"]["source"] == "user"
    assert "Rewritten readme" in again["overview"]["description"]["auto_value"]
    assert again["license"]["value"] == "CC0-1.0"
    assert again["license"]["source"] == "user"
    assert again["license"]["auto_value"] == "MIT"
    assert again["intended_use"]["value"] == "Toy training demo"
    assert again["out_of_scope_use"]["value"] == "Not for decisions about people"
    assert again["known_gaps"]["user"] == "Dropped the night batch."
    assert again["sources"]["user"] == [{"text": "Notebook 4, synthetic only"}]
    assert again["size"]["rows"] == 13
    assert again["class_balance"]["counts"][0]["count"] == 8
    rendered = (folder / "DATACARD.html").read_text(encoding="utf-8")
    assert "Hand-written purpose" in rendered
    assert "CC0-1.0" in rendered
    stored = read_card(folder)
    assert stored["overview"]["description"]["value"] == "Hand-written purpose"


def test_revert_to_scanned_value_becomes_auto_again(tmp_path):
    folder = tmp_path / "revert"
    _seed(folder)
    scan_and_merge(folder)
    save_edits(folder, {"description": "Temporary note"})
    card = read_card(folder)
    restored = save_edits(folder, {"description": card["overview"]["description"]["auto_value"]})
    assert restored["overview"]["description"]["source"] == "auto"


def test_discard_edits_rebuilds_from_the_scan(tmp_path):
    folder = tmp_path / "discard"
    _seed(folder)
    scan_and_merge(folder)
    save_edits(folder, {"description": "Please drop this"})
    fresh = scan_and_merge(folder, discard_edits=True)
    assert fresh["overview"]["description"]["source"] == "auto"
    assert fresh["overview"]["description"]["value"] != "Please drop this"
    assert "Toy measurements" in fresh["overview"]["description"]["value"]
