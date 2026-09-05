"""PHNTM CLI — build legendary USB sticks. Local-first, zero telemetry."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List, Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.table import Table

from . import VERSION
from .catalog import load_catalog, catalog_version, resolve_components
from .engine.build import compose_steps, dry_run, run_build, BuildError
from .engine.metadata import read_metadata, status_snippet, write_metadata
from .models import BuildManifest, Persona
from .presets import (
    available_personas,
    load_presets,
    manifest_from_preset,
    resolve_preset,
    tiers_for,
)
from .sizer import compute_budget, format_budget

app = typer.Typer(
    name="phntm",
    help="PHNTM — build legendary USB sticks. Local-first, open source, zero telemetry.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _version_cb(value: bool) -> None:
    if value:
        rprint(f"PHNTM [bold]v{VERSION}[/bold] — ghost protocol ready 👻")
        raise typer.Exit()


@app.callback()
def main(version: bool = typer.Option(False, "--version", callback=_version_cb, is_eager=True)) -> None:
    """PHNTM command line interface."""


# --------------------------------------------------------------------------- tui
@app.command("tui")
def cmd_tui() -> None:
    """Launch the guided build wizard (Textual TUI)."""
    try:
        from .tui import run_wizard
    except ImportError:
        rprint("[red]the TUI wizard needs Textual: install with [bold]pip install 'phntm[tui]'[/][/]")
        raise typer.Exit(1)
    run_wizard()


# --------------------------------------------------------------------------- presets
@app.command("presets")
def cmd_presets() -> None:
    """List all personas and their tiers with estimated sizes."""
    catalog = load_catalog()
    presets = load_presets()

    table = Table(title=f"PHNTM presets  (catalog {catalog_version()})", show_lines=True)
    table.add_column("Persona", style="cyan", no_wrap=True)
    table.add_column("Tier", style="bold")
    table.add_column("Comps", justify="right")
    table.add_column("Est. size", justify="right")
    table.add_column("Budget note")

    for persona in available_personas():
        pdata = presets[persona.value]
        rows = []
        for tier in sorted(pdata.tiers):
            preset = pdata.tiers[tier]
            manifest = manifest_from_preset(persona, tier)
            budget = compute_budget(manifest, catalog)
            rows.append(
                (f"{pdata.emoji} {pdata.label}", f"[green]{tier} GB[/]", str(len(preset.components)),
                 f"{budget.used_gb:.1f} GB", ("✅ fits" if budget.fits else "❌ overflow"))
            )
        for i, row in enumerate(rows):
            if i == 0:
                table.add_row(*row)
            else:
                table.add_row("", *row[1:])
        table.add_section()
    console.print(table)
    rprint("\nRecommended: [bold]phntm manifest new --persona <name> --tier <gb> --out build.json[/]")


# --------------------------------------------------------------------------- components
@app.command("components")
def cmd_components(
    query: str = typer.Argument("", help="free-text filter on id/name"),
    persona: str = typer.Option("", "--persona", "-p", help="filter by persona tag"),
    category: str = typer.Option("", "--category", "-c", help="filter by category"),
    kind: str = typer.Option("", "--kind", "-k", help="filter by kind: iso | tool | portable | custom"),
    direct: bool = typer.Option(False, "--direct", help="only components with a direct download link"),
) -> None:
    """Browse the component catalog."""
    catalog = load_catalog()
    q = query.lower()
    rows = [
        e for e in catalog.values()
        if (not q or q in e.id or q in e.name.lower())
        and (not persona or persona in {t.value for t in e.persona_tags})
        and (not category or category in e.categories)
        and (not kind or e.kind == kind)
        and (not direct or e.download_url)
    ]
    if not rows:
        rprint("[yellow]no components match that filter[/]")
        raise typer.Exit(0)
    table = Table(title=f"Catalog — {len(rows)} matches ({catalog_version()})")
    table.add_column("id", style="cyan", no_wrap=True)
    table.add_column("name")
    table.add_column("size", justify="right")
    table.add_column("kind")
    table.add_column("personas")
    table.add_column("categories")
    table.add_column("dl")
    for e in sorted(rows, key=lambda x: x.id):
        table.add_row(
            e.id,
            e.name,
            f"{e.size_gb:g} GB",
            e.kind,
            ",".join(p.value for p in e.persona_tags) or "—",
            ",".join(e.categories),
            "🛰" if e.download_url else "—",
        )
    console.print(table)


# --------------------------------------------------------------------------- doctor
@app.command("doctor")
def cmd_doctor() -> None:
    """Check this machine is ready to build sticks."""
    import platform
    import shutil

    from .engine.fetch import cache_status
    from .engine.ventoy import VentoyTool

    rprint("[bold]PHNTM doctor[/]")
    checks: list[tuple[str, str, bool]] = [
        ("python", platform.python_version(), True),
        ("phntm", f"v{VERSION}", True),
        ("catalog", catalog_version(), True),
        ("venv", "active ✅" if sys.prefix != sys.base_prefix else "⚠️ system python", sys.prefix != sys.base_prefix),
    ]
    cl = cache_status()
    checks.append(("cache", f"{cl['count']} component(s), {cl['total_gb']:.2f} GB", True))
    tool = VentoyTool.detect()
    checks.append(("ventoy", tool.message, tool.mode != "none"))
    docker = shutil.which("docker")
    checks.append(("docker", docker or "missing → ventoy native fallback ok", docker is not None))
    qemu = shutil.which("qemu-system-x86_64")
    checks.append(("qemu", qemu or "missing — needed to boot-test sticks once the driver is wired", qemu is not None))

    for name, val, ok in checks:
        rprint(f"  {'✅' if ok else '⚠️'} {name:<10} {val}")
    if tool.mode == "none":
        rprint("\n[yellow]No ventoy binary and no docker found — installing either enables real builds.[/]")


# --------------------------------------------------------------------------- manifest
@app.command("manifest")
def cmd_manifest(
    action: str = typer.Argument(..., help="new | validate | show"),
    persona: str = typer.Option("pentest", "--persona", "-p", help="persona id"),
    tier: int = typer.Option(32, "--tier", "-t", help="tier in GB (16/32/64/128)"),
    out: str = typer.Option("phntm-manifest.json", "--out", "-o", help="output manifest file"),
    file: str = typer.Option("", "--file", "-f", help="manifest file for validate/show"),
) -> None:
    """Create, validate, or pretty-print a build manifest."""
    try:
        p = Persona(persona)
    except ValueError:
        rprint(f"[red]unknown persona '{persona}'. Choose: {', '.join(x.value for x in Persona)}[/]")
        raise typer.Exit(1)

    if p == Persona.GENERAL:
        rprint("[yellow]note: GENERAL presets exist for 64/128 GB tiers[/]")
    available = tiers_for(p)

    if action == "new":
        if tier not in available + ([16, 32, 64, 128] if p == Persona.GENERAL else []):
            rprint(f"[yellow]tip: '{p.value}' ships presets for {available} GB; you picked {tier} (build anyway works)[/]")
        try:
            manifest = manifest_from_preset(p, tier)
        except KeyError as exc:
            rprint(f"[red]{exc}[/]")
            raise typer.Exit(1)
        write_manifest(manifest, out)
        rprint(f"[green]✔ manifest '{manifest.name}' written to {out}[/]")
        rprint("   validate it: [bold]phntm manifest validate --file " + out + "[/]")
        rprint("   preview it:  [bold]phntm build " + out + " --dry-run[/]")
    elif action == "validate":
        manifest = read_manifest(file)
        catalog = load_catalog()
        resolve_components(manifest.components, catalog)  # raises on unknown ids
        budget = compute_budget(manifest, catalog)
        rprint(f"[green]✔ '{manifest.name}' valid (manifestVersion={manifest.manifestVersion})[/]")
        rprint(format_budget(budget))
        if not budget.fits:
            rprint("[red]✘ plan does not fit — shrink vault/drop or raise tier[/]")
            raise typer.Exit(1)
    elif action == "show":
        manifest = read_manifest(file)
        rprint(manifest.model_dump_json(indent=2))
    else:
        rprint(f"[red]unknown action '{action}' (use new|validate|show)[/]")
        raise typer.Exit(1)


# --------------------------------------------------------------------------- devices
@app.command("devices")
def cmd_devices() -> None:
    """Detect plugged-in USB sticks: size, USB version, model, Ventoy state."""
    from .engine.devices import scan_devices
    from .engine.ventoy import VentoyTool

    sticks = scan_devices()
    ventoy = VentoyTool.detect()

    def _ventoy_state(path: str) -> str:
        if ventoy.mode == "none":
            return "n/a"
        try:
            return "installed ✅" if ventoy.installed_on(path) else "not yet"
        except Exception:
            return "?"

    if not sticks:
        rprint("[yellow]No removable USB stick detected.[/]")
        rprint("  Plug one in and run again — or build with ")
        rprint("  [bold]phntm build manifest.json --device /dev/sdX[/] when ready.")
        return
    table = Table(title=f"{len(sticks)} USB stick(s) detected")
    table.add_column("device", style="green", no_wrap=True)
    table.add_column("capacity", justify="right", style="bold")
    table.add_column("usb")
    table.add_column("ventoy")
    table.add_column("model")
    table.add_column("vendor")
    for s in sticks:
        table.add_row(
            s.path,
            s.human_size(),
            s.usb.speed_label if s.usb else "unknown",
            _ventoy_state(s.path),
            s.model or "—",
            (s.usb.vendor or s.vendor or "—").strip(),
        )
    console.print(table)
    rprint("\nSuggest: [bold]phntm manifest new -p <persona> -t <tier>[/] then [bold]phntm build -d auto[/]")


# --------------------------------------------------------------------------- check
@app.command("check")
def cmd_check(
    target: str = typer.Argument(..., help="manifest json OR a stick mount dir with phntm.json"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="show url/size details too"),
) -> None:
    """Diff a manifest (or a built stick) against the current catalog."""
    from .engine.metadata import read_metadata_stick
    from .engine.update import diff_pins
    from .models import ComponentPin

    catalog = load_catalog()
    target_path = Path(target)
    # A mount dir or an existing non-file (e.g. /dev/sdX) means "stick".
    if target_path.is_dir() or (target_path.exists() and not target_path.is_file()):
        try:
            meta, _ = read_metadata_stick(target)
        except FileNotFoundError as exc:
            rprint(f"[red]{exc}[/]")
            raise typer.Exit(1)
        pins = meta.components
        source = f"stick at {target}"
    else:
        manifest = read_manifest(target)
        resolve_components(manifest.components, catalog)
        pins = [
            ComponentPin(
                id=cid,
                name=catalog[cid].name,
                size_gb=catalog[cid].size_gb,
                sha256=catalog[cid].sha256,
                release=catalog[cid].release,
            )
            for cid in manifest.components
        ]
        source = f"manifest '{manifest.name}'"

    diff = diff_pins(pins, catalog)
    rprint(f"[bold]PHNTM check[/] — {source} vs catalog [i]{catalog_version()}[/]")
    if diff.current:
        rprint(f"  [green]✅ current ({len(diff.current)}):[/] {', '.join(sorted(diff.current))}")
    for cid, old, new in diff.stale:
        rprint(f"  [yellow]⬆  update available:[/] {cid}  {old} → {new}")
        if verbose:
            rprint(f"     new url: {catalog[cid].url}")
    for cid in diff.vanished:
        rprint(f"  [red]🗑  no longer in catalog:[/] {cid}")

    if not diff.outdated:
        rprint("  [green]Fully current — nothing to do.[/]")
    elif diff.stale:
        rprint("\n  [yellow]Re-flash the affected ISOs from the new download URLs to refresh a build.[/]")
    if diff.vanished:
        raise typer.Exit(1)


# --------------------------------------------------------------------------- help
@app.command("help")
def cmd_help() -> None:
    """The PHNTM pocket guide."""
    guide = """[bold cyan]PHNTM pocket guide[/]

