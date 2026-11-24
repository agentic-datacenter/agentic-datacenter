"""A parameter the module does not read is refused when the instance is built (ADR 0033)."""

from collections.abc import Mapping

import pytest

from agentic_datacenter.core.module import Inputs, ModuleContext, SimModule, parse_manifest
from agentic_datacenter.core.registry import InstanceSpec, ModuleRegistry, WiringError
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue


class Reader(SimModule):
    """Reads ``kw`` by ``get`` and ``limit`` by index when given."""

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        super().__init__(ctx, params)
        self.kw = params.get("kw", 1.0)
        if "limit" in params:
            self.limit = params["limit"]

    def step(self, inputs: Inputs) -> None:
        pass

    def forward_outputs(self) -> Mapping[str, object]:
        return {}

    def snapshot(self) -> JsonValue:
        return {}

    def restore(self, state: JsonValue) -> None:
        pass


class Everything(Reader):
    """Takes any name, as a module that maps parameters onto its points does."""

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        super().__init__(ctx, params)
        self.all = dict(params.items())


class Stub(Reader):
    """Reads nothing."""

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        SimModule.__init__(self, ctx, params)


def registry() -> ModuleRegistry:
    reg = ModuleRegistry()
    for module_id, factory in (("test.reader", Reader), ("test.everything", Everything)):
        manifest = parse_manifest(
            {
                "id": module_id, "version": "0.1.0", "fidelity": "F0", "zone": "Z-TEST",
                "requirements": ["ADC-FAC-004"], "spec": f"docs/design/modules/{module_id}.md",
            }
        )  # fmt: skip
        reg.register(manifest, factory, Stub)
    return reg


def build(module_id: str, params: dict[str, JsonValue], stub: bool = False) -> None:
    registry().build(Kernel(seed=1), [InstanceSpec(module_id, "X", params=params, stub=stub)], [])


@pytest.mark.req("ADC-FAC-004")
def test_parameters_the_module_reads_are_taken() -> None:
    build("test.reader", {"kw": 2.0, "limit": 5.0})


@pytest.mark.req("ADC-FAC-004")
def test_a_parameter_the_module_does_not_read_is_refused_with_what_it_reads() -> None:
    with pytest.raises(WiringError, match=r"test\.reader\[X\].*kwh.*reads.*kw"):
        build("test.reader", {"kwh": 2.0})


@pytest.mark.req("ADC-FAC-004")
def test_a_module_that_reads_every_name_takes_any() -> None:
    build("test.everything", {"anything": 1.0, "else": "x"})


@pytest.mark.req("ADC-FAC-004")
def test_a_stub_is_not_checked() -> None:
    build("test.reader", {"kwh": 2.0}, stub=True)
