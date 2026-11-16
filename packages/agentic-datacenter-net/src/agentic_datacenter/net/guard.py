"""The address guard: Agentic Datacenter talks only to itself.

Agentic Datacenter is a simulation and must never be mistaken for, or connected to, real
equipment. Every protocol server asks :func:`check_bind` before it binds, and
every protocol client asks :func:`check_connect` before it connects.

An address is internal when it is loopback, or lies inside a network the
deployment declared as container-internal. Such a declaration is itself
checked: only private address ranges can be declared internal.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence

type _Address = ipaddress.IPv4Address | ipaddress.IPv6Address
type _Network = ipaddress.IPv4Network | ipaddress.IPv6Network

#: The only ranges a deployment may declare as container-internal.
_PRIVATE: tuple[_Network, ...] = tuple(
    ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)


class ExternalAddressError(RuntimeError):
    """An address outside the simulator's own networks was about to be used."""


def _literal(host: str) -> _Address:
    if host == "localhost":
        return ipaddress.ip_address("127.0.0.1")
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        raise ExternalAddressError(
            f"{host!r} is not a literal IP address; names are not resolved, "
            "because where a name points can change"
        ) from None


def check_internal_networks(networks: Sequence[str]) -> tuple[_Network, ...]:
    """Validate the networks a deployment declares as container-internal.

    Raises:
        ExternalAddressError: If an entry is malformed or is not inside a
            private address range.
    """
    parsed = []
    for text in networks:
        try:
            network = ipaddress.ip_network(text)
        except ValueError:
            raise ExternalAddressError(f"{text!r} is not a valid internal network") from None
        if not any(
            network.version == private.version and network.subnet_of(private)  # type: ignore[arg-type]
            for private in _PRIVATE
        ):
            raise ExternalAddressError(
                f"{text} cannot be declared an internal network: it is not a private range"
            )
        parsed.append(network)
    return tuple(parsed)


def _is_internal(address: _Address, networks: tuple[_Network, ...]) -> bool:
    return address.is_loopback or any(
        address.version == network.version and address in network for network in networks
    )


def check_bind(
    host: str, *, allow_external: bool = False, internal_networks: Sequence[str] = ()
) -> None:
    """Refuse a server bind outside loopback and the declared internal networks.

    Args:
        host: Literal address to bind, or ``localhost``.
        allow_external: The ``--allow-external-bind`` override (ADC-SAF-001).
        internal_networks: Container-internal networks declared by the deployment.

    Raises:
        ExternalAddressError: If the bind is refused.
    """
    address = _literal(host)
    networks = check_internal_networks(internal_networks)
    if allow_external or _is_internal(address, networks):
        return
    reason = (
        "it is the wildcard address and would listen on every interface"
        if address.is_unspecified
        else "it is neither loopback nor inside a declared internal network"
    )
    raise ExternalAddressError(
        f"refusing to bind {host}: {reason}. Agentic Datacenter is simulation-only; "
        "pass --allow-external-bind only if you are sure nothing real can reach it"
    )


def check_connect(host: str, *, internal_networks: Sequence[str] = ()) -> None:
    """Refuse an outbound connection outside the simulator's own networks.

    There is no override: Agentic Datacenter never connects to real equipment (ADC-SAF-002).

    Raises:
        ExternalAddressError: If the destination is not internal.
    """
    address = _literal(host)
    if not _is_internal(address, check_internal_networks(internal_networks)):
        raise ExternalAddressError(
            f"refusing to connect to {host}: it is outside the simulator's own networks"
        )
