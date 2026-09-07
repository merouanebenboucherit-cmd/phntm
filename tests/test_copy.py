"""Copy layer tests — real catalog components staged into a tmp mount."""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

import pytest

from phntm.catalog import load_catalog
from phntm.engine import copy as copy_mod
from phntm.engine.fetch import filename_for
from phntm.models import BuildManifest, Persona

# Real components from the shipped catalog: one ISO, one portable tool.
# The copy layer only touches bytes + sha256, so seeded dummy content is fine;
# keeping real ids/URLs means the test stays honest if the catalog changes.
ISO_ID = "kali-linux"
TOOL_ID = "nmap-portable"


def _catalog() -> dict:
    """Fresh copies per call — tests pin their own sha256 without cross-talk."""
    cat = load_catalog()
    return {cid: cat[cid].model_copy() for cid in (ISO_ID, TOOL_ID)}


def _manifest(**kw) -> BuildManifest:
    base = dict(
        persona=Persona.IT,
        tier=32,
        components=[ISO_ID, TOOL_ID],
        vault_gb=1.0,
        drop_gb=1.0,
        theme="default",
    )
    base.update(kw)
    return BuildManifest(**base)


def _data(cid: str) -> bytes:
    return f"{cid}-sample-bytes".encode()


def _seed_cache(tmp_path, catalog) -> Path:
    """Stage cache files for both components, sha256 matching their bytes."""
    cache = tmp_path / "cache"
    for cid in (ISO_ID, TOOL_ID):
        entry = catalog[cid]
        data = _data(cid)
        f = cache / cid / filename_for(entry)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        entry.sha256 = hashlib.sha256(data).hexdigest()
    return cache


# ------------------------------------------------------------------ primitives


def test_cache_file_present_and_absent(tmp_path):
    catalog = _catalog()
    cache = _seed_cache(tmp_path, catalog)
    assert copy_mod.cache_file(catalog[ISO_ID], cache) == cache / ISO_ID / filename_for(catalog[ISO_ID])
    assert copy_mod.cache_file(catalog[TOOL_ID], tmp_path / "elsewhere") is None


def test_mount_root_for_skips_ventoy_and_efi(monkeypatch, tmp_path):
    ventoy = tmp_path / "hpstick" / "Ventoy"  # VTOYEFI shows up as .../Ventoy on some setups
    efi = tmp_path / "hpstick" / "EFI"
    data = tmp_path / "hpstick" / "DATA"
    for d in (ventoy, efi, data):
        d.mkdir(parents=True)

    monkeypatch.setattr(
        "phntm.engine.metadata.mountpoints_for_device", lambda dev: [ventoy, efi, data]
    )
    assert copy_mod.mount_root_for("/dev/sdx9") == data

    monkeypatch.setattr(
        "phntm.engine.metadata.mountpoints_for_device", lambda dev: [ventoy, efi]
    )
    assert copy_mod.mount_root_for("/dev/sdx9") == efi  # all-Ventoy → last listed


def test_mount_root_for_none_when_never_mounted(monkeypatch):
    monkeypatch.setattr("phntm.engine.metadata.mountpoints_for_device", lambda dev: [])
    assert copy_mod.mount_root_for("/dev/sdx9", timeout=0.05, interval=0.01) is None


def test_mount_root_for_polls_until_a_mount_appears(monkeypatch, tmp_path):
    data = tmp_path / "DATA"
    data.mkdir()
    responses = iter([[], [], [data]])

    def flaky(dev):
        try:
            return next(responses)
        except StopIteration:
            return [data]

    monkeypatch.setattr("phntm.engine.metadata.mountpoints_for_device", flaky)
    assert copy_mod.mount_root_for("/dev/sdx9", timeout=2.0, interval=0.01) == data


# ------------------------------------------------------------------ full layer


