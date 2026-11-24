"""What of the contract and scenario libraries fits a facility (ADR 0033, decisions 4 and 5).

On a facility of its owner's, the libraries written for the generic facility do
not all apply. A contract that writes a tag the facility does not have, or
whose premises name a kind of equipment it has none of, is not loaded. A
scenario that names an instance, a key, a zone, a relay, a tag or a contract
the facility lacks is not run. Each is listed with the first thing it lacks,
so nothing is skipped silently.

The checks read the facility as built: its instances, points, zones and relays.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.governance.premises import ALIASES
from agentic_datacenter.net.zones import zone_instances
from agentic_datacenter.scenarios.plant import BuiltinPlant
from agentic_datacenter.scenarios.scenario import Event, Scenario, load_scenario
from agentic_datacenter.supervisory.points import PointDatabase

_REF = re.compile(r"([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)?)\[([^\]\[{}]+)\]")
_ALIAS = re.compile(r"\b([a-z_]+)(?:\[([^\]]+)\])?\.[a-z_]")
#: Event parameters that name a key of a key set.
_KEY_PARAMS = {"train": "trains", "pod": "pods"}
#: Event parameters that count units of a module, with the module parameter that
#: holds their number and its default.
_UNIT_PARAMS = {
    ("cooling.chw_plant", "chiller"): ("chillers", 3),
    ("cooling.pump_station", "pump"): ("pumps", 3),
    ("cooling.pod", "unit"): ("ahu_count", 4),
}


@dataclass(frozen=True)
class FacilityView:
    """What a facility has, read from it as built."""

    instances: frozenset[str]
    modules: frozenset[str]
    params: Mapping[str, Mapping[str, Any]]
    key_sets: Mapping[str, tuple[str, ...]]
    tags: frozenset[str]
    zones: frozenset[str]
    relays: frozenset[str]
    points: PointDatabase = field(repr=False)

    @classmethod
    def build(cls, profile: Profile, registry: ModuleRegistry | None = None) -> FacilityView:
        """Build the plant of *profile* and read what it has."""
        kernel = Kernel(seed=0)
        model = BuiltinPlant(profile, kernel, registry)
        points = PointDatabase(kernel, model.modules)
        specs = profile.instances()
        return cls(
            instances=frozenset(spec.name for spec in specs),
            modules=frozenset(spec.module_id for spec in specs),
            params={spec.name: dict(spec.params) for spec in specs},
            key_sets={k: tuple(v) for k, v in profile.key_sets.items()},
            tags=frozenset(points.tags()),
            zones=frozenset(zone_instances(model.modules)),
            relays=frozenset(model.describe().relays),
            points=points,
        )


@dataclass(frozen=True)
class Fit:
    """The contracts that load on a facility and the scenarios that run on it."""

    contracts: ContractLibrary
    not_loaded: dict[str, str]
    runnable: list[str]
    not_run: dict[str, str]

    def block(self) -> dict[str, Any]:
        """The part of a card's ``facility`` block that says what did not fit."""
        return {
            "contracts_loaded": self.contracts.ids(),
            "contracts_not_loaded": dict(sorted(self.not_loaded.items())),
            "scenarios_run": list(self.runnable),
            "scenarios_not_run": dict(sorted(self.not_run.items())),
        }


def contract_problem(view: FacilityView, library: ContractLibrary, contract_id: str) -> str | None:
    """Return why one contract does not fit *view*, or ``None`` when it does."""
    problem = library.problem(contract_id, view.points, dict(view.key_sets))
    if problem is not None:
        return problem
    contract = library.get(contract_id)
    assert contract is not None
    for premise in contract.premises:
        for alias, instance in _ALIAS.findall(premise.expr):
            module_id = ALIASES.get(alias)
            if module_id is None:
                continue
            if module_id not in view.modules:
                return f"a premise names {alias}, and the facility has no {module_id}"
            if instance and "{" not in instance and f"{module_id}[{instance}]" not in view.instances:
                return f"a premise names {module_id}[{instance}], which the facility lacks"
    return None


def _strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _strings(item)


def _event_need(event: Event, view: FacilityView, loaded: set[str]) -> str | None:
    data = event.model_dump(exclude_none=True)
    for text in _strings(data):
        for module_id, instance in _REF.findall(text):
            if module_id in view.modules or module_id in ALIASES.values():
                if f"{module_id}[{instance}]" not in view.instances:
                    return f"{module_id}[{instance}]"
    if event.module is not None:
        module_id = event.module.split("[", 1)[0]
        for name, value in event.params.items():
            key_set = _KEY_PARAMS.get(name)
            if key_set is not None and str(value) not in view.key_sets.get(key_set, ()):
                return f"{key_set} key {value}"
            match = re.fullmatch(r"feeder\[([^\]]+)\]", str(value))
            if match and match.group(1) not in view.key_sets.get("trains", ()):
                return f"trains key {match.group(1)}"
            units = _UNIT_PARAMS.get((module_id, name))
            if units is not None:
                param, default = units
                count = view.params.get(event.module, {}).get(param, default)
                if not isinstance(value, int) or not 1 <= value <= int(str(count)):
                    return f"{name} {value} of {event.module}, which has {count}"
    if event.operator_write is not None:
        tag = str(event.operator_write.get("tag", ""))
        if tag not in view.tags:
            return f"the point {tag}"
    if event.attempt is not None:
        for key in ("source_zone", "destination_zone"):
            zone = event.attempt.get(key)
            if zone is not None and zone not in view.zones:
                return f"the zone {zone}"
        host = event.attempt.get("destination_host", "")
        if host.startswith("IED-") and host not in view.relays:
            return f"the relay {host}"
    if event.relay_request is not None:
        relay = event.relay_request.get("relay", "")
        if relay and relay not in view.relays:
            return f"the relay {relay}"
    if event.authority is not None and isinstance(event.authority.contracts, list):
        for contract_id in event.authority.contracts:
            if contract_id not in loaded:
                return f"the contract {contract_id}"
    return None


def scenario_need(scenario: Scenario, view: FacilityView, loaded: set[str]) -> str | None:
    """Return the first thing *scenario* needs that the facility lacks, or ``None``."""
    for contract_id in scenario.planned_work:
        if contract_id not in loaded:
            return f"the contract {contract_id}"
    for event in scenario.timeline:
        need = _event_need(event, view, loaded)
        if need is not None:
            return need
    return None


def fit_facility(
    profile: Profile,
    library: ContractLibrary,
    scenario_ids: Sequence[str],
    registry: ModuleRegistry | None = None,
) -> Fit:
    """Return what of *library* and of the scenarios *scenario_ids* fits *profile*."""
    view = FacilityView.build(profile, registry)
    not_loaded: dict[str, str] = {}
    for contract_id in library.ids():
        problem = contract_problem(view, library, contract_id)
        if problem is not None:
            not_loaded[contract_id] = problem
    contracts = library.subset([c for c in library.ids() if c not in not_loaded])
    loaded = set(contracts.ids())
    runnable: list[str] = []
    not_run: dict[str, str] = {}
    for scenario_id in scenario_ids:
        need = scenario_need(load_scenario(scenario_id), view, loaded)
        if need is None:
            runnable.append(scenario_id)
        else:
            not_run[scenario_id] = f"needs {need}"
    return Fit(contracts, not_loaded, runnable, not_run)
