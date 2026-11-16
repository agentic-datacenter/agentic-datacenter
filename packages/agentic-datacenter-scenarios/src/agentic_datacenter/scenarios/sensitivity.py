"""Sensitivity of conclusions to the most uncertain assumed parameters (SDD 6.7).

A conclusion is a yes-or-no statement about what happened in a scenario. The
scenario is run once on the profile as it is, and once for each value of each
varied parameter. A conclusion whose answer changes anywhere in that range is
reported as not robust, with the parameter and value that changed it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from agentic_datacenter.core.profile import Profile, build_plant
from agentic_datacenter.core.registry import ModuleRegistry, Plant
from agentic_datacenter.core.scheduler import Kernel

Scenario = Callable[[Kernel, Plant], Mapping[str, bool]]


@dataclass(frozen=True)
class Variation:
    """One uncertain parameter and the values to try for it."""

    name: str
    module_id: str
    param: str
    values: Sequence[float]


@dataclass(frozen=True)
class Flip:
    """A parameter value at which a conclusion differs from the baseline."""

    variation: str
    value: float
    answer: bool


@dataclass(frozen=True)
class ConclusionResult:
    """One conclusion, its answer on the baseline, and whether it held everywhere."""

    conclusion: str
    baseline: bool
    flipped_by: list[Flip] = field(default_factory=list)

    @property
    def robust(self) -> bool:
        """The answer was the same for every value of every varied parameter."""
        return not self.flipped_by


@dataclass(frozen=True)
class SensitivityReport:
    """Every run made and the verdict on each conclusion."""

    runs: list[dict[str, object]]
    conclusions: list[ConclusionResult]

    def to_markdown(self) -> str:
        """Return the report as a table, one row per conclusion."""
        lines = [
            "| Conclusion | Baseline | Verdict | Changed by |",
            "| --- | --- | --- | --- |",
        ]
        for c in self.conclusions:
            changed = "; ".join(f"{f.variation} = {f.value:g}" for f in c.flipped_by) or "-"
            verdict = "robust" if c.robust else "not robust"
            lines.append(
                f"| {c.conclusion} | {'yes' if c.baseline else 'no'} | {verdict} | {changed} |"
            )
        return "\n".join(lines) + "\n"


def run_sensitivity(
    profile: Profile,
    scenario: Scenario,
    variations: Sequence[Variation],
    seed: int,
    registry: ModuleRegistry | None = None,
) -> SensitivityReport:
    """Run *scenario* on the baseline profile and on every variation of it.

    Raises:
        ValueError: If a variation names a module the profile does not have.
    """
    modules = registry or ModuleRegistry.from_entry_points()

    def run(changed: Profile) -> Mapping[str, bool]:
        kernel = Kernel(seed=seed)
        return scenario(kernel, build_plant(changed, kernel, modules))

    variants = [
        (variation, value, profile.with_param(variation.module_id, variation.param, value))
        for variation in variations
        for value in variation.values
    ]
    baseline = run(profile)
    runs: list[dict[str, object]] = [{"variation": "baseline", "value": None, **baseline}]
    flips: dict[str, list[Flip]] = {name: [] for name in baseline}
    for variation, value, changed in variants:
        answers = run(changed)
        runs.append({"variation": variation.name, "value": value, **answers})
        for name, answer in answers.items():
            if answer != baseline[name]:
                flips[name].append(Flip(variation.name, value, answer))
    return SensitivityReport(
        runs=runs,
        conclusions=[ConclusionResult(name, baseline[name], flips[name]) for name in baseline],
    )
