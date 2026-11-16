"""ADC-SAF-002: no industrial-protocol connection leaves the simulator's networks."""

import ast
from pathlib import Path

import pytest

from agentic_datacenter.net.guard import ExternalAddressError, check_connect

REPO = Path(__file__).resolve().parents[3]

# Only these packages may open sockets or use a protocol library at all, and
# they must pass every destination through check_connect.
NETWORK_PACKAGES = {"agentic-datacenter-net", "agentic-datacenter-iec61850"}
PROTOCOL_MODULES = {
    "socket", "socketserver", "pymodbus", "bacpypes3", "asyncua", "pysnmp", "pysnmplib",
    "iec61850", "pyiec61850",
}  # fmt: skip


def protocol_imports(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        found += [n for n in names if n.split(".")[0] in PROTOCOL_MODULES]
    return found


@pytest.mark.req("ADC-SAF-002")
@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_connection_to_loopback_is_allowed(host: str) -> None:
    check_connect(host)


@pytest.mark.req("ADC-SAF-002")
def test_connection_inside_a_declared_container_network_is_allowed() -> None:
    check_connect("172.28.0.9", internal_networks=("172.28.0.0/16",))


@pytest.mark.req("ADC-SAF-002")
@pytest.mark.parametrize("host", ["192.168.1.20", "10.0.0.5", "8.8.8.8", "plc.example.com"])
def test_connection_anywhere_else_is_refused_with_no_override(host: str) -> None:
    with pytest.raises(ExternalAddressError):
        check_connect(host)
    with pytest.raises(TypeError):
        check_connect(host, allow_external=True)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "source", ["import socket", "from pymodbus.client import ModbusTcpClient", "import asyncua"]
)
def test_scan_reports_a_protocol_import(source: str) -> None:
    assert protocol_imports(source)


@pytest.mark.req("ADC-SAF-002")
def test_no_package_outside_the_network_layer_imports_a_socket_or_protocol_library() -> None:
    sources = sorted(REPO.glob("packages/*/src/**/*.py"))
    assert sources
    problems = [
        f"{path.relative_to(REPO)}: {name}"
        for path in sources
        if path.relative_to(REPO).parts[1] not in NETWORK_PACKAGES
        for name in protocol_imports(path.read_text(encoding="utf-8"))
    ]
    assert problems == []