[b]WIZARD[/]
  phntm tui                        guided: persona → tier → plan → save (TUI)

[b]EXPLORE[/]
  phntm devices                     see plugged-in sticks + USB + Ventoy state
  phntm presets                     persona × tier matrix (14 presets)
  phntm components [kw]             browse the catalog [--persona] [--category] [--kind] [--direct]
  phntm doctor                      is this machine build-ready?
  phntm cache                       what's in the offline cache

[b]PLAN[/]
  phntm manifest new -p <persona> -t <tier> -o build.json    16/32/64/128 GB
  phntm manifest validate -f build.json                      fits? valid?
  phntm build build.json --dry-run                           full plan, safe

[b]OFFLINE ARSENAL[/]
  phntm fetch --all                                          grab ISOs → ~/.cache/phntm
  phntm fetch kali-linux hirens-boot-pe                      …or just a few
  phntm fetch --verify                                       re-check cached files
  (resumable; sha256-verified when the catalog knows a hash)

[b]BUILD[/]
  phntm build build.json -d auto -y                          single stick = auto-pick
  phntm build build.json -d /dev/sdX -y                      explicit device
  (builds refuse wrong sizes, missing devices — loudly; flashes Ventoy, smart upgrade)

[b]AFTER[/]
  phntm status /media/USB                                    what is on the stick?
  phntm status /dev/sdX                                      same, from the block device
  phntm check build.json                                     is it current vs catalog?
  phntm check /media/USB                                     same, from the stick itself

