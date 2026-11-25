"""The ``agentic-datacenter bench`` command."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from agentic_datacenter.core.facility import FacilityError, load_facility
from agentic_datacenter.core.profile import ProfileError, load_profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.agents import AGENTS
from agentic_datacenter.scenarios.bench import (
    TIERS,
    BenchVersionError,
    CardMergeError,
    benchmark_version,
    load_gates,
    merge_cards,
    run_benchmark,
    write_card,
    write_decisions,
)
from agentic_datacenter.scenarios.demo import DEMO_AGENTS, DEMO_SCENARIOS, build_demo, write_demo
from agentic_datacenter.scenarios.evidence import (
    build_bundle,
    code_commit,
    verify_bundle,
    write_bundle,
)
from agentic_datacenter.scenarios.facility_fit import fit_facility
from agentic_datacenter.scenarios.harness import RunResult, run_scenario
from agentic_datacenter.scenarios.heldout import commitment
from agentic_datacenter.scenarios.llm_agent import (
    MAX_CALLS,
    PROVIDERS,
    LlmAgentError,
    LlmAgentFactory,
    LlmOptions,
    agent_kind,
    agent_note,
    is_llm,
    parse_name,
)
from agentic_datacenter.scenarios.provenance import CARD_NAME, verify_record, write_record
from agentic_datacenter.scenarios.release_gate import check_card
from agentic_datacenter.scenarios.scenario import Scenario, library_ids, load_scenario


def _agent_name(scripted: Sequence[str]) -> Any:
    """Return an argparse type: a scripted agent of *scripted*, or ``llm:<provider>/<model>``."""

    def check(value: str) -> str:
        if value in scripted:
            return value
        if is_llm(value):
            try:
                parse_name(value)
            except LlmAgentError as exc:
                raise argparse.ArgumentTypeError(str(exc)) from exc
            return value
        raise argparse.ArgumentTypeError(
            f"no such agent: {value!r}; choose one of {', '.join(scripted)}, "
            "or a language model as llm:<provider>/<model> (agentic-datacenter agent list)"
        )

    return check


def _llm_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the options of a language-model agent (ADR 0035), which are used only with one."""
    group = parser.add_argument_group(
        "language-model agent", "Optional; the default agents are scripted (ADR 0035)."
    )
    group.add_argument(
        "--llm-transcripts", type=Path,
        help="Where each run's transcript of requests and replies is written.",
    )  # fmt: skip
    group.add_argument(
        "--llm-replay", type=Path,
        help="Replay the runs from the transcripts here, calling no model.",
    )  # fmt: skip
    group.add_argument(
        "--llm-max-calls", type=int, default=MAX_CALLS,
        help=f"Calls to the model one run may make (default {MAX_CALLS}).",
    )  # fmt: skip
    group.add_argument(
        "--llm-effort", choices=["low", "medium", "high", "xhigh", "max"],
        help="The effort asked of an Anthropic model; the provider's default if left out.",
    )  # fmt: skip


def _llm_options(args: argparse.Namespace, default_transcripts: Path) -> LlmOptions:
    replay = args.llm_replay
    if replay is not None and replay.is_dir() and (replay / "llm_transcript.jsonl").is_file():
        replay = replay / "llm_transcript.jsonl"  # an evidence bundle of an earlier run
    return LlmOptions(
        transcripts=args.llm_transcripts or default_transcripts, replay=replay,
        max_calls=args.llm_max_calls, effort=args.llm_effort,
    )  # fmt: skip


def agent(argv: Sequence[str]) -> int:
    """List the agents a run can be given: the scripted ones, and the language-model providers.

    Runs ``agentic-datacenter agent list`` and returns the exit status.
    The first line is the help text of ``agentic-datacenter --help``.
    """
    parser = argparse.ArgumentParser(
        prog="agentic-datacenter agent", description="The agents a run can be given."
    )
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="List the scripted agents and the language-model providers.")
    parser.parse_args(argv)
    print("Scripted agents (the default): predefined, simulated calls, no model, no key.")
    for name, make in sorted(DEMO_AGENTS.items()):
        doc = (make.__doc__ or "").strip().splitlines()
        print(f"  {name:22s} {doc[0] if doc else ''}")
    print()
    print("Language-model agents (optional: uv sync --group llm), named llm:<provider>/<model>:")
    for provider, needs in PROVIDERS.items():
        print(f"  llm:{provider}/<model>  {needs}")
    print()
    print("A language-model agent is reported apart from the scripted agents and is never a")
    print("benchmark result. Every request and reply is kept in a transcript (ADR 0035).")
    return 0


