"""CLI smoke tests — the commands users will actually type."""

import json

from typer.testing import CliRunner

from phntm.cli import app

runner = CliRunner()


def run(*args):
    return runner.invoke(app, list(args))


def test_version():
    result = run("--version")
    assert result.exit_code == 0
    assert "PHNTM" in result.stdout


def test_presets_lists_all_personas():
    result = run("presets")
    assert result.exit_code == 0
    for label in ("IT Tech", "Pentester", "DFIR Analyst", "Privacy User", "General Mix"):
        assert label in result.stdout


def test_manifest_new_writes_valid_file(tmp_path):
    out = tmp_path / "m.json"
    result = run("manifest", "new", "--persona", "it", "--tier", "16", "--out", str(out))
    assert result.exit_code == 0, result.stdout
    manifest = json.loads(out.read_text())
    assert manifest["persona"] == "it"
    assert manifest["tier"] == 16
    assert manifest["manifestVersion"] == 1


def test_manifest_validate_ok():
    import phntm.cli as cli

    m = cli.write_manifest(__import__("phntm.presets", fromlist=["manifest_from_preset"]).manifest_from_preset(
        __import__("phntm.models", fromlist=["Persona"]).Persona.PENTEST, 32
    ), "/tmp/phntm-test-manifest.json")
    result = run("manifest", "validate", "--file", str(m))
    assert result.exit_code == 0
    assert "valid" in result.stdout


def test_build_dry_run_plans_everything(tmp_path):
    from phntm.presets import manifest_from_preset
    from phntm.models import Persona

    m = tmp_path / "m.json"
    m.write_text(manifest_from_preset(Persona.DFIR, 32).model_dump_json())
    result = run("build", str(m), "--dry-run")
    assert result.exit_code == 0, result.stdout
    assert "BUDGET" in result.stdout
    assert "STEPS" in result.stdout
    assert "ventoy" in result.stdout.lower()
    assert "Nothing was modified" in result.stdout


def test_build_real_without_device_fails_cleanly(tmp_path):
    from phntm.presets import manifest_from_preset
    from phntm.models import Persona

    m = tmp_path / "m.json"
    m.write_text(manifest_from_preset(Persona.IT, 16).model_dump_json())
    result = run("build", str(m), "--no-dry-run", "--device", "/dev/sdZ99", "--yes")
    assert result.exit_code == 1
    assert "does not exist" in result.stdout or "✘" in result.stdout


def test_status_on_non_phntm_mount_fails():
    result = run("status", "/tmp")
    assert result.exit_code == 1
    assert "no phntm.json" in result.stdout


def test_components_search():
    result = run("components", "kali")
    assert result.exit_code == 0
    assert "kali-linux" in result.stdout

    result = run("components", "--persona", "dfir")
    assert result.exit_code == 0
    assert "winfe" in result.stdout
    assert "seclists" in result.stdout

    result = run("components", "zzznothing")
    assert result.exit_code == 0
    assert "no components" in result.stdout


def test_doctor_reports_environment():
    result = run("doctor")
    assert result.exit_code == 0
    for token in ("python", "ventoy", "catalog"):
        assert token in result.stdout.lower()


def test_manifest_show_prints_json():
    from phntm.presets import manifest_from_preset
    from phntm.models import Persona

    m = tmp_path = "/tmp/phntm-show-test.json"
    import json as _json

    _json.dump(manifest_from_preset(Persona.PRIVACY, 16).model_dump(), open(m, "w"))
    result = run("manifest", "show", "--file", m)
    assert result.exit_code == 0
    assert '"persona": "privacy"' in result.stdout


def test_build_no_dry_run_without_device_refuses(tmp_path):
    """--no-dry-run without --device must refuse loudly — never silently plan."""
    from phntm.presets import manifest_from_preset
    from phntm.models import Persona

    m = tmp_path / "m.json"
    m.write_text(manifest_from_preset(Persona.IT, 64).model_dump_json())
    result = run("build", str(m), "--no-dry-run")
    assert result.exit_code == 1
    assert "--device" in result.stdout
    assert "BUDGET" not in result.stdout


def test_update():
    result = run("update")
    assert result.exit_code == 0


def test_devices_command_exits_clean():
    """No stick required for this to work — it reports state."""
    result = run("devices")
    assert result.exit_code == 0
    assert "stick" in result.stdout.lower()


def test_help_command_prints_guide():
    result = run("help")
    assert result.exit_code == 0
    for token in ("phntm build", "DROP", "VAULT", "PERSIST"):
        assert token in result.stdout


def test_check_manifest_reports_freshness():
    result = run("check", "examples/dfir-spectre-32.json")
    assert result.exit_code == 0
    assert "vs catalog" in result.stdout