def test_full_layer_stages_everything(tmp_path, monkeypatch):
    mount = tmp_path / "stick"
    catalog = _catalog()
    cache = _seed_cache(tmp_path, catalog)
    manifest = _manifest(persistence={"enabled": True, "size_gb": 2.0})

    cmds: list[list[str]] = []
    monkeypatch.setattr(copy_mod, "has_tool", lambda name: True)
    monkeypatch.setattr(copy_mod, "_run", lambda cmd: cmds.append(cmd) or 0)

    rep = copy_mod.run_copy_layer(manifest, catalog, mount, cache=cache)

    for d in copy_mod.COPY_DIRS:
        assert (mount / d).is_dir()
    assert (mount / "ventoy").is_dir()

    assert (mount / "ISOS" / filename_for(catalog[ISO_ID])).read_bytes() == _data(ISO_ID)
    assert (mount / "TOOLS" / filename_for(catalog[TOOL_ID])).read_bytes() == _data(TOOL_ID)
    assert set(rep.copied) == {ISO_ID, TOOL_ID}

    for name in ("phntm-about.txt", "disk-info.sh", "router-creds.sh", "vault.txt"):
        assert (mount / "SETUP" / name).exists()
    mode = stat.S_IMODE((mount / "SETUP" / "disk-info.sh").stat().st_mode)
    assert mode & 0o111

    img = mount / "PERSIST" / "phntm-persist.img"
    assert img.exists() and img.stat().st_size == 2 * 1024**3
    assert any("mkfs.ext4" in c and str(img) in c for c in cmds)

    vimg = mount / "VAULT" / "phntm-vault.img"
    key = mount / "SETUP" / "vault-key.txt"
    assert vimg.exists() and key.exists()
    assert stat.S_IMODE(key.stat().st_mode) == 0o600  # key not world-readable
    assert any(c[0] == "cryptsetup" and "--key-file" in c and str(key) in c for c in cmds)

    assert (mount / "DROP" / "README.txt").exists()
    assert "phntm-persist.img" in (mount / "ventoy" / "ventoy.json").read_text()

    assert rep.setup_scripts == ["phntm-about.txt", "disk-info.sh", "router-creds.sh", "vault.txt"]
    assert not rep.missing and not rep.errors and not rep.skipped
    assert "components staged on stick: 2" in rep.summary()


# ------------------------------------------------------------------ failure modes


def test_missing_cache_reported_not_fatal(tmp_path):
    mount = tmp_path / "stick"
    catalog = _catalog()
    rep = copy_mod.run_copy_layer(_manifest(), catalog, mount, cache=tmp_path / "nope")

    assert sorted(rep.missing) == [ISO_ID, TOOL_ID]
    assert not rep.errors  # skip silently in the report, don't abort the build
    assert not list((mount / "ISOS").glob("*"))


def test_sha256_mismatch_rejects_and_cleans(tmp_path):
    mount = tmp_path / "stick"
    catalog = _catalog()
    cache = _seed_cache(tmp_path, catalog)
    catalog[ISO_ID].sha256 = "0" * 64  # breaks the seeded checksum on purpose

    rep = copy_mod.run_copy_layer(_manifest(), catalog, mount, cache=cache, parts=["isos"])

    assert len(rep.errors) == 1 and "sha256" in rep.errors[0] and ISO_ID in rep.errors[0]
    assert not (mount / "ISOS" / filename_for(catalog[ISO_ID])).exists()  # rejected copy cleaned


def test_parts_filter_stages_only_requested(tmp_path):
    mount = tmp_path / "stick"
    catalog = _catalog()
    cache = _seed_cache(tmp_path, catalog)

    rep = copy_mod.run_copy_layer(_manifest(), catalog, mount, cache=cache, parts=["setup"])

    assert (mount / "SETUP" / "phntm-about.txt").exists()
    assert not list((mount / "ISOS").glob("*"))  # cached but not part of this run
    assert not rep.copied and not rep.missing


def test_vault_and_persist_skip_without_tools(tmp_path, monkeypatch):
    mount = tmp_path / "stick"
    monkeypatch.setattr(copy_mod, "has_tool", lambda name: False)

    manifest = _manifest(persistence={"enabled": True, "size_gb": 2.0}, vault_gb=2.0)
    rep = copy_mod.run_copy_layer(manifest, _catalog(), mount)

    assert not (mount / "VAULT" / "phntm-vault.img").exists()
    assert not (mount / "PERSIST" / "phntm-persist.img").exists()
    skipped = " ".join(rep.skipped)
    assert "vault" in skipped and "persist" in skipped


def test_drop_readme_absent_when_zero(tmp_path):
    mount = tmp_path / "stick"
    copy_mod.run_copy_layer(
        _manifest(drop_gb=0.0), _catalog(), mount, cache=tmp_path / "nope", parts=["drop"]
    )
    assert (mount / "DROP").is_dir()
    assert not (mount / "DROP" / "README.txt").exists()


def test_theme_written_with_persistence_backend(tmp_path):
    mount = tmp_path / "stick"
    rep = copy_mod.run_copy_layer(
        _manifest(persistence={"enabled": True, "size_gb": 1.0}),
        _catalog(),
        mount,
        parts=["theme"],
    )
    cfg = (mount / "ventoy" / "ventoy.json").read_text()
    assert '"/PERSIST/phntm-persist.img"' in cfg
    assert rep.ok