def bench(argv: Sequence[str]) -> int:
    """Benchmark gates over the scenario library, and merge, freeze and check results.

    Runs ``agentic-datacenter bench run ...`` and returns the exit status.
    The first line is the help text of ``agentic-datacenter --help``.
    """
    parser = argparse.ArgumentParser(
        prog="agentic-datacenter bench", description="Agentic-Datacenter Bench."
    )
    actions = parser.add_subparsers(dest="action", required=True)
    run = actions.add_parser("run", help="Benchmark gates and write a result card.")
    run.add_argument("--gate", action="append", help="Gate entry point; repeat for several.")
    run.add_argument(
        "--agent", action="append", type=_agent_name(sorted(AGENTS)),
        help="An agent; repeat for several. Default: both scripted agents. A language model "
        "is named llm:<provider>/<model> and is run apart from the scripted agents.",
    )  # fmt: skip
    run.add_argument("--scenario", action="append", choices=library_ids())
    run.add_argument("--seeds", type=int, help="Number of seeds (default 1, or the tier's).")
    run.add_argument(
        "--first-seed", type=int, default=1,
        help="The first seed. Runs a part of a benchmark, to be merged with the others.",
    )  # fmt: skip
    run.add_argument(
        "--seconds", type=int,
        help="Shorten every scenario to exactly this many seconds, also beside a tier.",
    )  # fmt: skip
    run.add_argument("--profile", type=Path, default=Path("profiles/generic_dc.yaml"))
    run.add_argument(
        "--facility", type=Path,
        help="A facility of your own: a bundle directory or a profile (ADR 0033). Contracts "
        "and scenarios that do not fit it are listed on the card, not run.",
    )  # fmt: skip
    run.add_argument("--contracts", type=Path, default=Path("contracts"))
    run.add_argument("--frozen", type=Path, default=Path("docs/bench/VERSION.json"))
    run.add_argument(
        "--allow-unfrozen",
        action="store_true",
        help="Run a development version; the card is labelled as such.",
    )
    run.add_argument("--no-counterfactual", action="store_true")
    run.add_argument(
        "--tier", choices=sorted(TIERS),
        help="A preset of length, seeds and replay bounds (docs/bench/TIERS.md). "
        "Options given beside it take precedence.",
    )  # fmt: skip
    run.add_argument(
        "--horizon", type=int,
        help="Replay each proposal this many seconds after its decision, not to the end.",
    )  # fmt: skip
    run.add_argument("--max-judged", type=int, help="Judge at most this many proposals per run.")
    run.add_argument("--out", type=Path, default=Path("build/bench"))
    run.add_argument(
        "--heldout-secret-file", type=Path,
        help="Also run held-out variants (Track D) drawn from the secret in this file.",
    )  # fmt: skip
    run.add_argument("--heldout-variants", type=int, default=3)
    _llm_arguments(run)
    run.add_argument(
        "--jobs", type=int, default=1,
        help="Runs made at a time, each in a process of its own. The card is the same "
        "whatever the number.",
    )  # fmt: skip
    run.add_argument(
        "--replay-jobs", type=int, default=1,
        help="Processes that share the replay of one run, for a long replay such as "
        "--tier full. Beside --jobs: together they should not exceed the cores. "
        "The card is the same whatever the number.",
    )  # fmt: skip
    merge = actions.add_parser(
        "merge", help="Merge result cards made in parts (seed ranges, machines) into one."
    )
    merge.add_argument("cards", type=Path, nargs="+")
    merge.add_argument("--out", type=Path, required=True)
    freeze = actions.add_parser("freeze", help="Record the benchmark version, once.")
    freeze.add_argument("--profile", type=Path, default=Path("profiles/generic_dc.yaml"))
    freeze.add_argument("--contracts", type=Path, default=Path("contracts"))
    freeze.add_argument("--out", type=Path, default=Path("docs/bench/VERSION.json"))
    commit = actions.add_parser(
        "heldout-commit", help="Print the commitment to a held-out secret, for publication."
    )
    commit.add_argument("secret_file", type=Path)
    check = actions.add_parser(
        "check", help="Refuse a result card with any harmful execution or invariant breach."
    )
    check.add_argument("card", type=Path, help="A result_card.json.")
    check.add_argument("--gate", action="append", help="Gate to check; repeat for several.")
    check.add_argument(
        "--publication", action="store_true",
        help="Also require the frozen benchmark version: the check for a reported result.",
    )  # fmt: skip
    record = actions.add_parser(
        "record", help="Write the commit and the hash of every file beside a result card."
    )
    record.add_argument("directory", type=Path, help="The directory a benchmark wrote.")
    verify = actions.add_parser(
        "verify", help="Check the files beside a result card against their record."
    )
    verify.add_argument("directory", type=Path, help="The directory a benchmark wrote.")
    args = parser.parse_args(argv)

    if args.action == "check":
        return _check(args.card, args.gate or ["remora_governed"], args.publication)
    if args.action == "record":
        if not (args.directory / CARD_NAME).is_file():
            print(f"agentic-datacenter bench: no {CARD_NAME} in {args.directory}", file=sys.stderr)
            return 1
        print(f"record written to {write_record(args.directory, code_commit(Path.cwd()))}")
        return 0
    if args.action == "verify":
        problems = verify_record(args.directory)
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{args.directory}: {'intact' if not problems else 'NOT intact'}")
        return 1 if problems else 0

    if args.action == "merge":
        try:
            card = merge_cards([json.loads(p.read_text(encoding="utf-8")) for p in args.cards])
        except CardMergeError as exc:
            print(f"agentic-datacenter bench merge: {exc}", file=sys.stderr)
            return 1
        write_card(card, args.out)
        print(f"{len(args.cards)} cards merged into {args.out / 'result_card.json'}")
        return 0
    if args.action == "heldout-commit":
        print(commitment(args.secret_file.read_text(encoding="utf-8").strip()))
        return 0
    if args.action == "freeze":
        if args.out.exists():
            print(
                f"agentic-datacenter bench: {args.out} already holds a frozen version; "
                "a new version is a new file, never a rewrite",
                file=sys.stderr,
            )
            return 1
        version = benchmark_version(
            load_profile(args.profile), ContractLibrary.load(args.contracts), library_ids()
        )
        frozen_file = {
            "version": version,
            "scenarios": library_ids(),
            "code_commit": code_commit(Path.cwd()),
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(frozen_file, indent=2, sort_keys=True) + "\n", "utf-8")
        print(f"frozen benchmark version written to {args.out}")
        return 0
    installed = load_gates()
    names = args.gate or sorted(installed)
    unknown = [n for n in names if n not in installed]
    if unknown:
        print(
            f"agentic-datacenter bench: no such gate: {', '.join(unknown)}; installed: "
            f"{', '.join(sorted(installed))}",
            file=sys.stderr,
        )
        return 2
    frozen = None
    if args.frozen.is_file():
        frozen = json.loads(args.frozen.read_text(encoding="utf-8"))
        frozen = frozen.get("version", frozen)
    secret = None
    if args.heldout_secret_file is not None:
        secret = args.heldout_secret_file.read_text(encoding="utf-8").strip()
    if args.jobs < 1:
        print("agentic-datacenter bench: --jobs must be at least 1", file=sys.stderr)
        return 2
    if args.replay_jobs < 1:
        print("agentic-datacenter bench: --replay-jobs must be at least 1", file=sys.stderr)
        return 2
    preset = TIERS.get(args.tier or "", {})
    seeds = args.seeds if args.seeds is not None else int(preset.get("seeds") or 1)
    seconds = args.seconds if args.seconds is not None else preset.get("seconds")
    # A length given by hand is the length. Only a tier's own shortening is played
    # past an event it would cut off.
    reach = None if args.seconds is not None else preset.get("reach_s")
    horizon = args.horizon if args.horizon is not None else preset.get("horizon_s")
    max_judged = args.max_judged if args.max_judged is not None else preset.get("max_judged")

    def progress(done: int, total: int, run_id: str) -> None:
        print(f"[{done}/{total}] {run_id}", file=sys.stderr, flush=True)

    decided: list[dict[str, object]] = []
    profile, contracts = load_profile(args.profile), ContractLibrary.load(args.contracts)
    scenario_ids = args.scenario or library_ids()
    facility_block = None
    if args.facility is not None:
        try:
            own = load_facility(args.facility)
        except ProfileError as exc:
            print(f"agentic-datacenter bench: {exc}", file=sys.stderr)
            return 1
        fit = fit_facility(own.profile, contracts, scenario_ids)
        if not fit.runnable:
            print("agentic-datacenter bench: no scenario fits this facility", file=sys.stderr)
            return 1
        profile, contracts, scenario_ids = own.profile, fit.contracts, fit.runnable
        facility_block = {**own.summary(), **fit.block()}
        for scenario_id, reason in fit.not_run.items():
            print(f"not run: {scenario_id}, {reason}", file=sys.stderr)

    agent_names = args.agent or sorted(AGENTS)
    try:
        kind = agent_kind(agent_names)
    except LlmAgentError as exc:
        print(f"agentic-datacenter bench: {exc}", file=sys.stderr)
        return 2
    llm = None
    if kind == "language_model":
        llm = _llm_options(args, args.out / "llm-transcripts")
        print(
            "language-model agent: reported apart from the scripted agents, without "
            "counterfactual replay; transcripts in "
            f"{llm.replay if llm.replay is not None else llm.transcripts}",
            file=sys.stderr,
        )
    try:
        card = run_benchmark(
            profile, contracts,
            {name: installed[name] for name in names},
            agent_names,
            scenario_ids,
            list(range(args.first_seed, args.first_seed + seeds)), seconds,
            counterfactual=not args.no_counterfactual, frozen_version=frozen,
            # A quick run is for trying a gate and is never a result, so it needs no flag.
            allow_unfrozen=args.allow_unfrozen or args.tier == "quick",
            heldout_secret=secret, heldout_variants=args.heldout_variants if secret else 0,
            jobs=args.jobs, progress=progress, horizon_s=horizon, max_judged=max_judged,
            replay_jobs=args.replay_jobs, decisions=decided, reach_s=reach,
            facility=facility_block, llm=llm,
        )  # fmt: skip
    except LlmAgentError as exc:
        print(f"agentic-datacenter bench: {exc}", file=sys.stderr)
        return 1
    except BenchVersionError as exc:
        print(
            f"agentic-datacenter bench: {exc}. Use --allow-unfrozen for a development run. "
            "A season is run on its frozen version: check out that version's tag first "
            "(docs/bench/PUBLIC_TEST.md).",
            file=sys.stderr,
        )
        return 1
    write_card(card, args.out)
    write_decisions(decided, args.out)
    print(f"{card['label']}: {args.out / 'result_card.json'} and {args.out / 'report.html'}")
    models = card.get("language_models")
    if isinstance(models, list):
        print("agent: " + " ".join(agent_note("language_model", m) for m in models))
    else:
        print(f"agent: {agent_note('scripted')}")
    print(f"each decision and the gate's reasons: {args.out / 'decisions.jsonl'}")
    for row in card["results"]:
        assert isinstance(row, dict)
        print(
            f"  {row['gate']:18s} {row['agent']:22s} {row['operating_profile']:17s} "
            f"safety {row['safety']}  false blocks {row['false_block_rate']}  "
            f"approvals declined {row['approvals_declined']}  "
            f"without required approval {row['executed_without_required_approval']}"
            f" of {row['approval_required']}  verdicts {' '.join(row['verdicts_used'])}"
        )
        if row.get("proposals_without_authority"):
            print(
                f"  {'':18s} without a mandate: {row['executed_without_authority']} executed of "
                f"{row['proposals_without_authority']} proposed, "
                f"{row['refused_citing_authority']} refused citing authority"
            )
        counted = row.get("authority")
        if isinstance(counted, dict):
            if counted["runs_premise_withheld"]:
                print(
                    f"  {'':18s} given the mandate record and not the premise in "
                    f"{counted['runs_premise_withheld']} run(s)"
                )
            if counted["findings_given"]:
                print(
                    f"  {'':18s} its own finding of who may act: given for "
                    f"{counted['findings_given']}, {counted['findings_wrong']} of them not the "
                    "premise"
                )
            if counted["details_given"]:
                print(
                    f"  {'':18s} never held or ended: said for {counted['details_given']}, "
                    f"{counted['details_wrong']} of them not what the register holds"
                )
    return 0


