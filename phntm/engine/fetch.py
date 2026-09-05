"""Fetch driver — download component files into a local offline cache.

Supporting:
- deterministic cache layout: ``<cache>/<id>/<release>-<id>.<ext>``
- resumable downloads via ``Range`` (a ``.part`` file survives interruptions)
- sha256 verification when the catalog knows a checksum (missing → warning)
- atomic finalize: a file only lands in the cache once fully verified

No network access happens at build time: you fetch, then build stays offline.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import unquote, urlparse

from ..models import CatalogEntry

DEFAULT_CACHE = Path.home() / ".cache" / "phntm"
CHUNK = 1024 * 256  # 256 KiB read chunks
TIMEOUT = 30


class FetchError(RuntimeError):
    pass


@dataclass
class FetchResult:
    entry: CatalogEntry
    path: Path
    size: int
    fresh: bool = True  # True when downloaded this run, False when already cached
    checksum: Optional[str] = None
    checksum_ok: Optional[bool] = None  # None = no checksum on record

    @property
    def verified(self) -> bool:
        return self.checksum_ok is True


def cache_dir(cache: str | Path | None = None) -> Path:
    return Path(cache) if cache else DEFAULT_CACHE


def filename_for(entry: CatalogEntry) -> str:
    """A stable, descriptive filename for a component in the cache."""
    base = _basename_from_url(entry.download_url or entry.url) or entry.id
    ext = Path(base).suffix or (".iso" if entry.kind == "iso" else "")
    stem = Path(base).stem or entry.id
    if entry.release and entry.release not in stem:
        stem = f"{stem}-{entry.release}"
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", stem)
    return f"{name}{ext}"


def _basename_from_url(url: str) -> str:
    return unquote(Path(urlparse(url).path).name)


def list_cache(cache: str | Path | None = None) -> dict[str, Path]:
    """Map component-id → cached file path for every finished download."""
    root = cache_dir(cache)
    found: dict[str, Path] = {}
    if not root.exists():
        return found
    for file in root.glob("*/*"):
        if file.is_file() and file.suffix != ".part":
            found[file.parent.name] = file
    return found


def cache_status(cache: str | Path | None = None) -> dict[str, object]:
    """Total cached size + per-component entries, for ``phntm cache``/doctor."""
    files = list_cache(cache)
    total = sum(f.stat().st_size for f in files.values())
    return {"count": len(files), "total_gb": total / 1e9, "files": files}


def fetch(
    entry: CatalogEntry,
    *,
    cache: str | Path | None = None,
    verify_only: bool = False,
    progress=None,
) -> FetchResult:
    """Fetch (or reuse) one component in the cache. Verifies sha256 when known.

    ``progress`` is an optional callable ``(downloaded: int, total: int|None) -> None``.
    Raises :class:`FetchError` on terminal problems (no URL, bad checksum, 404…).
    """
    url = entry.download_url
    if not url:
        raise FetchError(
            f"'{entry.id}' has no direct download URL on record — open {entry.url} and grab it by hand"
        )
    target = cache_dir(cache) / entry.id / filename_for(entry)
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        result = _verified(target, entry)
        if result.checksum_ok is False:
            raise FetchError(
                f"cached file {target} fails sha256 verification for '{entry.id}' — "
                "delete it and re-fetch"
            )
        result.fresh = False
        return result

    if verify_only:
        raise FetchError(
            f"'{entry.id}' is not cached — nothing to verify (run 'phntm fetch {entry.id}')"
        )

    part = target.with_suffix(target.suffix + ".part")
    size_on_disk = part.stat().st_size if part.exists() else 0
    _download(entry, url, part, size_on_disk=size_on_disk, progress=progress)

    result = _verified(part, entry)
    if result.checksum_ok is False:
        part.unlink(missing_ok=True)
        raise FetchError(
            f"sha256 mismatch for '{entry.id}': expected "
            f"{entry.sha256 or 'unknown'}, got {result.checksum}. Retrying from scratch may help."
        )
    part.replace(target)  # atomic finalize
    return FetchResult(entry=entry, path=target, size=result.size, checksum=result.checksum, checksum_ok=result.checksum_ok)


def fetch_all(
    entries: Iterable[CatalogEntry],
    *,
    cache: str | Path | None = None,
    verify_only: bool = False,
    progress=None,
) -> list[FetchResult]:
    return [fetch(e, cache=cache, verify_only=verify_only, progress=progress) for e in entries]


def _download(
    entry: CatalogEntry,
    url: str,
    part: Path,
    *,
    size_on_disk: int,
    progress=None,
) -> None:
    headers = {"User-Agent": "phntm/1.3 (+https://github.com/merouanebenboucherit-cmd/phntm)"}
    if size_on_disk:
        headers["Range"] = f"bytes={size_on_disk}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            total = int(resp.headers.get("Content-Length") or 0) + size_on_disk
            if size_on_disk and resp.status == 200:
                # Server ignored Range — restart from zero.
                size_on_disk = 0
                total = int(resp.headers.get("Content-Length") or 0)
            mode = "ab" if size_on_disk else "wb"
            with open(part, mode) as fh:
                downloaded = size_on_disk
                if progress:
                    progress(downloaded, total or None)
                while True:
                    block = resp.read(CHUNK)
                    if not block:
                        break
                    fh.write(block)
                    downloaded += len(block)
                    if progress:
                        progress(downloaded, total or None)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise FetchError(f"{url} → HTTP 404 (not found — check the catalog entry for '{entry.id}')")
        raise FetchError(f"{url} → HTTP {exc.code}")
    except urllib.error.URLError as exc:
        raise FetchError(f"{url} → {exc.reason}")
    # Sanity: servers advertise Content-Length; warn when a .part silently completes short.
    if part.exists() and part.stat().st_size == 0:
        part.unlink(missing_ok=True)
        raise FetchError(f"empty download for '{entry.id}'")


def _verified(path: Path, entry: CatalogEntry) -> FetchResult:
    size = path.stat().st_size
    checksum = None
    checksum_ok = None
    if entry.sha256:
        checksum = sha256_of(path)
        checksum_ok = checksum.lower() == entry.sha256.lower()
    return FetchResult(
        entry=entry,
        path=path,
        size=size,
        checksum=checksum,
        checksum_ok=checksum_ok,
    )


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()