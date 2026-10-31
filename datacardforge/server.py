"""Local-only data card editor. Binds to 127.0.0.1:8767 and does not call out."""

from __future__ import annotations

import argparse
import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from datacardforge import __version__
from datacardforge.render import render_html, render_markdown
from datacardforge.scan_images import has_class_folders
from datacardforge.scan_tabular import has_tabular_files
from datacardforge.stats import SPDX_LICENSES
from datacardforge.store import (
    SCHEMA_VERSION,
    ensure_dataset_dir,
    output_paths,
    preview_card,
    read_card,
    save_edits,
    scan_and_merge,
)

HOST = "127.0.0.1"
PORT = 8767
MAX_BODY = 5_000_000

_SAMPLE_NAMES = {
    "colored-shapes-csv": "Colored shapes (CSV)",
    "colored-shapes-parquet": "Colored shapes (Parquet)",
    "colored-shapes-images": "Colored shapes (images)",
}

_EXPORTS = {
    "md": ("DATACARD.md", "text/markdown; charset=utf-8"),
    "markdown": ("DATACARD.md", "text/markdown; charset=utf-8"),
    "html": ("DATACARD.html", "text/html; charset=utf-8"),
    "json": ("datacard.json", "application/json; charset=utf-8"),
}


def repo_root() -> Path:
    here = Path(__file__).resolve().parent.parent
    if (here / "web" / "index.html").is_file():
        return here
    cwd = Path.cwd()
    if (cwd / "web" / "index.html").is_file():
        return cwd
    return here


def assert_loopback(host: str) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("DataCardForge only binds to loopback (127.0.0.1).")