def _check(path: Path, gates: Sequence[str], publication: bool = False) -> int:
    """Print the release gate's findings for each gate; 1 if any gate fails."""
    card = json.loads(path.read_text(encoding="utf-8"))
    version_file = Path("docs/bench/VERSION.json")
    frozen = json.loads(version_file.read_text("utf-8")) if version_file.is_file() else None
    failed = False
    for gate in gates:
        report = check_card(card, gate, publication, frozen)
        verdict = "passed" if report.passed else "REFUSED"
        print(f"{gate}: {verdict}, {report.runs_checked} runs checked")
        for line in report.violations:
            print(f"  violation: {line}")
        for line in report.notes:
            print(f"  note: {line}")
        failed = failed or not report.passed
    return 1 if failed else 0


def demo(argv: Sequence[str]) -> int:
    """Record a demo with a baseline and one or more gates.

    Runs ``agentic-datacenter demo`` and returns the exit status.
    The first line is the help text of ``agentic-datacenter --help``.
    """
    parser = argparse.ArgumentParser(
        prog="agentic-datacenter demo",
        description="Record a demo with a baseline and one or more gates.",
    )
    parser.add_argument("--gate", action="append", help="Gate to compare; repeat for several.")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--seconds", type=int, help="Shorten every scenario to this many seconds.")
    parser.add_argument("--full", action="store_true", help="Play the week of optimization whole.")
    parser.add_argument(
        "--scenario", action="append", choices=[s for s, _ in DEMO_SCENARIOS],
        help="Play only this scenario; repeat for several. OP-03 alone takes about a minute.",
    )  # fmt: skip
    parser.add_argument("--profile", type=Path, default=Path("profiles/generic_dc.yaml"))
    parser.add_argument("--facility", type=Path, help="A facility bundle or profile.")
    parser.add_argument("--contracts", type=Path, default=Path("contracts"))
    parser.add_argument("--out", type=Path, default=Path("build/demo"))
    args = parser.parse_args(argv)

    installed = load_gates()
    preferred = [name for name in ("remora_governed", "remora") if name in installed]
    selected = list(dict.fromkeys(args.gate or preferred[:1] or ["static_allowlist"]))
    if "null_gate" in selected:
        print("agentic-datacenter demo: null_gate is already the baseline", file=sys.stderr)
        return 2
    missing = [name for name in ("null_gate", *selected) if name not in installed]
    if missing:
        print(
            f"agentic-datacenter demo: no such gate: {', '.join(missing)}; installed: "
            f"{', '.join(sorted(installed))}",
            file=sys.stderr,
        )
        return 2
    contracts = ContractLibrary.load(args.contracts)
    only = args.scenario or [scenario_id for scenario_id, _ in DEMO_SCENARIOS]
    facility_block = None
    if args.facility is None:
        profile = load_profile(args.profile)
    else:
        try:
            own = load_facility(args.facility)
        except (FacilityError, ProfileError) as exc:
            print(f"agentic-datacenter demo: {exc}", file=sys.stderr)
            return 1
        fit = fit_facility(own.profile, contracts, only)
        if not fit.runnable:
            print(
                "agentic-datacenter demo: no selected scenario fits this facility", file=sys.stderr
            )
            for scenario_id, reason in fit.not_run.items():
                print(f"{scenario_id}: {reason}", file=sys.stderr)
            return 1
        profile, contracts, only = own.profile, fit.contracts, fit.runnable
        facility_block = {**own.summary(), **fit.block()}
    commit = code_commit(Path.cwd())

    def keep(played: Scenario, gate_name: str, result: RunResult) -> dict[str, Any]:
        bundle = build_bundle(result, profile, played, contracts, commit)
        write_bundle(bundle, args.out / "evidence" / f"{played.id}.{gate_name}")
        manifest: dict[str, Any] = json.loads(bundle["manifest.json"])
        return manifest

    recording = build_demo(
        profile,
        contracts,
        installed,
        selected[0],
        seed=args.seed,
        seconds=args.seconds,
        full=args.full,
        progress=lambda line: print(f"  {line}", file=sys.stderr),
        on_result=keep,
        only=only,
        additional_gates=selected[1:],
        facility=facility_block,
    )
    write_demo(recording, args.out)
    print(
        f"evidence bundles: {args.out / 'evidence'} "
        "(check one with: agentic-datacenter scenario verify)"
    )
    print(f"{recording['label']}: {args.out / 'index.html'} and {args.out / 'demo.json'}")
    for scenario in recording["scenarios"]:
        for side in scenario["sides"]:
            verdict = "passed" if side["passed"] else "not passed"
            print(f"  {scenario['scenario']}  {side['gate']:18s} {side['profile']:17s} {verdict}")
    return 0


