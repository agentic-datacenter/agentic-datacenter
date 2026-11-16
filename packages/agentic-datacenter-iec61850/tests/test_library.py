"""The binding to the protocol library, the view, and the loopback rule (ADR 0017)."""

from pathlib import Path

import pytest

# The optional package is absent in most jobs (ADC-IEC-005).
pytest.importorskip("agentic_datacenter_iec61850")

from agentic_datacenter.core.profile import build_plant, load_profile  # noqa: E402
from agentic_datacenter.core.registry import ModuleRegistry  # noqa: E402
from agentic_datacenter.core.scheduler import Kernel  # noqa: E402
from agentic_datacenter.supervisory.points import PointDatabase  # noqa: E402
from agentic_datacenter_iec61850 import library  # noqa: E402
from agentic_datacenter_iec61850.guard import ExternalAddressError, check_bind, check_connect  # noqa: E402
from agentic_datacenter_iec61850.model import EPOCH_MS  # noqa: E402
from agentic_datacenter_iec61850.view import RelayView, convert  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
needs_library = pytest.mark.skipif(
    not library.available(), reason="libiec61850 is not available on this platform (ADR 0017)"
)


def test_a_missing_library_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    library.load.cache_clear()
    monkeypatch.setenv(library.OVERRIDE, "/nonexistent/libiec61850.so")
    try:
        assert not library.available()
        with pytest.raises(library.LibraryUnavailableError):
            library.load()
    finally:
        library.load.cache_clear()


@needs_library
def test_the_library_is_the_version_the_binding_was_written_against() -> None:
    assert library.version() == library.VERSION == "1.6.1"


@needs_library
def test_every_constant_equals_the_one_in_the_installed_wheel() -> None:
    swig = pytest.importorskip("pyiec61850.pyiec61850")
    assert len(library.CONSTANTS) > 80
    for name, number in library.CONSTANTS.items():
        assert getattr(swig, name) == number, name


@pytest.mark.req("ADC-SAF-001")
def test_only_loopback_is_bound_without_the_override() -> None:
    for host in ("127.0.0.1", "::1", "localhost"):
        check_bind(host)
        check_connect(host)
    for host in ("0.0.0.0", "10.0.0.5", "192.168.1.20", "relay.example.com"):
        with pytest.raises(ExternalAddressError):
            check_bind(host)
        with pytest.raises(ExternalAddressError):
            check_connect(host)
    check_bind("172.28.0.9", allow_external=True)


def test_conversions_from_point_values() -> None:
    assert convert(True, "dbpos") is True and convert(2.0, "ms") == 2000
    assert convert("PTOC", "equals:PTOC") is True and convert("PIOC", "equals:PTOC") is False
    assert convert("NONE", "differs:NONE") is False and convert(3, "float") == 3.0
    with pytest.raises(ValueError):
        convert(1, "nonsense")


@pytest.mark.req("ADC-IEC-002")
def test_the_view_follows_the_point_database_and_stamps_changes_with_simulated_time() -> None:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    points = PointDatabase(kernel, plant)
    kernel.run_for(2000)
    view = RelayView(kernel, points)
    calls: list[int] = []
    view.follow(lambda: calls.append(kernel.clock.now_ms))
    kernel.run_for(300)
    assert calls == [2000, 2100, 2200], "once per step, in the step"
    position = view.samples("IED-FDR-A")["LD0/XCBR1.Pos.stVal"]
    assert position.value is True and position.quality == "good"
    plant.module("electrical.mv_switchgear", "SWG-MV").inject("manual_open", breaker="feeder[A]")
    kernel.run_for(500)
    opened = view.samples("IED-FDR-A")["LD0/XCBR1.Pos.stVal"]
    assert opened.value is False and opened.time_ms == EPOCH_MS + 2300
    assert view.samples("IED-FDR-B")["LD0/XCBR1.Pos.stVal"].time_ms == position.time_ms
    events: list[object] = []
    kernel.events.subscribe("net.device_violation", events.append)
    view.refuse("IED-FDR-A", "control", "LD0/XCBR1.Pos", "127.0.0.1:5", "status-only")
    assert len(events) == 1 and view.violations()[0]["client"] == "127.0.0.1:5"
