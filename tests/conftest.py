"""Block outbound sockets for the whole session. Loopback stays open for the local UI tests."""

from __future__ import annotations

import ipaddress
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_original_create = socket.create_connection
_original_getaddrinfo = socket.getaddrinfo


def _host(address):
    if isinstance(address, tuple) and address:
        return address[0]
    return None


def _is_ip(host) -> bool:
    try:
        ipaddress.ip_address(str(host).strip("[]"))
    except ValueError:
        return False
    return True


def _loopback(host) -> bool:
    if host is None:
        return False
    text = str(host).strip("[]")
    if text in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        return False


def _connect(self, address):
    if not isinstance(address, tuple):
        return _original_connect(self, address)
    if not _loopback(_host(address)):
        raise RuntimeError(f"outbound network blocked during tests: {address}")
    return _original_connect(self, address)


def _connect_ex(self, address):
    if isinstance(address, tuple) and not _loopback(_host(address)):
        raise RuntimeError(f"outbound network blocked during tests: {address}")
    return _original_connect_ex(self, address)


def _create_connection(address, *args, **kwargs):
    if not _loopback(_host(address)):
        raise RuntimeError(f"outbound network blocked during tests: {address}")
    return _original_create(address, *args, **kwargs)


def _getaddrinfo(host, *args, **kwargs):
    if host not in (None, "", "localhost", "127.0.0.1", "::1") and not _is_ip(host):
        raise RuntimeError(f"outbound network blocked during tests: DNS {host}")
    return _original_getaddrinfo(host, *args, **kwargs)


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.create_connection = _create_connection
socket.getaddrinfo = _getaddrinfo