def scenario(argv: Sequence[str]) -> int:
    """Run one scenario and write its evidence bundle, or verify a bundle.

    Runs ``agentic-datacenter scenario run|verify`` and returns the exit status.
    The first line is the help text of ``agentic-datacenter --help``.
    """
    parser = argparse.ArgumentParser(
        prog="agentic-datacenter scenario", description="Run one scenario."
    )
    actions = parser.add_subparsers(dest="action", required=True)
    run = actions.add_parser("run", help="Run a scenario and write its evidence bundle.")
    run.add_argument("scenario", choices=library_ids())
    run.add_argument("--gate", default="null_gate")
    run.add_argument(
        "--agent", type=_agent_name(sorted(DEMO_AGENTS)), default="scripted_benign",
        help="Default scripted_benign. A language model is named llm:<provider>/<model>.",
    )  # fmt: skip
    run.add_argument("--seed", type=int, default=1)
    run.add_argument("--seconds", type=int, help="Shorten the scenario to this many seconds.")
    run.add_argument("--profile", type=Path, default=Path("profiles/generic_dc.yaml"))
    run.add_argument(
        "--facility", type=Path,
        help="A facility of your own: a bundle directory or a profile (ADR 0033).",
    )  # fmt: skip
    run.add_argument("--contracts", type=Path, default=Path("contracts"))
    run.add_argument("--out", type=Path, default=Path("build/evidence"))
    _llm_arguments(run)
    verify = actions.add_parser("verify", help="Check an evidence bundle against its manifest.")
    verify.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)

    if args.action == "verify":
        problems = verify_bundle(args.bundle)
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{args.bundle}: {'intact' if not problems else 'NOT intact'}")
        return 1 if problems else 0
    installed = load_gates()
    if args.gate not in installed:
        print(
            f"agentic-datacenter scenario: no such gate: {args.gate}; "
            f"installed: {', '.join(sorted(installed))}",
            file=sys.stderr,
        )
        return 2
    profile, contracts = load_profile(args.profile), ContractLibrary.load(args.contracts)
    if args.facility is not None:
        try:
            own = load_facility(args.facility)
        except ProfileError as exc:
            print(f"agentic-datacenter scenario: {exc}", file=sys.stderr)
            return 1
        fit = fit_facility(own.profile, contracts, [args.scenario])
        if args.scenario in fit.not_run:
            print(
                f"agentic-datacenter scenario: {args.scenario} does not fit this facility: "
                f"{fit.not_run[args.scenario]}",
                file=sys.stderr,
            )
            return 2
        profile, contracts = own.profile, fit.contracts
        for contract_id, reason in fit.not_loaded.items():
            print(f"not loaded: {contract_id}, {reason}", file=sys.stderr)
    chosen = load_scenario(args.scenario)
    gate = installed[args.gate](contracts)
    operating = str(getattr(gate, "profile", "UNSPECIFIED"))
    factory = None
    if is_llm(args.agent):
        label = f"{chosen.id}.{args.gate}.{args.agent}.{args.seed}"
        options = _llm_options(args, args.out / "llm_transcript.jsonl")
        factory = LlmAgentFactory(args.agent, options, label)
    try:
        made = factory() if factory is not None else DEMO_AGENTS[args.agent]()
        result = run_scenario(
            chosen, profile, gate, operating, made, args.seed, contracts, args.seconds
        )
    except LlmAgentError as exc:
        print(f"agentic-datacenter scenario: {exc}", file=sys.stderr)
        return 1
    language_model, transcript = None, None
    if factory is not None:
        language_model = {**factory.describe(), "usage": factory.usage()}
        recorded = factory.transcript()
        if recorded is not None and recorded.is_file():
            transcript = recorded.read_text(encoding="utf-8")
    bundle = build_bundle(
        result, profile, chosen, contracts, code_commit(Path.cwd()),
        language_model=language_model, transcript=transcript,
    )  # fmt: skip
    write_bundle(bundle, args.out)
    verdict = "passed" if result.passed else "not passed: " + "; ".join(result.failed_criteria)
    print(f"{chosen.id} {args.gate} ({operating}) seed {args.seed}: {verdict}")
    kind = "language_model" if factory is not None else "scripted"
    print(f"agent: {result.agent}. {agent_note(kind, language_model)}")
    print(f"evidence bundle: {args.out}")
    return 0 if result.passed else 1


