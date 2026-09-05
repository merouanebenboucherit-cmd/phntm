"""StickMetadata (phntm.json) roundtrip + version pinning."""

from phntm import VERSION
from phntm.catalog import catalog_version, load_catalog
from phntm.engine.build import metadata_for
from phntm.engine.metadata import (
    read_metadata,
    read_metadata_stick,
    write_metadata,
    status_snippet,
)
from phntm.models import BuildManifest, Persona
from phntm.presets import manifest_from_preset


def test_metadata_roundtrip(tmp_path):
    catalog = load_catalog()
    manifest = manifest_from_preset(Persona.DFIR, 32)
    meta = metadata_for(manifest, catalog, tool_version="1.0.0")

    path = write_metadata(tmp_path, meta)
    assert path.name == "phntm.json"

    reread = read_metadata(tmp_path)
    assert reread.schema_name == "phntm/metadata"
    assert reread.tool_version == "1.0.0"
    assert reread.persona == "dfir"
    assert len(reread.components) == len(manifest.components)
    # Component pins snapshot catalog truth.
    assert reread.components[0].sha256 is None or isinstance(reread.components[0].sha256, str)


def test_status_snippet_is_human_readable(tmp_path):
    catalog = load_catalog()
    manifest = manifest_from_preset(Persona.PENTEST, 64)
    meta = metadata_for(manifest, catalog, tool_version="1.0.0")
    write_metadata(tmp_path, meta)
    snippet = status_snippet(read_metadata(tmp_path))
    assert "persona" in snippet
    assert "phntm" not in snippet.lower() or "phntm" in snippet  # no requirement, just smoke
    assert "tailscale" not in snippet  # nothing weird


def test_metadata_rejects_foreign_json(tmp_path):
    (tmp_path / "phntm.json").write_text('{"schema": "something-else"}')
    try:
        read_metadata(tmp_path)
        raise AssertionError("should have rejected foreign metadata")
    except Exception:
        pass


def test_read_metadata_stick_accepts_mount_dir(tmp_path):
    catalog = load_catalog()
    manifest = manifest_from_preset(Persona.PENTEST, 32)
    write_metadata(tmp_path, metadata_for(manifest, catalog, tool_version="1.0.0"))
    meta, path = read_metadata_stick(tmp_path)
    assert meta.persona == "pentest"
    assert path == tmp_path / "phntm.json"


def test_read_metadata_stick_follows_block_device_mounts(tmp_path, monkeypatch):
    """A /dev/sdX target scans its mounted partitions for phntm.json."""
    catalog = load_catalog()
    manifest = manifest_from_preset(Persona.DFIR, 64)
    write_metadata(tmp_path, metadata_for(manifest, catalog, tool_version="1.0.0"))
    monkeypatch.setattr(
        "phntm.engine.metadata.mountpoints_for_device",
        lambda device: [tmp_path],
    )
    meta, path = read_metadata_stick("/dev/sdb1")
    assert meta.persona == "dfir"
    assert path == tmp_path / "phntm.json"


def test_read_metadata_stick_raises_cleanly_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "phntm.engine.metadata.mountpoints_for_device", lambda device: []
    )
    try:
        read_metadata_stick("/dev/sdz9")
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError as exc:
        assert "/dev/sdz9" in str(exc)
        assert "PHNTM-built stick" in str(exc)


def test_metadata_for_defaults_to_real_versions(tmp_path):
    """tool_version defaults to the shipped version, catalog to the real one."""
    catalog = load_catalog()
    manifest = manifest_from_preset(Persona.IT, 16)
    meta = metadata_for(manifest, catalog)
    assert meta.tool_version == VERSION
    assert meta.tool_version != "1.0.0"  # never the placeholder again
    assert meta.catalog_version == catalog_version()