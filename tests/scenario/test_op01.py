"""OP-01: utility loss on train A, clean return after 20 minutes (Stage 2 exit criterion).

Run on local control alone: no supervisory layer exists. Expected (SDD 10.1):
full transfer and retransfer per 7.2, UPS-A bridges, no POD loses power.
"""

from pathlib import Path

import pytest

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel

REPO = Path(__file__).resolve().parents[2]
PODS = [f"{n:02d}" for n in range(1, 17)]


@pytest.mark.req("ADC-CTL-001")
@pytest.mark.req("ADC-CTL-002")
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_op01_utility_loss_on_train_a_with_clean_return(seed: int) -> None:
    kernel = Kernel(seed=seed)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    train = plant.module("electrical.power_train", "A")
    ups = plant.module("electrical.ups", "A")
    genset = plant.module("electrical.genset", "A")
    switchboard = plant.module("electrical.mv_switchgear", "SWG-MV")
    loads = [plant.module("electrical.it_load", pod) for pod in PODS]
    states: list[str] = []
    kernel.events.subscribe(
        "ato.state",
        lambda e: (
            states.append(str(e.payload["state"]))
            if e.payload["source"] == "electrical.power_train[A]"
            else None
        ),
    )
    seen = {
        "both_closed": False,
        "dropped": False,
        "min_soc": 100.0,
        "on_battery": False,
        "other_trains_moved": False,
    }

    def watch(seconds: float) -> None:
        for _ in range(round(seconds * 10)):
            kernel.step()
            seen["both_closed"] |= bool(train.io["util_brk_closed"] and train.io["gen_brk_closed"])
            seen["dropped"] |= any(load.io["dropped"] for load in loads)
            seen["min_soc"] = min(seen["min_soc"], float(ups.io["soc_pct"]))
            seen["on_battery"] |= ups.io["mode"] == "ON_BATTERY"
            for other in ("B", "C"):
                state = plant.module("electrical.power_train", other).io["state"]
                seen["other_trains_moved"] |= state != "ON_UTILITY"

    watch(60)
    assert train.io["state"] == "ON_UTILITY" and ups.io["mode"] == "ONLINE"

    switchboard.inject("manual_open", breaker="feeder[A]")
    watch(40)
    assert train.io["state"] == "ON_GENERATOR"
    assert genset.io["state"] == "LOADED"
    assert seen["on_battery"], "UPS-A carried its load across the gap"
    assert seen["min_soc"] > 90.0, "about 18 s of a 300 s battery"
    assert ups.io["mode"] == "ONLINE", "back on its input, now from the generator"

    watch(20 * 60 - 40)
    assert train.io["state"] == "ON_GENERATOR"
    assert float(ups.io["soc_pct"]) == 100.0, "recharged from the generator"

    switchboard.inject("manual_close", breaker="feeder[A]")
    watch(45)
    assert train.io["state"] == "ON_UTILITY"
    assert genset.io["state"] == "COOLDOWN", "running unloaded for TDEC"
    watch(300)
    assert genset.io["state"] == "STOPPED"

    assert states == [
        "START_DELAY", "WAIT_GENERATOR", "PRE_TRANSFER", "OPENING_UTILITY",
        "NEUTRAL_TO_GENERATOR", "CLOSING_GENERATOR", "ON_GENERATOR",
        "RETURN_DELAY", "OPENING_GENERATOR", "NEUTRAL_TO_UTILITY", "CLOSING_UTILITY",
        "ON_UTILITY",
    ]  # fmt: skip
    assert not seen["both_closed"], "INV-ATO-1"
    assert not seen["dropped"], "no POD lost power"
    assert all(load.io["kwh_lost"] == 0.0 for load in loads)
    assert not seen["other_trains_moved"], "trains B and C never left the utility"
    assert train.io["transfers"] == 1
