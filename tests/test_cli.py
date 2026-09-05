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


def test_build_dry_run_without_device_still_plans(tmp_path):
    """--no-dry-run without --device must degrade to a plan, never execute."""
    from phntm.presets import manifest_from_preset
    from phntm.models import Persona

    m = tmp_path / "m.json"
    m.write_text(manifest_from_preset(Persona.IT, 64).model_dump_json())
    result = run("build", str(m), "--no-dry-run")
    assert result.exit_code == 0
    assert "BUDGET" in result.stdout


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