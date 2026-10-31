import json
import threading
import urllib.error
import urllib.request

import pytest

from datacardforge.server import assert_loopback, create_server
from tests.test_tabular import write_csv


@pytest.fixture
def api_server():
    httpd = create_server("127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def request(server, method, path, payload=None):
    port = server.server_address[1]
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            body = response.read().decode("utf-8")
            content_type = response.headers.get("Content-Type", "")
            parsed = json.loads(body) if "json" in content_type else body
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        return exc.code, parsed


def test_refuses_non_loopback():
    with pytest.raises(ValueError, match="loopback"):
        assert_loopback("0.0.0.0")


def test_scan_save_preview_and_export(api_server, tmp_path):
    folder = tmp_path / "served"
    write_csv(folder)
    status, page = request(api_server, "GET", "/")
    assert status == 200
    assert "DataCardForge" in page
    assert "/art/icon.png" in page
    assert "/art/cover.png" in page
    assert "http://" not in page
    assert "https://" not in page

    health, body = request(api_server, "GET", "/api/health")
    assert health == 200
    assert body["offline"] is True

    status, scanned = request(api_server, "POST", "/api/scan", {"path": str(folder)})
    assert status == 200
    assert scanned["card"]["size"]["rows"] == 12
    assert "<svg" in scanned["html"]
    before = (folder / "datacard.json").read_text(encoding="utf-8")

    status, preview = request(
        api_server,
        "POST",
        "/api/preview",
        {"path": str(folder), "edits": {"description": "Draft only"}},
    )
    assert status == 200
    assert "Draft only" in preview["html"]
    assert (folder / "datacard.json").read_text(encoding="utf-8") == before

    status, saved = request(
        api_server,
        "POST",
        "/api/save",
        {
            "path": str(folder),
            "edits": {
                "description": "Saved from the API",
                "license": "CC0-1.0",
                "sources_user": ["Bench notebook"],
            },
        },
    )
    assert status == 200
    assert saved["card"]["overview"]["description"]["value"] == "Saved from the API"
    assert saved["card"]["license"]["value"] == "CC0-1.0"

    status, exported = request(
        api_server,
        "GET",
        f"/api/export?path={folder}&format=md",
    )
    assert status == 200
    assert "Saved from the API" in exported

    with (folder / "measurements.csv").open("a", encoding="utf-8") as handle:
        handle.write("s11,20,cat,new@example.com,555-0111,New Person,extra\n")
    status, rescanned = request(api_server, "POST", "/api/scan", {"path": str(folder)})
    assert status == 200
    assert rescanned["card"]["size"]["rows"] == 13
    assert rescanned["card"]["overview"]["description"]["value"] == "Saved from the API"
    assert rescanned["card"]["sources"]["user"][0]["text"] == "Bench notebook"

    missing, error = request(api_server, "POST", "/api/scan", {"path": str(tmp_path / "nope")})
    assert missing == 400
    assert "does not exist" in error["error"]


def test_meta_lists_spdx_choices(api_server):
    status, meta = request(api_server, "GET", "/api/meta")
    assert status == 200
    assert "MIT" in meta["spdx"]
    assert meta["art"]["icon"] == "/art/icon.png"
    assert meta["art"]["cover"] == "/art/cover.png"
    assert meta["port"] == 8767