def gate(argv: Sequence[str]) -> int:
    """List the installed gates, or run the gate interface suite on one.

    Runs ``agentic-datacenter gate list|check`` and returns the exit status.
    The first line is the help text of ``agentic-datacenter --help``.

    ``check`` is what a gate from outside this repository passes before it is
    benchmarked: the gate interface suite (ADC-GOV-004) and a known operating
    profile. It checks the shape of what the gate returns; the benchmark judges
    its decisions.
    """
    from agentic_datacenter.governance.conformance import GateConformanceError, check_gate
    from agentic_datacenter.governance.control_path import PROFILES

    parser = argparse.ArgumentParser(
        prog="agentic-datacenter gate", description="Gates installed here."
    )
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser(
        "list", help="Every gate under the agentic_datacenter.gates entry-point group."
    )
    check = actions.add_parser("check", help="Run the gate interface suite on one gate.")
    check.add_argument(
        "gate", help="Entry-point name, as `agentic-datacenter gate list` prints it."
    )
    check.add_argument("--contracts", type=Path, default=Path("contracts"))
    args = parser.parse_args(argv)

    installed = load_gates()
    if args.action == "list":
        for name in sorted(installed):
            print(name)
        return 0
    if args.gate not in installed:
        print(
            f"agentic-datacenter gate: no such gate: {args.gate}; "
            f"installed: {', '.join(sorted(installed))}",
            file=sys.stderr,
        )
        return 2
    contracts = ContractLibrary.load(args.contracts)
    factory = installed[args.gate]
    try:
        made = factory(contracts)
        operating = str(getattr(made, "profile", ""))
        if operating not in PROFILES or operating == "BASELINE_RULES":
            known = ", ".join(p for p in PROFILES if p != "BASELINE_RULES")
            raise GateConformanceError(f"declares profile {operating!r}; expected one of {known}")
        made_here: list[object] = [made]

        def build() -> Any:
            gate = factory(contracts)
            made_here.append(gate)
            return gate

        check_gate(build)
        # A gate that cannot reach its service abstains, and abstaining passes
        # the suite; so a gate that reports failed calls fails the check here.
        failed = [f for gate in made_here for f in getattr(gate, "failures", [])]
        if failed:
            raise GateConformanceError(
                f"its service gave no usable answer {len(failed)} time(s); first: {failed[0]}"
            )
    except Exception as error:  # noqa: BLE001 - every failure of a foreign gate is reported
        print(f"{args.gate}: FAILED: {type(error).__name__}: {error}")
        return 1
    print(f"{args.gate}: passed the gate interface suite ({made.name}, {operating})")
    print(
        "next: agentic-datacenter bench run --gate "
        f"{args.gate} --seeds 3 --allow-unfrozen --out build/bench-{args.gate}"
    )
    return 0