def list_samples() -> list[dict]:
    base = repo_root() / "samples"
    if not base.is_dir():
        return []
    samples = []
    for path in sorted(base.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        kind = peek_kind(path)
        if kind == "empty":
            continue
        samples.append(
            {
                "id": path.name,
                "name": _SAMPLE_NAMES.get(path.name, path.name.replace("-", " ")),
                "kind": kind,
                "path": str(path.resolve()),
            }
        )
    return samples


def peek_kind(root: Path) -> str:
    tabular = has_tabular_files(root)
    images = has_class_folders(root)
    if tabular and images:
        return "mixed"
    if tabular:
        return "tabular"
    if images:
        return "images"
    return "empty"


def resolve_dataset(raw: str) -> Path:
    if raw is None or not str(raw).strip():
        raise ValueError("A dataset folder is required.")
    path = Path(str(raw).strip()).expanduser()
    if not path.is_absolute():
        path = repo_root() / path
    path = path.resolve()
    if path.is_file() and path.suffix.lower() in {".csv", ".parquet"}:
        path = path.parent
    return ensure_dataset_dir(path)


def browse(raw: str | None) -> dict:
    if raw and str(raw).strip():
        path = resolve_dataset(raw)
    else:
        path = repo_root()
    if not path.is_dir():
        raise ValueError(f"Not a folder: {path}")
    try:
        children = list(path.iterdir())
    except OSError as exc:
        raise ValueError(f"Cannot list {path}: {exc}") from exc
    directories = []
    for child in children:
        if not child.is_dir() or child.name.startswith("."):
            continue
        directories.append({"name": child.name, "path": str(child.resolve())})
    directories.sort(key=lambda item: item["name"].lower())
    parent = None if path.parent == path else str(path.parent)
    return {
        "path": str(path),
        "parent": parent,
        "directories": directories[:300],
    }


def card_payload(card: dict, root: Path) -> dict:
    return {
        "card": card,
        "html": render_html(card),
        "markdown": render_markdown(card),
        "outputs": output_paths(root),
    }


class Server(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "DataCardForge/1.0"

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def log_message(self, fmt: str, *args) -> None:
        print(f"[datacardforge] {self.address_string()} {fmt % args}")

    def _handle(self, method: str) -> None:
        try:
            parsed = urlparse(self.path)
            route = parsed.path if parsed.path == "/" else parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)
            if method == "GET" and route in {"/", "/index.html", "/styles.css", "/app.js", "/art/icon.png", "/art/cover.png", "/favicon.ico"}:
                self._send_static(route if route != "/favicon.ico" else "/favicon.ico")
                return
            if method == "GET" and route == "/api/health":
                self._send_json({"ok": True, "offline": True, "version": __version__, "port": PORT})
                return
            if method == "GET" and route == "/api/meta":
                self._send_json(self._meta())
                return
            if method == "GET" and route == "/api/samples":
                self._send_json({"samples": list_samples()})
                return
            if method == "GET" and route == "/api/browse":
                self._send_json(browse((query.get("path") or [""])[0]))
                return
            if method == "GET" and route == "/api/card":
                root = resolve_dataset((query.get("path") or [""])[0])
                card = read_card(root)
                if card is None:
                    self._send_json({"error": "No card yet. Scan the folder first."}, 404)
                    return
                self._send_json(card_payload(card, root))
                return
            if method == "GET" and route == "/api/export":
                self._export(query)
                return
            if method == "POST" and route == "/api/scan":
                body = self._body()
                root = resolve_dataset(body.get("path", ""))
                card = scan_and_merge(root, discard_edits=bool(body.get("discard_edits")))
                self._send_json(card_payload(card, root))
                return
            if method == "POST" and route == "/api/save":
                body = self._body()
                root = resolve_dataset(body.get("path", ""))
                card = save_edits(root, body.get("edits") or {})
                self._send_json(card_payload(card, root))
                return
            if method == "POST" and route == "/api/preview":
                body = self._body()
                root = resolve_dataset(body.get("path", ""))
                card = preview_card(root, body.get("edits") or None)
                self._send_json(card_payload(card, root))
                return
            if route.startswith("/api/"):
                self._send_json({"error": "Not found."}, 404)
                return
            self._send_text("Not found.", 404, "text/plain; charset=utf-8")
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001 - the local UI should see a message, not a stack
            traceback.print_exc()
            self._send_json({"error": str(exc)}, 500)

    def _meta(self) -> dict:
        return {
            "ok": True,
            "offline": True,
            "name": "DataCardForge",
            "version": __version__,
            "schema_version": SCHEMA_VERSION,
            "host": HOST,
            "port": PORT,
            "spdx": SPDX_LICENSES,
            "samples": list_samples(),
            "art": {"icon": "/art/icon.png", "cover": "/art/cover.png"},
        }

    def _export(self, query: dict) -> None:
        root = resolve_dataset((query.get("path") or [""])[0])
        fmt = ((query.get("format") or ["md"])[0] or "md").lower()
        if fmt not in _EXPORTS:
            raise ValueError("Format must be md, html, or json.")
        filename, content_type = _EXPORTS[fmt]
        path = root / filename
        if not path.is_file():
            self._send_json({"error": "Scan the dataset before exporting."}, 404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length < 0 or length > MAX_BODY:
            raise ValueError("Request body is too large.")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Expected JSON ({exc}).") from exc
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        return data

    def _send_static(self, route: str) -> None:
        path = _static_path(route)
        if path is None:
            self._send_text("Not found.", 404, "text/plain; charset=utf-8")
            return
        body = path.read_bytes()
        content_type = "image/png" if route == "/favicon.ico" else _content_type(path)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: int, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _static_path(route: str) -> Path | None:
    root = repo_root()
    mapping = {
        "/": root / "web" / "index.html",
        "/index.html": root / "web" / "index.html",
        "/styles.css": root / "web" / "styles.css",
        "/app.js": root / "web" / "app.js",
        "/art/icon.png": root / "art" / "icon.png",
        "/art/cover.png": root / "art" / "cover.png",
        "/favicon.ico": root / "art" / "icon.png",
    }
    path = mapping.get(route)
    if path is not None and path.is_file():
        return path
    return None


def _content_type(path: Path) -> str:
    return {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".png": "image/png",
    }.get(path.suffix.lower(), "application/octet-stream")


def create_server(host: str = HOST, port: int = PORT) -> Server:
    assert_loopback(host)
    return Server((host, port), Handler)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="datacardforge", description="Local data card editor")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)
    icon = repo_root() / "art" / "icon.png"
    cover = repo_root() / "art" / "cover.png"
    if not icon.is_file() or not cover.is_file():
        raise SystemExit("DataCardForge needs art/icon.png and art/cover.png.")
    try:
        httpd = create_server(args.host, args.port)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    except OSError as exc:
        raise SystemExit(f"Could not listen on {args.host}:{args.port} ({exc}).") from exc
    bound_port = httpd.server_address[1]
    print(f"DataCardForge {__version__}")
    print(f"icon  {icon}")
    print(f"cover {cover}")
    print(f"listening on {args.host}:{bound_port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