def test_build_auto_without_stick_fails_cleanly(tmp_path):
    from phntm.presets import manifest_from_preset
    from phntm.models import Persona

    m = tmp_path / "m.json"
    m.write_text(manifest_from_preset(Persona.IT, 16).model_dump_json())
    # On a machine with no stick this should explain, not crash.
    result = run("build", str(m), "--no-dry-run", "-d", "auto", "--yes")
    assert result.exit_code in (0, 1)


def test_update_is_honest_about_offline():
    result = run("update")
    assert result.exit_code == 0
    assert "local" in result.stdout.lower() or "bundled" in result.stdout.lower()

def test_fetch_unknown_component():
    result = run("fetch", "no-such-thing")
    assert result.exit_code == 1
    assert "unknown component" in result.stdout


def test_fetch_tty_progress_branch_cleans_up_on_missing(monkeypatch, tmp_path):
    # Drive the rich Progress (TTY) code path; empty cache → first entry fails,
    # which must unwind the progress bars cleanly and report the error.
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    result = run("fetch", "--verify", "--all", "--cache", str(tmp_path))
    assert result.exit_code == 1
    assert "not cached" in result.stdout


# ---------------------------------------------------------------- v1.5.0 additions
def test_status_clean_error_when_not_a_stick(tmp_path):
    result = run("status", str(tmp_path))
    assert result.exit_code == 1
    assert "PHNTM-built stick" in result.stdout
    assert "Traceback" not in result.stdout


def test_status_on_stick_dir(tmp_path):
    from phntm.engine.build import metadata_for
    from phntm.engine.metadata import write_metadata
    from phntm.catalog import load_catalog
    from phntm.presets import manifest_from_preset
    from phntm.models import Persona

    catalog = load_catalog()
    manifest = manifest_from_preset(Persona.PRIVACY, 16)
    write_metadata(tmp_path, metadata_for(manifest, catalog))
    result = run("status", str(tmp_path))
    assert result.exit_code == 0, result.stdout
    assert "PHNTM stick status" in result.stdout
    assert "metadata: " in result.stdout


def test_check_on_stick_dir(tmp_path):
    from phntm.engine.build import metadata_for
    from phntm.engine.metadata import write_metadata
    from phntm.catalog import load_catalog
    from phntm.presets import manifest_from_preset
    from phntm.models import Persona

    catalog = load_catalog()
    manifest = manifest_from_preset(Persona.PENTEST, 64)
    write_metadata(tmp_path, metadata_for(manifest, catalog))
    result = run("check", str(tmp_path))
    assert result.exit_code == 0, result.stdout
    assert "vs catalog" in result.stdout


def test_components_kind_and_direct_filters():
    iso = run("components", "--kind", "iso")
    assert iso.exit_code == 0
    assert "kali-linux" in iso.stdout
    # a non-iso tool must not leak into --kind iso results
    assert "nmap-portable" not in iso.stdout

    tool = run("components", "--kind", "tool")
    assert tool.exit_code == 0
    assert "nmap-portable" in tool.stdout
    assert "kali-linux" not in tool.stdout

    direct = run("components", "--kind", "iso", "--direct")
    assert direct.exit_code == 0
    # direct-only: every row has a download link; page-only ISOs are excluded
    assert "kali-linux" in direct.stdout
    assert "memtest86plus" not in direct.stdout  # page-only ISO (no direct link)


def test_fetch_continues_on_partial_failure(monkeypatch):
    """One failing component must not abort siblings; exit 1 with a tally."""
    from types import SimpleNamespace

    from phntm.catalog import load_catalog
    from phntm.engine.fetch import FetchError

    catalog = load_catalog()
    good = catalog["kali-linux"]  # has a direct download_url
    bad = catalog["memtest86plus"]  # page-only — the fetch module refuses
    calls: list[str] = []

    def fake_fetch(entry, cache=None, verify_only=False, progress=None):
        calls.append(entry.id)
        if entry.id == bad.id:
            raise FetchError("no direct download URL on record")
        return SimpleNamespace(
            entry=entry, fresh=False, checksum_ok=None, size=1024 * 1024
        )

    monkeypatch.setattr("phntm.engine.fetch.fetch", fake_fetch)
    result = run("fetch", good.id, bad.id)
    assert result.exit_code == 1
    assert calls == [good.id, bad.id]     # both were attempted, in order
    assert "1 of 2 failed" in result.stdout
    assert good.id in result.stdout       # the successful one was reported


def test_help_guide_covers_filters_and_tiers():
    result = run("help")
    assert result.exit_code == 0
    for token in ("--direct", "16/32/64/128", "OFFLINE ARSENAL", "sha256"):
        assert token in result.stdout
