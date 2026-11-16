"""ADC-SAF-001: no protocol server binds where real equipment could reach it."""

import pytest

from agentic_datacenter.net.guard import ExternalAddressError, check_bind, check_internal_networks

DOCKER = ("172.28.0.0/16",)


@pytest.mark.req("ADC-SAF-001")
@pytest.mark.parametrize("host", ["127.0.0.1", "127.8.9.10", "::1", "localhost"])
def test_loopback_is_allowed(host: str) -> None:
    check_bind(host)


@pytest.mark.req("ADC-SAF-001")
@pytest.mark.parametrize(
    "host", ["0.0.0.0", "::", "192.168.1.20", "10.0.0.5", "172.28.0.5", "8.8.8.8", "fe80::1"]
)
def test_anything_else_is_refused_by_default(host: str) -> None:
    with pytest.raises(ExternalAddressError, match="--allow-external-bind"):
        check_bind(host)


@pytest.mark.req("ADC-SAF-001")
def test_address_inside_a_declared_container_network_is_allowed() -> None:
    check_bind("172.28.0.5", internal_networks=DOCKER)


@pytest.mark.req("ADC-SAF-001")
def test_address_outside_the_declared_container_network_is_refused() -> None:
    with pytest.raises(ExternalAddressError):
        check_bind("172.29.0.5", internal_networks=DOCKER)


@pytest.mark.req("ADC-SAF-001")
def test_wildcard_is_refused_even_with_a_container_network() -> None:
    with pytest.raises(ExternalAddressError, match="every interface"):
        check_bind("0.0.0.0", internal_networks=DOCKER)


@pytest.mark.req("ADC-SAF-001")
@pytest.mark.parametrize(
    "host", ["plc.example.com", "agentic-datacenter", "", "127.0.0.1:502", "256.1.1.1"]
)
def test_name_that_is_not_a_literal_address_is_refused(host: str) -> None:
    with pytest.raises(ExternalAddressError, match="literal"):
        check_bind(host)


@pytest.mark.req("ADC-SAF-001")
@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "8.8.8.8"])
def test_explicit_override_allows_an_external_bind(host: str) -> None:
    check_bind(host, allow_external=True)


@pytest.mark.req("ADC-SAF-001")
def test_override_does_not_excuse_a_malformed_address() -> None:
    with pytest.raises(ExternalAddressError, match="literal"):
        check_bind("plc.example.com", allow_external=True)


@pytest.mark.req("ADC-SAF-001")
@pytest.mark.parametrize("network", ["8.8.8.0/24", "0.0.0.0/0", "100.64.0.0/10", "not-a-network"])
def test_public_or_malformed_range_cannot_be_declared_internal(network: str) -> None:
    with pytest.raises(ExternalAddressError, match="internal network"):
        check_internal_networks((network,))


@pytest.mark.req("ADC-SAF-001")
@pytest.mark.parametrize(
    "network", ["172.28.0.0/16", "10.20.0.0/24", "192.168.50.0/24", "fd00:dc::/64"]
)
def test_private_range_can_be_declared_internal(network: str) -> None:
    check_internal_networks((network,))
