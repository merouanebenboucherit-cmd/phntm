"""Copy-layer tests — what actually lands on the mounted stick."""

from __future__ import annotations

import hashlib
import stat

import pytest

from phntm.engine import copy as copy_mod
from phntm.models import BuildManifest, CatalogEntry, Persona
from phntm.presets import manifest_from_preset

ISO = CatalogEntry(
    id="miniiso",
    name="Mini ISO",
    kind="iso",
    categories=["boot"],
    size_gb=1.0,
    url="https://example.com/mini.iso",
    sha256=None,
)
TOOL = CatalogEntry(
    id="minitool",
    name="Mini Tool",
    kind="tool",
    categories=["utils"],
    size_gb=1.0,
    url="https://example.com/tool.zip",
    sha256=None,
)


def _manifest(**kw) -> BuildManifest:
    base = dict(
        persona=Persona.IT,
        tier=32,
        components=["miniiso", "minitool"],
        vault_gb=1.0,
        drop_gb=1.0,
        theme="default",
    )
    base.update(kw)
    return BuildManifest(**base)


def _catalog() -> dict[str, CatalogEntry]:
    return {"miniiso": ISO, "minitool": TOOL}


def _seed_cache(tmp_path) -> tuple:
    """Cache files for both components; wire their real sha256 into the catalog."""
    cache = tmp_path / "cache"
    for entry, data in ((ISO, b"iso-bytes"), (TOOL, b"tool-bytes")):
        f = cache / entry.id / copy_mod.filename_for(entry)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        entry.sha256 = hashlib.sha256(data).hexdigest()
    return cache, _catalog()


# ------------------------------------------------------------------ primitives


def test_cache_file_present_and_absent(tmp_path):
    cache, catalog = _seed_cache(tmp_path)
    assert copy_mod.cache_file(ISO, cache) == cache / "miniiso" / "mini.iso"
    assert copy_mod.cache_file(catalog["minitool"], cache).name == "tool.zip"
    missing = CatalogEntry(
        id="never", name="N", kind="iso", categories=["x"], size_gb=1.0, url="https://e/x.iso"
    )
    assert copy_mod.cache_file(missing, cache) is None


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

    # all-ventoy mounts → fall back to the last listed
    monkeypatch.setattr(
        "phntm.engine.metadata.mountpoints_for_device", lambda dev: [ventoy, efi]
    )
    assert copy_mod.mount_root_for("/dev/sdx9") == efi


def test_mount_root_for_none_when_never_mounted(monkeypatch):
    monkeypatch.setattr(
        "phntm.engine.metadata.mountpoints_for_device", lambda dev: []
    )
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


def test_full_layer_stages_everything(tmp_path):
    mount = tmp_path / "stick"
    cache, catalog = _seed_cache(tmp_path)
    manifest = _manifest(persistence={"enabled": True, "size_gb": 2.0})

    cmds: list[list[str]] = []
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(copy_mod, "has_tool", lambda name: True)
    monkeypatch.setattr(copy_mod, "_run", lambda cmd: cmds.append(cmd) or 0)
    try:
        rep = copy_mod.run_copy_layer(manifest, catalog, mount, cache=cache)
    finally:
        monkeypatch.undo()

    # all dirs exist
    for d in copy_mod.COPY_DIRS:
        assert (mount / d).is_dir()
    assert (mount / "ventoy").is_dir()

    # components: iso → ISOS/, non-iso → TOOLS/, sha256 verified
    assert (mount / "ISOS" / "mini.iso").read_bytes() == b"iso-bytes"
    assert (mount / "TOOLS" / "tool.zip").read_bytes() == b"tool-bytes"
    assert set(rep.copied) == {"miniiso", "minitool"}
    assert rep.ok

    # setup scripts executable + docs present
    for name in ("phntm-about.txt", "disk-info.sh", "router-creds.sh", "vault.txt"):
        assert (mount / "SETUP" / name).exists()
    mode = stat.S_IMODE((mount / "SETUP" / "disk-info.sh").stat().st_mode)
    assert mode & 0o111

    # persist image created via mkfs.ext4
    img = mount / "PERSIST" / "phntm-persist.img"
    assert img.exists() and img.stat().st_size == 2 * 1024**3
    assert any("mkfs.ext4" in c and str(img) in c for c in cmds)

    # vault formatted via cryptsetup with a random key file (0600)
    vimg = mount / "VAULT" / "phntm-vault.img"
    key = mount / "SETUP" / "vault-key.txt"
    assert vimg.exists() and key.exists()
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    assert any(c[0] == "cryptsetup" and "--key-file" in c and str(key) in c for c in cmds)

    # drop README
    assert (mount / "DROP" / "README.txt").exists()

    # theme + persistence plugin config
    cfg = (mount / "ventoy" / "ventoy.json").read_text()
    assert "phntm-persist.img" in cfg

    # honest report
    assert rep.setup_scripts == ["phntm-about.txt", "disk-info.sh", "router-creds.sh", "vault.txt"]
    assert not rep.missing and not rep.errors and not rep.skipped
    assert "components staged on stick: 2" in rep.summary()


# ------------------------------------------------------------------ failure modes


def test_missing_cache_reported_not_fatal(tmp_path):
    mount = tmp_path / "stick"
    rep = copy_mod.run_copy_layer(_manifest(), _catalog(), mount, cache=tmp_path / "nope")
    assert sorted(rep.missing) == ["miniiso", "minitool"]
    assert not rep.errors  # best-effort: skip, don't abort the build
    assert rep.ok
    assert not list((mount / "ISOS").glob("*"))


def test_sha256_mismatch_rejects_and_cleans(tmp_path):
    mount = tmp_path / "stick"
    cache, catalog = _seed_cache(tmp_path)
    catalog["miniiso"].sha256 = "0" * 64  # wrong on purpose
    rep = copy_mod.run_copy_layer(_manifest(), catalog, mount, cache=cache, parts=["isos"])
    assert len(rep.errors) == 1 and "sha256" in rep.errors[0]
    assert "miniiso" in rep.errors[0]
    assert not (mount / "ISOS" / "mini.iso").exists()  # rejected file cleaned up


def test_parts_filter_stages_only_requested(tmp_path):
    mount = tmp_path / "stick"
    cache, catalog = _seed_cache(tmp_path)
    rep = copy_mod.run_copy_layer(_manifest(), catalog, mount, cache=cache, parts=["setup"])
    assert (mount / "SETUP" / "phntm-about.txt").exists()
    assert not list((mount / "ISOS").glob("*"))  # cached but not staged
    assert not rep.copied
    assert not rep.missing


def test_vault_skipped_and_persist_skipped_without_tools(tmp_path):
    mount = tmp_path / "stick"
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(copy_mod, "has_tool", lambda name: False)
    try:
        rep = copy_mod.run_copy_layer(
            _manifest(persistence={"enabled": True, "size_gb": 2.0}, vault_gb=2.0),
            _catalog(),
            mount,
        )
    finally:
        monkeypatch.undo()
    assert not (mount / "VAULT" / "phntm-vault.img").exists()
    assert not (mount / "PERSIST" / "phntm-persist.img").exists()
    skipped = " ".join(rep.skipped)
    assert "vault" in skipped and "persist" in skipped


def test_drop_page_absent_when_zero(tmp_path):
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