def facility(argv: Sequence[str]) -> int:
    """Compile a facility of your own and check what of the libraries fits it.

    Runs ``agentic-datacenter facility init|compile|check|report`` and returns the exit
    status. The first line is the help text of ``agentic-datacenter --help``.
    """
    from agentic_datacenter.scenarios.facility_report import (
        check_facility,
        example_bundle,
        operator_report,
        write_operator_report,
        write_report,
    )

    parser = argparse.ArgumentParser(
        prog="agentic-datacenter facility",
        description="Bring your own data center: a bundle of files (ADR 0033).",
    )
    actions = parser.add_subparsers(dest="action", required=True)
    compile_ = actions.add_parser("compile", help="Write the profile a bundle compiles to.")
    compile_.add_argument("path", type=Path, help="A bundle directory, or a profile file.")
    compile_.add_argument("--out", type=Path, required=True)
    check = actions.add_parser(
        "check", help="Build the plant, run it, and report what contracts and scenarios fit."
    )
    check.add_argument("path", type=Path, help="A bundle directory, or a profile file.")
    check.add_argument("--contracts", type=Path, default=Path("contracts"))
    check.add_argument("--out", type=Path, default=Path("build/facility"))
    init = actions.add_parser("init", help="Start a bundle of your own from the example one.")
    init.add_argument("path", type=Path, help="A directory that does not exist yet, or is empty.")
    report_ = actions.add_parser(
        "report",
        help="One report for an operator: what fits, and what each gate does on the facility.",
    )
    report_.add_argument("path", type=Path, help="A bundle directory, or a profile file.")
    report_.add_argument("--gate", action="append", help="Gate to compare; repeat for several.")
    report_.add_argument("--contracts", type=Path, default=Path("contracts"))
    report_.add_argument("--out", type=Path, default=Path("build/operator-report"))
    args = parser.parse_args(argv)
    if args.action == "init":
        if args.path.exists() and any(args.path.iterdir()):
            print(f"agentic-datacenter facility: {args.path} is not empty", file=sys.stderr)
            return 1
        import shutil

        shutil.copytree(example_bundle(), args.path, dirs_exist_ok=True)
        print(
            f"a bundle of six PODs of three kinds is in {args.path}; change it, then run "
            f"`agentic-datacenter facility check {args.path}`"
        )
        return 0
    try:
        own = load_facility(args.path)
    except (FacilityError, ProfileError) as exc:
        print(f"agentic-datacenter facility: {exc}", file=sys.stderr)
        return 1
    if args.action == "compile":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        data = own.profile.model_dump(mode="json", by_alias=True, exclude_none=True)
        args.out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        print(f"{own.profile.name}: hash {own.profile.hash()}, written to {args.out}")
        return 0
    if args.action == "report":
        installed = load_gates()
        names = args.gate or [g for g in ("null_gate", "static_allowlist") if g in installed]
        unknown = [n for n in names if n not in installed]
        if unknown:
            print(
                f"agentic-datacenter facility: no such gate: {', '.join(unknown)}", file=sys.stderr
            )
            return 2
        result = operator_report(
            own, ContractLibrary.load(args.contracts), {n: installed[n] for n in names}
        )
        write_operator_report(result, args.out)
        print(f"{own.profile.name}: {args.out / 'operator_report.md'}")
        return 0
    report = check_facility(own, ContractLibrary.load(args.contracts))
    write_report(report, args.out)
    fit = report["fit"]
    print(
        f"{own.profile.name}: {len(fit['contracts_loaded'])} contracts load, "
        f"{len(fit['contracts_not_loaded'])} do not; {len(fit['scenarios_run'])} scenarios "
        f"fit, {len(fit['scenarios_not_run'])} do not. Report: {args.out / 'facility_report.md'}"
    )
    return 0


