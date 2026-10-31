import re
import socket
from pathlib import Path

import pytest

from datacardforge.server import HOST, PORT

ROOT = Path(__file__).resolve().parents[1]
URLS = re.compile(r"https?://[^\s\"')>]+")


def test_server_binds_loopback_on_8767():
    assert HOST == "127.0.0.1"
    assert PORT == 8767


def test_outbound_sockets_and_dns_are_blocked():
    with pytest.raises(RuntimeError, match="blocked"):
        socket.create_connection(("1.1.1.1", 80), timeout=1)
    with pytest.raises(RuntimeError, match="blocked"):
        socket.getaddrinfo("example.com", 80)
    probe = socket.socket()
    try:
        with pytest.raises(RuntimeError, match="blocked"):
            probe.connect(("8.8.8.8", 53))
    finally:
        probe.close()


def test_project_files_do_not_reference_remote_urls():
    paths = list((ROOT / "datacardforge").glob("*.py"))
    paths += list((ROOT / "web").glob("*"))
    paths += [
        ROOT / "README.md",
        ROOT / "launch-linux.sh",
        ROOT / "launch-mac.command",
        ROOT / "launch-windows.bat",
        ROOT / "samples" / "generate.py",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        assert "cdn." not in lowered
        assert "unpkg" not in lowered
        assert "jsdelivr" not in lowered
        assert "fonts.googleapis" not in lowered
        for match in URLS.findall(text):
            assert match.startswith("http://127.0.0.1") or match.startswith("http://localhost"), (
                path.name,
                match,
            )


def test_launchers_use_the_art_files():
    linux = (ROOT / "launch-linux.sh").read_text(encoding="utf-8")
    mac = (ROOT / "launch-mac.command").read_text(encoding="utf-8")
    windows = (ROOT / "launch-windows.bat").read_text(encoding="utf-8")
    assert linux.startswith("#!/usr/bin/env bash")
    assert mac.startswith("#!/bin/bash")
    for script in (linux, mac):
        assert "art/icon.png" in script
        assert "art/cover.png" in script
        assert "8767" in script
        assert "requirements.txt" in script
    assert "art\\icon.png" in windows
    assert "art\\cover.png" in windows
    assert "8767" in windows
    assert (ROOT / "art" / "icon.png").is_file()
    assert (ROOT / "art" / "cover.png").is_file()


def test_app_code_does_not_open_remote_clients():
    text = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "datacardforge").glob("*.py"))
    assert "urlopen" not in text
    assert "requests" not in text
    assert "httpx" not in text
