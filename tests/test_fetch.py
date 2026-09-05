"""Fetch driver tests against a local HTTP server with Range support."""

from __future__ import annotations

import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from phntm.engine.fetch import (
    FetchError,
    cache_status,
    fetch,
    fetch_all,
    filename_for,
    list_cache,
)
from phntm.models import CatalogEntry

PAYLOAD = bytes(range(256)) * 4096  # 1 MiB deterministic blob


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _Handler(BaseHTTPRequestHandler):
    ignore_range = False  # toggle per test: True → server answers 200 to Range
    requests: list[tuple[str, str]] = []  # (path, range?) log

    def log_message(self, *args):  # quiet
        pass

    def do_GET(self):  # noqa: N802
        _Handler.requests.append((self.path, self.headers.get("Range", "")))
        if self.path == "/blob.bin":
            body = PAYLOAD
        elif self.path == "/other.bin":
            body = PAYLOAD[:100]
        elif self.path == "/empty.bin":
            body = b""
        else:
            self.send_error(404)
            return
        if self.headers.get("Range") and not self.ignore_range:
            m = self.headers.get("Range")
            start = int(m.split("=")[1].split("-")[0])
            if start >= len(body):
                self.send_response(416)
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(body)-1}/{len(body)}")
            self.send_header("Content-Length", str(len(body) - start))
            self.end_headers()
            self.wfile.write(body[start:])
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    _Handler.requests.clear()
    _Handler.ignore_range = False
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    thread.join(timeout=5)


def _entry(server: str, *, digest: str | None = None, kind: str = "iso") -> CatalogEntry:
    return CatalogEntry(
        id="blob-linux" if kind == "iso" else "blob-tool",
        name="Blob Linux",
        kind=kind,
        categories=["test"],
        size_gb=0.01,
        url=server,
        download_url=f"{server}/blob.bin",
        sha256=digest or _sha256(PAYLOAD),
    )


def test_fetch_happy_path(tmp_path: Path, server: str):
    e = _entry(server)
    r = fetch(e, cache=tmp_path)
    assert r.fresh is True
    assert r.checksum_ok is True
    assert r.size == len(PAYLOAD)
    assert r.path == tmp_path / "blob-linux" / filename_for(e)
    assert r.path.read_bytes() == PAYLOAD
    assert r.path.name == "blob.bin"
    assert ("/blob.bin", "") in _Handler.requests  # no Range on first fetch


def test_fetch_reuses_cached_file(tmp_path: Path, server: str):
    e = _entry(server)
    first = fetch(e, cache=tmp_path)
    second = fetch(e, cache=tmp_path)
    assert second.fresh is False
    assert second.path == first.path
    assert second.checksum_ok is True
    assert len([r for r in _Handler.requests if r[0] == "/blob.bin"]) == 1


def test_fetch_resumes_from_partial_part(tmp_path: Path, server: str):
    e = _entry(server)
    part_dir = tmp_path / "blob-linux"
    part_dir.mkdir(parents=True)
    seed = PAYLOAD[:30000]
    (part_dir / "blob.bin.part").write_bytes(seed)
    r = fetch(e, cache=tmp_path)
    assert r.path.read_bytes() == PAYLOAD
    # server must have seen a Range request for the remaining bytes
    assert any(rng.startswith(f"bytes={len(seed)}-") for _, rng in _Handler.requests)


def test_fetch_restarts_when_server_ignores_range(tmp_path: Path, server: str):
    _Handler.ignore_range = True
    e = _entry(server)
    part_dir = tmp_path / "blob-linux"
    part_dir.mkdir(parents=True)
    (part_dir / "blob.bin.part").write_bytes(PAYLOAD[:30000])
    r = fetch(e, cache=tmp_path)
    assert r.path.read_bytes() == PAYLOAD
    assert r.checksum_ok is True


def test_fetch_rejects_checksum_mismatch(tmp_path: Path, server: str):
    e = _entry(server, digest=hashlib.sha256(b"wrong").hexdigest())
    with pytest.raises(FetchError, match="sha256 mismatch"):
        fetch(e, cache=tmp_path)
    # nothing half-written may remain, neither .part nor final file
    assert not (tmp_path / "blob-linux" / "blob.bin").exists()
    assert not list((tmp_path / "blob-linux").glob("*.part"))


def test_fetch_404(tmp_path: Path, server: str):
    e = _entry(server).model_copy(update={"download_url": f"{server}/nope.bin"})
    with pytest.raises(FetchError, match="404"):
        fetch(e, cache=tmp_path)


def test_fetch_empty_download(tmp_path: Path, server: str):
    e = _entry(server).model_copy(update={"download_url": f"{server}/empty.bin"})
    with pytest.raises(FetchError, match="empty"):
        fetch(e, cache=tmp_path)


def test_fetch_requires_download_url(tmp_path: Path):
    e = CatalogEntry(
        id="page-only", name="Page Only", kind="iso", categories=["test"],
        size_gb=1.0, url="https://example.org/download",
    )
    with pytest.raises(FetchError, match="no direct download URL"):
        fetch(e, cache=tmp_path)


def test_verify_only(tmp_path: Path, server: str):
    e = _entry(server)
    with pytest.raises(FetchError, match="not cached"):
        fetch(e, cache=tmp_path, verify_only=True)
    fetch(e, cache=tmp_path)
    r = fetch(e, cache=tmp_path, verify_only=True)
    assert r.fresh is False
    assert r.checksum_ok is True


def test_cache_status_and_list(tmp_path: Path, server: str):
    e = _entry(server)
    fetch(e, cache=tmp_path)
    st = cache_status(tmp_path)
    assert st["count"] == 1
    assert st["total_gb"] == pytest.approx(len(PAYLOAD) / 1e9, rel=1e-3)
    files = list_cache(tmp_path)
    assert files == {"blob-linux": st["files"]["blob-linux"]}


def test_fetch_all_orders_and_reports(tmp_path: Path, server: str):
    e1 = _entry(server, kind="iso")
    e2 = _entry(server, kind="tool").model_copy(update={"id": "blob-tool"})
    results = fetch_all([e1, e2], cache=tmp_path)
    assert [r.entry.id for r in results] == ["blob-linux", "blob-tool"]
    assert all(r.checksum_ok for r in results)
    assert (st := cache_status(tmp_path))
    assert st["count"] == 2


def test_filename_for_uses_release():
    e = CatalogEntry(
        id="kali-linux", name="Kali", kind="iso", categories=["pentest"],
        size_gb=4.0, url="https://example.org", release="2024.4",
        download_url="https://example.org/kali-linux-2024.4-live-amd64.iso",
    )
    assert filename_for(e) == "kali-linux-2024.4-live-amd64.iso"


def test_filename_for_falls_back_to_id():
    e = CatalogEntry(
        id="no-base", name="No Base", kind="iso", categories=["test"],
        size_gb=1.0, url="https://example.org", download_url="https://example.org",
    )
    assert filename_for(e).startswith("no-base")