def equipment(argv: Sequence[str]) -> int:
    """Check an equipment registry entry before it is submitted (ADR 0034).

    Runs ``agentic-datacenter equipment check <entry.yaml>`` and returns the exit status.
    The first line is the help text of ``agentic-datacenter --help``.
    """
    from pydantic import ValidationError

    from agentic_datacenter.core.equipment import Entry, load_sources, problems, registry_dir
    from agentic_datacenter.core.profile import build_plant, parse_profile
    from agentic_datacenter.core.registry import ModuleRegistry, WiringError
    from agentic_datacenter.core.scheduler import Kernel

    parser = argparse.ArgumentParser(
        prog="agentic-datacenter equipment", description="The equipment registry (ADR 0034)."
    )
    actions = parser.add_subparsers(dest="action", required=True)
    check = actions.add_parser("check", help="Check one entry, as the registry's gate would.")
    check.add_argument("entry", type=Path)
    check.add_argument(
        "--source", type=Path,
        help="A YAML file with the entry's source, when it is not in sources.yaml yet.",
    )  # fmt: skip
    check.add_argument("--registry", type=Path, help="The registry directory (default: found).")
    args = parser.parse_args(argv)
    root = args.registry or registry_dir()
    try:
        entry = Entry.model_validate(yaml.safe_load(args.entry.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        print(f"{args.entry}: not a valid entry:\n{exc}", file=sys.stderr)
        return 1
    sources = load_sources(root)
    if args.source is not None:
        sources.update(yaml.safe_load(args.source.read_text(encoding="utf-8")) or {})
    found = problems(entry, sources, root.parent)
    generic = yaml.safe_load((root.parent / "profiles/generic_dc.yaml").read_text("utf-8"))
    uses = [u for u in generic["modules"] if u["id"] == entry.module]
    if not uses:
        found.append(f"the generic facility has no {entry.module} to try the entry on")
    for use in uses:
        use["params"] = {k: p.model_dump(exclude_none=True) for k, p in entry.params.items()}
    if uses:
        try:
            build_plant(parse_profile(generic), Kernel(seed=1), ModuleRegistry.from_entry_points())
        except (WiringError, ValueError) as exc:
            found.append(f"{entry.module} does not take these values: {exc}")
    expected = root / entry.module / f"{entry.id}.yaml"
    for problem in found:
        print(f"  {problem}", file=sys.stderr)
    verdict = "can enter the registry" if not found else "cannot enter the registry yet"
    print(f"{entry.id} ({entry.maker} {entry.model}, {entry.tier}): {verdict}; file: {expected}")
    return 1 if found else 0
