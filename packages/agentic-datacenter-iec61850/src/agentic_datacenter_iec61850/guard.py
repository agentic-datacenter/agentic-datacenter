"""Loopback only: the relays never listen where real equipment could reach them.

``agentic_datacenter.net.guard`` holds the rule for the other protocol servers. This
package may not import ``agentic_datacenter.net`` (SDD section 5), so the part of the rule
it needs is repeated here: a literal loopback address, or an explicit override
for a server inside a container network. A client has no override.
"""

from __future__ import annotations

import ipaddress


class ExternalAddressError(RuntimeError):
    """An address outside the simulator's own machine was about to be used."""


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_bind(host: str, *, allow_external: bool = False) -> None:
    """Refuse a server bind outside loopback unless *allow_external* is set (ADC-SAF-001).

    Raises:
        ExternalAddressError: If the bind is refused.
    """
    if not (allow_external or _loopback(host)):
        raise ExternalAddressError(
            f"refusing to bind {host}: it is not loopback. Agentic Datacenter is simulation-only; "
            "allow an external bind only if you are sure nothing real can reach it"
        )


def check_connect(host: str) -> None:
    """Refuse a client connection outside loopback; there is no override (ADC-SAF-002).

    Raises:
        ExternalAddressError: If the destination is not loopback.
    """
    if not _loopback(host):
        raise ExternalAddressError(f"refusing to connect to {host}: it is not loopback")
