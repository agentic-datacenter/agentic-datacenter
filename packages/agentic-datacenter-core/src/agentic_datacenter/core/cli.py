"""The ``agentic-datacenter`` command."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from importlib.metadata import entry_points
from pathlib import Path

import yaml

from agentic_datacenter.core.clock import wall_seconds
from agentic_datacenter.core.profile import Profile, ProfileError, build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel

LOCK_FILE = "modules.lock.yaml"
_HEADER = (
    "# Generated from the module manifests by `agentic-datacenter modules lock`. Do not edit.\n"
    "# CI fails when this file differs from the manifests (ADC-MOD-005).\n"
)


def render_lock(registry: ModuleRegistry) -> str:
    """Return the text of ``modules.lock.yaml`` for *registry*."""
    return _HEADER + yaml.safe_dump(registry.lock_data(), sort_keys=False)


def _modules_list(registry: ModuleRegistry) -> int:
    rows = [(m.id, m.version, m.fidelity, m.zone) for m in registry.manifests()]
    width = max((len(r[0]) for r in rows), default=0)
    for module_id, version, fidelity, zone in rows:
        print(f"{module_id:<{width}}  {version}  {fidelity}  {zone}")
    return 0


def _wiring(registry: ModuleRegistry, profile_path: Path) -> int:
    plant = build_plant(load_profile(profile_path), Kernel(seed=0), registry)
    for consumer, provider, port_type in plant.wiring():
        print(f"{consumer}  <-  {provider}  ({port_type})")
    return 0


def render_schema() -> str:
    """Return the text of ``profiles/schema.json``."""
    return json.dumps(Profile.model_json_schema(), indent=2, sort_keys=True) + "\n"


def _profile_schema(path: Path, check: bool) -> int:
    text = render_schema()
    if not check:
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")
        return 0
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        print(f"{path} is stale; run `agentic-datacenter profile schema`", file=sys.stderr)
        return 1
    return 0


def _profile_validate(path: Path) -> int:
    profile = load_profile(path)
    print(
        f"{profile.name}: {len(profile.instances())} instances, "
        f"{len(profile.connections())} connections, hash {profile.hash()}"
    )
    return 0


def _run(
    registry: ModuleRegistry, profile_path: Path, seed: int, seconds: int, quantized: bool
) -> int:
    profile = load_profile(profile_path)
    kernel = Kernel(seed=seed)
    build_plant(profile, kernel, registry)
    start = wall_seconds()
    for _ in range(seconds):
        kernel.run_for(1000)
        kernel.state_hash()
    elapsed = wall_seconds() - start
    print(f"profile         {profile.name} ({profile.hash()})")
    print(f"seed            {seed}")
    print(f"simulated time  {kernel.clock.now_s:.1f} s")
    print(f"state hash      {kernel.state_hash()}")
    if quantized:
        print(f"quantized state hash  {kernel.quantized_state_hash()}")
    print(f"wall time       {elapsed:.2f} s", file=sys.stderr)
    return 0


def _modules_graph(registry: ModuleRegistry) -> int:
    for manifest in registry.manifests():
        print(manifest.id)
        for decl in manifest.provides:
            print(f"  provides  {decl.label()}")
        for decl in manifest.requires:
            print(f"  requires  {decl.label()}")
    return 0


def _modules_lock(registry: ModuleRegistry, path: Path, check: bool) -> int:
    text = render_lock(registry)
    if not check:
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")
        return 0
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        print(f"{path} is stale; run `agentic-datacenter modules lock`", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``agentic-datacenter`` command and return its exit status."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Higher layers add commands through the `agentic_datacenter.commands` entry-point
    # group, so the kernel does not import them.
    extra = {point.name: point for point in entry_points(group="agentic_datacenter.commands")}
    if arguments and arguments[0] in extra:
        status: int = extra[arguments[0]].load()(arguments[1:])
        return status
    parser = argparse.ArgumentParser(
        prog="agentic-datacenter", description="Data center OT simulator."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    modules = commands.add_parser("modules", help="Inspect the installed plant modules.")
    actions = modules.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="Module, version, fidelity level and zone.")
    graph = actions.add_parser("graph", help="Ports per module, or the wiring of a profile.")
    graph.add_argument("--profile", type=Path, help="Print the wiring of this profile.")
    lock = actions.add_parser("lock", help=f"Write {LOCK_FILE} from the manifests.")
    lock.add_argument("--check", action="store_true", help="Fail if the file is stale.")
    lock.add_argument("--path", type=Path, default=Path(LOCK_FILE))
    profile = commands.add_parser("profile", help="Check facility profiles.")
    profile_actions = profile.add_subparsers(dest="action", required=True)
    validate = profile_actions.add_parser("validate", help="Validate one profile file.")
    validate.add_argument("path", type=Path)
    schema = profile_actions.add_parser("schema", help="Write profiles/schema.json.")
    schema.add_argument("--check", action="store_true", help="Fail if the file is stale.")
    schema.add_argument("--path", type=Path, default=Path("profiles/schema.json"))
    run = commands.add_parser("run", help="Run a profile for a number of simulated seconds.")
    run.add_argument("--profile", type=Path, required=True)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--seconds", type=int, default=60)
    run.add_argument(
        "--quantized",
        action="store_true",
        help="Also print the hash with floats rounded to nine digits (ADC-CI-004).",
    )
    args = parser.parse_args(arguments)

    try:
        if args.command == "profile":
            if args.action == "validate":
                return _profile_validate(args.path)
            return _profile_schema(args.path, args.check)
        registry = ModuleRegistry.from_entry_points()
        if args.command == "run":
            return _run(registry, args.profile, args.seed, args.seconds, args.quantized)
        if args.action == "list":
            return _modules_list(registry)
        if args.action == "graph":
            if args.profile is not None:
                return _wiring(registry, args.profile)
            return _modules_graph(registry)
        return _modules_lock(registry, args.path, args.check)
    except ProfileError as exc:
        print(f"agentic-datacenter: {exc}", file=sys.stderr)
        return 1
