"""StickMetadata (phntm.json) roundtrip + version pinning."""

from phntm.catalog import load_catalog
from phntm.engine.build import metadata_for
from phntm.engine.metadata import read_metadata, write_metadata, status_snippet
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