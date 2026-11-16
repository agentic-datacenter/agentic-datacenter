"""Settings shared by the cross-package tests."""

import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import settings

# SDD 12.4: derandomized on pull requests, randomized nightly.
settings.register_profile("pr", derandomize=True, max_examples=100, deadline=None)
settings.register_profile("nightly", derandomize=False, max_examples=1000, deadline=None)
settings.load_profile(os.environ.get("ADC_HYPOTHESIS_PROFILE", "pr"))


@pytest.fixture(scope="module")
def relay_site() -> Iterator[SimpleNamespace]:
    """The generic facility with its six relays served over MMS on loopback.

    Skipped where the optional package or the protocol library is absent: the
    library has wheels for Linux only (ADR 0017).
    """
    pytest.importorskip("agentic_datacenter_iec61850")
    from agentic_datacenter.core.profile import build_plant, load_profile
    from agentic_datacenter.core.registry import ModuleRegistry
    from agentic_datacenter.core.scheduler import Kernel
    from agentic_datacenter.supervisory.points import PointDatabase
    from agentic_datacenter_iec61850 import library
    from agentic_datacenter_iec61850.server import Iec61850Server
    from agentic_datacenter_iec61850.view import RelayView

    if not library.available():
        pytest.skip("libiec61850 is not available on this platform (ADR 0017)")
    kernel = Kernel(seed=1)
    profile = load_profile(Path(__file__).resolve().parents[1] / "profiles/generic_dc.yaml")
    plant = build_plant(profile, kernel, ModuleRegistry.from_entry_points())
    points = PointDatabase(kernel, plant)
    kernel.run_for(5000)
    view = RelayView(kernel, points)
    servers = {tag: Iec61850Server(view, tag) for tag in view.relays}
    ports = {tag: server.start("127.0.0.1", 0) for tag, server in servers.items()}
    yield SimpleNamespace(kernel=kernel, plant=plant, points=points, view=view, ports=ports)
    for server in servers.values():
        server.stop()
