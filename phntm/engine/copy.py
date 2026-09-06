"""Copy layer — turn a mounted Ventoy stick into a real PHNTM ghost stick.

Everything here runs against a *mount root* (a directory), never a raw device:
after Ventoy is flashed and the data partition is mounted, the build stages

    ISOS/     live ISO files (sha256-verified against the catalog)
    TOOLS/    portable tools from the offline cache
    SETUP/    PHNTM helper scripts + honest per-stick documentation
    DROP/     plaintext scratch space (reserved as configured)
    VAULT/    LUKS-encrypted file container (cryptsetup, best-effort)
    PERSIST/  per-OS persistence image (Ventoy persistence plugin backends)
    ventoy/   ventoy.json theme + persistence plugin

All square operations work unprivileged (no sudo): file copies, sparse images,
``mkfs.ext4`` and ``cryptsetup luksFormat`` on file containers. Mounting the
result is up to Ventoy at boot time.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from ..models import BuildManifest, CatalogEntry
from .fetch import cache_dir, filename_for

COPY_DIRS = ("ISOS", "TOOLS", "SETUP", "DROP", "PERSIST", "VAULT")

ALL_PARTS = ("isos", "tools", "setup", "drop", "persist", "vault", "theme")


@dataclass
class BuildReport:
    """What actually landed on the stick — shown after a real build."""

    mount_root: Optional[Path] = None
    copied: dict[str, Path] = field(default_factory=dict)  # component id → dest
    missing: list[str] = field(default_factory=list)       # cached file absent
    skipped: list[str] = field(default_factory=list)       # best-effort skipped
    errors: list[str] = field(default_factory=list)
    setup_scripts: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def snapshot(self) -> dict:
        return {
            "mount": str(self.mount_root) if self.mount_root else None,
            "copied": sorted(self.copied),
            "missing": self.missing,
            "skipped": self.skipped,
            "errors": self.errors,
            "setup_scripts": self.setup_scripts,
        }

    def summary(self) -> str:
        """Human-readable tally for the post-build screen (plain text)."""
        out: list[str] = []
        if self.copied:
            out.append(f"  components staged on stick: {len(self.copied)}")
            for cid in sorted(self.copied):
                out.append(f"    • {cid} → {self.copied[cid]}")
        if self.missing:
            out.append(
                "  not cached / skipped: " + ", ".join(self.missing)
                + "  (run: phntm fetch <id>)"
            )
        if self.skipped:
            out.append("  best-effort skipped: " + ", ".join(self.skipped))
        if self.setup_scripts:
            out.append("  SETUP/ scripts: " + ", ".join(self.setup_scripts))
        if self.errors:
            out.append("  ERRORS:")
            out.extend(f"    ✘ {e}" for e in self.errors)
        if not out:
            out.append("  nothing staged.")
        return "\n".join(out)


# ------------------------------------------------------------------ primitives


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_file(entry: CatalogEntry, cache: str | Path | None = None) -> Optional[Path]:
    """Resolve the cached file for an entry, if it exists."""
    f = cache_dir(cache) / entry.id / filename_for(entry)
    return f if f.is_file() else None


def has_tool(name: str) -> bool:
    return shutil.which(name) is not None


def _run(cmd: list[str]) -> int:
    """Run an external helper (mkfs.ext4, cryptsetup…). Test-friendly seam."""
    return subprocess.run(cmd, check=False, capture_output=True).returncode


def mount_root_for(device: str | Path, timeout: float = 30.0, interval: float = 1.0) -> Optional[Path]:
    """Find the mounted data partition of ``device`` (polls; skips EFI/Ventoy).

    Returns the first non-EFI mount, else the last mount listed, else None.
    """
    from .metadata import mountpoints_for_device

    deadline = time.monotonic() + timeout
    mounts: list[Path] = []
    while time.monotonic() < deadline:
        mounts = mountpoints_for_device(device)
        if mounts:
            break
        time.sleep(interval)
    if not mounts:
        return None
    for m in mounts:
        low = str(m).lower()
        if "ventoy" not in low and "efi" not in low:
            return m
    return mounts[-1]


# ------------------------------------------------------------------ parts


def _stage_components(
    manifest: BuildManifest,
    catalog: dict[str, CatalogEntry],
    mount: Path,
    cache: str | Path | None,
    verify: bool,
    rep: BuildReport,
) -> None:
    for cid in manifest.components:
        entry = catalog[cid]
        src = cache_file(entry, cache)
        if src is None:
            rep.missing.append(cid)
            continue
        folder = "ISOS" if entry.kind == "iso" else "TOOLS"
        dest = mount / folder / filename_for(entry)
        try:
            _copy_verified(src, dest, entry.sha256 if verify else None)
            rep.copied[cid] = dest
        except (OSError, ValueError) as exc:
            rep.errors.append(f"{cid}: {exc}")


def _copy_verified(src: Path, dest: Path, expect_sha: Optional[str]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    if expect_sha:
        got = sha256(dest)
        if got.lower() != expect_sha.lower():
            dest.unlink(missing_ok=True)
            raise ValueError(f"sha256 mismatch ({got[:12]}… != {expect_sha[:12]}…) — rejected")


def _stage_setup(mount: Path, manifest: BuildManifest, rep: BuildReport) -> None:
    setup = mount / "SETUP"
    setup.mkdir(parents=True, exist_ok=True)
    scripts = {
        "phntm-about.txt": _about_text(manifest),
        "disk-info.sh": _DISK_INFO_SH,
        "router-creds.sh": _ROUTER_CREDS_SH,
        "vault.txt": _vault_guide(manifest),
    }
    for name, text in scripts.items():
        path = setup / name
        path.write_text(text)
        if path.suffix == ".sh":
            path.chmod(path.stat().st_mode | 0o111)
        rep.setup_scripts.append(name)


_DISK_INFO_SH = """#!/bin/sh
# PHNTM — quick hardware inventory before you touch anything.
set -e
echo "== block devices =="
lsblk -o NAME,SIZE,TRAN,MODEL,MOUNTPOINTS
echo "== memory/CPU =="
grep MemTotal /proc/meminfo || true
grep 'model name' /proc/cpuinfo | head -1 || true
echo "== network =="
ip -brief addr || ifconfig 2>/dev/null || true
"""

_ROUTER_CREDS_SH = """#!/bin/sh
# PHNTM — common router/webapp default creds, rescue-style (read /routersec/…).
set -e
echo "== common vendor defaults (verify against the device!) =="
cat <<'EOF'
router       admin/admin, admin/password, admin/1234
ubiquiti     ubnt/ubnt
tp-link      admin/admin
draytek      admin/admin
synology     admin/ (blank)
camera Hik   admin/12345
EOF
"""


def _about_text(manifest: BuildManifest) -> str:
    parts = [
        f"PHNTM ghost stick — {manifest.name}",
        f"persona: {manifest.persona.value} · tier: {manifest.tier}GB · "
        f"built with phntm {manifest.created_at[:10]}",
        "",
        "ISOS/    live boot images (Ventoy boots them)",
        "TOOLS/   portable tools",
        "SETUP/   helpers + docs (this folder)",
        "DROP/    plaintext scratch",
        "VAULT/   encrypted container (see vault.txt)",
        "PERSIST/ per-OS persistence images",
    ]
    return "\n".join(parts) + "\n"


def _vault_guide(manifest: BuildManifest) -> str:
    return (
        "VAULT — encrypted container (LUKS)\n"
        "----------------------------------\n"
        f"created for manifest '{manifest.name}' (v{manifest.vault_gb:.1f} GB).\n\n"
        "Open it on the stick:\n"
        "  cryptsetup luksOpen VAULT/phntm-vault.img vault\n"
        "  mkfs.ext4 /dev/mapper/vault        # first time only\n"
        "  mount /dev/mapper/vault /mnt/vault\n\n"
        "The LUKS key sits in SETUP/vault-key.txt — ROTATE IT or copy data "
        "out and rebuild. A stick carrying its own key protects against "
        "reviewers, not thieves.\n"
    )


def _stage_drop(mount: Path, manifest: BuildManifest, rep: BuildReport) -> None:
    drop = mount / "DROP"
    drop.mkdir(parents=True, exist_ok=True)
    if manifest.drop_gb > 0:
        (drop / "README.txt").write_text(
            f"Plaintext scratch space. {manifest.drop_gb:.1f} GB of this stick is "
            "reserved for you — fill it, wipe it, no one's watching.\n"
        )


def _stage_persist(mount: Path, manifest: BuildManifest, rep: BuildReport) -> None:
    if not manifest.persistence.enabled:
        return
    img = mount / "PERSIST" / "phntm-persist.img"
    if has_tool("mkfs.ext4"):
        gb = manifest.persistence.size_gb or 1.0
        img.parent.mkdir(parents=True, exist_ok=True)
        with open(img, "wb") as fh:
            fh.truncate(int(gb * 1024 * 1024 * 1024))
        rc = _run(["mkfs.ext4", "-q", "-L", "PERSIST", str(img)])
        if rc != 0:
            rep.errors.append(f"persist: mkfs.ext4 failed (exit {rc}) — image left empty")
    else:
        rep.skipped.append("persist image (mkfs.ext4 not installed)")


def _stage_vault(mount: Path, manifest: BuildManifest, rep: BuildReport) -> None:
    if manifest.vault_gb <= 0:
        return
    img = mount / "VAULT" / "phntm-vault.img"
    if not has_tool("cryptsetup"):
        rep.skipped.append("vault container (cryptsetup not installed)")
        return
    img.parent.mkdir(parents=True, exist_ok=True)
    key = mount / "SETUP" / "vault-key.txt"
    with open(img, "wb") as fh:
        fh.truncate(int(manifest.vault_gb * 1024 * 1024 * 1024))
    if not key.exists():
        key.write_text(os.urandom(32).hex() + "\n")  # honest: see vault.txt
        key.chmod(0o600)
    rc = _run(["cryptsetup", "-q", "luksFormat", "--batch-mode", "--key-file", str(key), str(img)])
    if rc != 0:
        rep.errors.append(f"vault: cryptsetup luksFormat failed (exit {rc})")


def _stage_theme(mount: Path, manifest: BuildManifest, rep: BuildReport) -> None:
    from .ventoy import ventoy_json

    vdir = mount / "ventoy"
    vdir.mkdir(parents=True, exist_ok=True)
    cfg = ventoy_json(theme=manifest.theme, persistence_label="PERSIST")
    (vdir / "ventoy.json").write_text(json.dumps(cfg, indent=2) + "\n")


# ------------------------------------------------------------------ entry point


def run_copy_layer(
    manifest: BuildManifest,
    catalog: dict[str, CatalogEntry],
    mount_root: str | Path,
    *,
    cache: str | Path | None = None,
    verify: bool = True,
    parts: Iterable[str] = ALL_PARTS,
    report: Optional[BuildReport] = None,
) -> BuildReport:
    """Execute the given copy-layer parts into ``mount_root`` in place."""
    mount = Path(mount_root)
    rep = report if report is not None else BuildReport(mount_root=mount)
    rep.mount_root = mount
    wanted = set(parts)
    for d in COPY_DIRS:
        (mount / d).mkdir(parents=True, exist_ok=True)
    if "isos" in wanted or "tools" in wanted:
        _stage_components(manifest, catalog, mount, cache, verify, rep)
    if "setup" in wanted:
        _stage_setup(mount, manifest, rep)
    if "drop" in wanted:
        _stage_drop(mount, manifest, rep)
    if "persist" in wanted:
        _stage_persist(mount, manifest, rep)
    if "vault" in wanted:
        _stage_vault(mount, manifest, rep)
    if "theme" in wanted:
        _stage_theme(mount, manifest, rep)
    return rep