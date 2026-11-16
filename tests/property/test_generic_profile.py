"""ADC-KRN-001 and -002 on the generic profile (Stage 1 exit: 100 seeds)."""

from pathlib import Path

import pytest

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles/generic_dc.yaml")
REGISTRY = ModuleRegistry.from_entry_points()


def run(seed: int, steps: int) -> list[str]:
    kernel = Kernel(seed=seed)
    build_plant(PROFILE, kernel, REGISTRY)
    out = []
    for _ in range(steps):
        kernel.step()
        out.append(kernel.state_hash())
    return out


@pytest.mark.req("ADC-KRN-001")
@pytest.mark.parametrize("seed", range(100))
def test_generic_profile_is_deterministic(seed: int) -> None:
    assert run(seed, 25) == run(seed, 25)


@pytest.mark.req("ADC-KRN-002")
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_generic_profile_restores_and_continues_identically(seed: int) -> None:
    kernel = Kernel(seed=seed)
    build_plant(PROFILE, kernel, REGISTRY)
    kernel.run(15)
    saved = kernel.snapshot()
    expected = [(kernel.step(), kernel.state_hash())[1] for _ in range(15)]
    fresh = Kernel(seed=seed + 1000)
    build_plant(PROFILE, fresh, REGISTRY)
    fresh.restore(saved)
    assert [(fresh.step(), fresh.state_hash())[1] for _ in range(15)] == expected


@pytest.mark.req("ADC-PRC-001")
def test_power_drawn_by_the_it_load_reaches_the_utility() -> None:
    """Steady state: IT load, UPS losses and chiller input all arrive at the incomers."""
    kernel = Kernel(seed=1)
    plant = build_plant(PROFILE, kernel, REGISTRY)
    kernel.run(100)
    it_kw = sum(
        d.kw
        for n in range(1, 17)
        for d in plant.module("electrical.it_load", f"{n:02d}").reverse_outputs().values()
    )
    swg = plant.module("electrical.mv_switchgear", "SWG-MV").reverse_outputs()
    utility_kw = sum(d.kw for d in swg.values())
    assert it_kw == pytest.approx(2400.0)
    trains = sum(plant.module("electrical.power_train", t).io["bus_kw"] for t in ("A", "B", "C"))
    # Everything the three switchboards draw arrives at the incomers, and nothing else does.
    assert utility_kw == pytest.approx(trains, rel=1e-9)
    assert utility_kw > 2400.0 / 0.96


EVENTS = [
    ("electrical.utility", "INC-1", "loss", {}),
    ("electrical.utility", "INC-2", "loss", {}),
    ("electrical.utility", "INC-1", "restore", {}),
    ("electrical.utility", "INC-2", "restore", {}),
    ("electrical.utility", "INC-1", "set", {"voltage_pu": 0.85}),
    ("electrical.genset", "B", "start_failure", {}),
    ("electrical.genset", "A", "trip", {}),
    ("electrical.genset", "A", "reset", {}),
    ("electrical.ups", "C", "fault", {}),
    ("electrical.ups", "C", "reset", {}),
    ("electrical.power_train", "A", "util_brk_trip", {"kind": "other"}),
    ("electrical.power_train", "A", "reset", {}),
    ("electrical.power_train", "B", "gen_brk_fail_close", {}),
    ("electrical.it_load", "07", "set_load", {"fraction": 0.4}),
]


@pytest.mark.req("ADC-PRC-001")
@pytest.mark.parametrize("seed", range(8))
def test_real_power_balances_in_every_electrical_module_at_every_step(seed: int) -> None:
    """Whatever happens, no module creates or loses power: in = out + losses + stored."""
    kernel = Kernel(seed=seed)
    plant = build_plant(PROFILE, kernel, REGISTRY)
    order = kernel.rng.stream("test.events")
    balanced = [
        plant.module(i.module_id, i.instance)
        for i in PROFILE.instances()
        if hasattr(plant.module(i.module_id, i.instance), "power_balance")
    ]
    assert len(balanced) >= 22
    for _ in range(12):
        module_id, instance, fault, params = EVENTS[order.randrange(len(EVENTS))]
        plant.module(module_id, instance).inject(fault, **params)
        for _ in range(order.randrange(20, 400)):
            kernel.step()
            for module in balanced:
                b = module.power_balance()
                residual = b["in_kw"] - b["out_kw"] - b["loss_kw"] - b["stored_kw"]
                scale = max(b["in_kw"], b["out_kw"], 1.0)
                assert abs(residual) <= 1e-3 * scale, (module.ctx.name, kernel.clock.now_ms, b)


@pytest.mark.req("ADC-KRN-001")
def test_skipping_quiescent_modules_gives_the_run_of_stepping_every_module() -> None:
    """The optimization is invisible: same port values, step for step."""
    from agentic_datacenter.core.registry import ModuleRegistry as Registry

    restless = Registry()
    for entry in REGISTRY.entries():
        awake = type("Awake", (entry.factory,), {"quiescent": lambda self: False})
        restless.register(entry.manifest, awake, awake)

    def ports(registry: Registry) -> list[object]:
        kernel = Kernel(seed=4)
        plant = build_plant(PROFILE, kernel, registry)
        out = []
        for _ in range(40):
            kernel.step()
            out.append(plant.port_values())
        return out

    assert ports(REGISTRY) == ports(restless)


@pytest.mark.req("ADC-KRN-004")
def test_letting_settled_modules_rest_does_not_change_what_the_plant_reports() -> None:
    """Three simulated hours with a trip in the middle, with and without skipping."""
    from agentic_datacenter.core.registry import ModuleRegistry as Registry

    restless = Registry()
    for entry in REGISTRY.entries():
        awake = type(
            "Awake",
            (entry.factory,),
            {"quiescent": lambda self: False, "settled": lambda self: False},
        )
        restless.register(entry.manifest, awake, awake)

    def report(registry: Registry) -> list[dict[str, object]]:
        kernel = Kernel(seed=4)
        plant = build_plant(PROFILE, kernel, registry)
        out = []
        for minute in range(180):
            if minute == 90:
                plant.module("cooling.chw_plant", "CHW").inject("chiller_trip", chiller=1)
            kernel.run_for(60_000)
            values = plant.port_values()
            out.append(
                {
                    port: {k: round(v, 3) if isinstance(v, float) else v for k, v in value.items()}
                    for direction in values.values()
                    for port, value in direction.items()
                }
            )
        return out

    resting, awake_all = report(REGISTRY), report(restless)
    assert resting == awake_all