[b]RULES OF THE STICK[/]
  DROP/    plaintext scratch      VAULT/  encrypted (cryptsetup)
  PERSIST/ LUKS per-OS state      ISOS/   sha256-verified bootables
  phntm.json metadata             no phone-home, no cloud, no host needed
"""
    rprint(guide)


# --------------------------------------------------------------------------- build
@app.command("build")
def cmd_build(
    file: str = typer.Argument(..., help="manifest json file"),
    dry: bool = typer.Option(True, "--dry-run/--no-dry-run", help="plan-only (default) or execute"),
    device: str = typer.Option("", "--device", "-d", help="/dev/sdX, or auto to pick the single stick"),
    mount: str = typer.Option("", "--mount", "-m", help="stick mount point (for phntm.json)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="confirm destructive build"),
) -> None:
    """Plan (dry-run) or execute a real build from a manifest."""
    from .engine.devices import device_capacity, resolve_device, scan_devices

    catalog = load_catalog()
    manifest = read_manifest(file)
    resolve_components(manifest.components, catalog)

    if not dry and not device:
        rprint("[red]a real build needs a target stick: pass --device /dev/sdX (or -d auto)[/]")
        rprint("  [yellow]first preview it:[/] [bold]phntm build " + file + " --dry-run[/]")
        raise typer.Exit(1)

    if dry or not device:
        needed = compute_budget(manifest, catalog).used_gb
        sticks = scan_devices()
        rprint(dry_run(manifest, catalog))
        # Offline-first: tell the user what the manifest still needs fetched.
        from .engine.fetch import list_cache

        have = list_cache()
        missing = sorted(
            catalog[c].id for c in manifest.components
            if catalog[c].kind == "iso" and c not in have
        )
        if missing:
            rprint(f"[yellow]not yet cached:[/] {', '.join(missing)} — snag them with "
                   f"[bold]phntm fetch {' '.join(missing)}[/]")
        elif any(catalog[c].kind == "iso" for c in manifest.components):
            rprint("[green]ISO components all cached — this build can run fully offline.[/]")
        if sticks:
            fits_one = next((s for s in sticks if s.fits(needed)), None)
            if fits_one:
                rprint(f"[green]Stick ready for this build:[/] {fits_one.path} "
                       f"({fits_one.human_size()}, USB {fits_one.usb.speed_label}) — build with [bold]-d auto[/]")
            else:
                rprint("[yellow]No plugged stick has room for this plan.[/] "
                       "Pick a bigger tier or trim components in the manifest.")
        else:
            rprint("\n[yellow]No USB stick currently detected — plug one in, then build with -d auto.[/]")
        return

    try:
        resolved = resolve_device(device)
        # Capacity gate: refuse to start something the stick physically can't hold.
        needed = compute_budget(manifest, catalog).used_gb
        real_cap = device_capacity(resolved)
        if real_cap and real_cap < needed + 1.0:
            rprint(
                f"[red]✘ {resolved} has {real_cap:.1f} GB but the plan needs {needed:.1f} GB. "
                "Raise the tier or shrink vault/drop/components.[/]"
            )
            raise typer.Exit(1)
        meta = run_build(manifest, catalog, resolved, yes=yes)
        if mount:
            path = write_metadata(mount, meta)
            rprint(f"[green]✔ build complete — metadata at {path}[/]")
        else:
            rprint("[green]✔ build complete. Mount the stick, then:")
            rprint("    [bold]phntm status /media/USB[/]   after running")
            rprint("    [bold]phntm check /media/USB[/]    to track catalog freshness")
            rprint("    to record stick metadata.")
    except BuildError as exc:
        rprint(f"[red]✘ {exc}[/]")
        raise typer.Exit(1)
    except LookupError as exc:
        rprint(f"[red]✘ {exc}[/]")
        raise typer.Exit(1)


# --------------------------------------------------------------------------- status
@app.command("status")
def cmd_status(device: str = typer.Argument(..., help="stick mount point or block device")) -> None:
    """Show what a PHNTM-built stick contains."""
    from .engine.metadata import read_metadata_stick

    try:
        meta, meta_path = read_metadata_stick(device)
    except FileNotFoundError as exc:
        rprint(f"[red]{exc}[/]")
        raise typer.Exit(1)
    rprint("[bold]PHNTM stick status[/]")
    rprint(status_snippet(meta))
    rprint(f"\n  metadata: {meta_path}")


# --------------------------------------------------------------------------- update
@app.command("update")
def cmd_update(
    dry: bool = typer.Option(True, "--dry-run/--apply", help="show what would change (default)"),
) -> None:
    """Refresh the component catalog (v1: informational)."""
    current = load_catalog()
    with_dl = sum(1 for e in current.values() if e.download_url)
    rprint(f"[bold]catalog[/] {catalog_version()} — {len(current)} components ({with_dl} with direct download links)")
    if dry:
        rprint("[yellow]This build ships the bundled catalog. Network refresh arrives in a later release.[/]")
        rprint("[green]Fetch ISOs into the offline cache now:[/] [bold]phntm fetch --all[/]  (or [bold]phntm fetch <id>…[/])")
    else:
        rprint("[yellow]automatic catalog pull is not wired yet; keep this build fully local by design.[/]")


# --------------------------------------------------------------------------- fetch
@app.command("fetch")
def cmd_fetch(
    components: List[str] = typer.Argument(None, help="component ids to fetch (e.g. kali-linux)"),
    all_: bool = typer.Option(False, "--all", help="fetch every component that has a direct download link"),
    manifest: str = typer.Option("", "--manifest", "-m", help="fetch exactly the components in a manifest"),
    verify: bool = typer.Option(False, "--verify", help="verify already-cached files instead of downloading"),
    cache: str = typer.Option("", "--cache", help="cache dir (default ~/.cache/phntm)"),
) -> None:
    """Download component files (ISOs) into the local offline cache."""
    from .engine.fetch import FetchError, fetch, filename_for

    catalog = load_catalog()
    ids: list[str] = []
    if manifest:
        ids = read_manifest(manifest).components
    elif all_:
        ids = sorted(c.id for c in catalog.values() if c.download_url)
    elif components:
        ids = components
    else:
        rprint("[red]give component ids, or use --all / --manifest <file>[/]")
        raise typer.Exit(1)

    unknown = [i for i in ids if i not in catalog]
    if unknown:
        rprint(f"[red]unknown component(s): {', '.join(unknown)}[/]")
        raise typer.Exit(1)

    if verify:
        rprint(f"[bold]phntm fetch --verify[/] — checking {len(ids)} cached file(s)…")
    else:
        rprint(f"[bold]phntm fetch[/] — {len(ids)} component(s) → {cache or '~/.cache/phntm'}")
    entries = [catalog[i] for i in ids]
    tty = sys.stdout.isatty()
    errors: list[str] = []

    def _quiet_progress(entry, done: int, total: int | None) -> None:
        if not tty:
            return
        pct = f"{done/1024/1024:.0f}/{total/1024/1024:.0f} MiB" if total else f"{done/1024/1024:.0f} MiB"
        print(f"\r  {entry.id:<20} {pct:<28}", end="", flush=True)

    results: list = []
    if tty:
        from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TransferSpeedColumn

        with Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            transient=True,
        ) as prog:
            for e in entries:
                task = prog.add_task(f"  {e.id}", total=None)

                def cb(done: int, total: int | None, task_id=task) -> None:
                    if total is not None and prog.tasks[task_id].total is None:
                        prog.update(task_id, total=total)
                    prog.update(task_id, completed=done)

                try:
                    results.append(fetch(e, cache=cache or None, verify_only=verify, progress=cb))
                except FetchError as exc:
                    errors.append(str(exc))
    else:
        for e in entries:
            try:
                results.append(fetch(e, cache=cache or None, verify_only=verify, progress=_quiet_progress))
            except FetchError as exc:
                errors.append(str(exc))
    if tty:
        print()
    for err in errors:
        rprint(f"[red]✘ {err}[/]")
    for r in results:
        flag = "cached ✔" if not r.fresh else ("verified ✔" if verify else "downloaded ✔")
        checksum = f"sha256 ok" if r.checksum_ok else ("sha256 n/a" if r.checksum_ok is None else "sha256 MISMATCH")
        rprint(f"  [green]{r.entry.id:<20}[/] {flag:<12} {filename_for(r.entry)}  ({r.size/1024/1024:.0f} MiB, {checksum})")
    total_mib = sum(r.size for r in results) / 1024 / 1024
    rprint(f"[bold]done[/] {len(results)} file(s), {total_mib:.0f} MiB in cache. Build stays offline — stick to [bold]phntm build[/].")
    if errors:
        rprint(f"[yellow]{len(errors)} of {len(entries)} failed[/] — see above.")
        raise typer.Exit(1)


# --------------------------------------------------------------------------- cache
@app.command("cache")
def cmd_cache(cache: str = typer.Option("", "--cache", help="cache dir (default ~/.cache/phntm)")) -> None:
    """Show what's in the offline cache."""
    from .engine.fetch import cache_status

    st = cache_status(cache or None)
    n, total_gb = st["count"], st["total_gb"]
    rprint(f"[bold]phntm cache[/] — {n} component{'s' if n != 1 else ''}: {total_gb:.2f} GB"
           f"{'' if cache else '  (~/.cache/phntm)'}")
    if not n:
        rprint("[yellow]cache is empty — [bold]phntm fetch --all[/] fills it[/]")
        return
    for cid, p in sorted(st["files"].items()):
        rprint(f"  [green]{cid:<20}[/] {p}")


# --------------------------------------------------------------------------- test
@app.command("test")
def cmd_test(device: str = typer.Option("", "--device", "-d", help="/dev/sdX of the stick")) -> None:
    """QEMU boot-test a stick (planned)."""
    if not device:
        rprint("[red]--device /dev/sdX is required (the stick you want to boot-test)[/]")
        raise typer.Exit(1)
    rprint(f"[yellow]QEMU boot-test driver is planned. Coming: qemu-system-x86_64 -drive file={device},if=none…[/]")


# --------------------------------------------------------------------------- helpers
def read_manifest(path: str) -> BuildManifest:
    p = Path(path)
    if not p.exists():
        rprint(f"[red]manifest not found: {path}[/]")
        raise typer.Exit(1)
    try:
        return BuildManifest.model_validate(json.loads(p.read_text()))
    except Exception as exc:  # pydantic ValidationError et al. — keep the message short
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else repr(exc)
        rprint(f"[red]invalid manifest: {first}[/]")
        raise typer.Exit(1)


def write_manifest(manifest: BuildManifest, path: str) -> Path:
    p = Path(path)
    p.write_text(manifest.model_dump_json(indent=2) + "\n")
    return p


if __name__ == "__main__":
    app()