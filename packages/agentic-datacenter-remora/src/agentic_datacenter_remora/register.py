"""REMORA's capability register, as the pinned package carries it (ADC-PIN-006).

REMORA records how far each of its mechanisms is wired in
``docs/assurance/capability_register_v1.yaml``. That file is not in the wheel.
The wheel carries ``remora/governance/capability_catalogue_v1.json``, which
REMORA builds from the register (id, name, status and hook of every
capability) and holds to it with a test of its own. This module reads that
file from the installed distribution, as data, after checking that the
installed commit is the pinned one. It imports nothing from REMORA.

Nothing here knows a maturity word. Whoever credits REMORA with a capability
names it by its id and takes the word from :meth:`CapabilityRegister.maturity`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import distribution
from pathlib import Path

from agentic_datacenter_remora.binding import check_pin

#: Where the installed REMORA keeps the packaged register, relative to its install root.
CATALOGUE = "remora/governance/capability_catalogue_v1.json"


class RegisterError(RuntimeError):
    """The capability register cannot be read, or does not list a capability."""


@dataclass(frozen=True)
class Capability:
    """One entry of the register: REMORA's own id, name and maturity word."""

    id: str
    name: str
    status: str


@dataclass(frozen=True)
class CapabilityRegister:
    """The register of one REMORA commit."""

    #: The REMORA commit the register was read at: the pinned, installed one.
    commit: str
    #: The file in the installed package the entries were read from.
    file: str
    #: The file in REMORA's repository that REMORA says it built that file from.
    source: str
    #: SHA-256 of the file read.
    sha256: str
    capabilities: Mapping[str, Capability]

    def capability(self, capability_id: str) -> Capability:
        """Return the entry of *capability_id*.

        Raises:
            RegisterError: If the register does not list it. No word is made up for it.
        """
        try:
            return self.capabilities[capability_id]
        except KeyError:
            raise RegisterError(
                f"REMORA's capability register at {self.commit} does not list {capability_id}"
            ) from None

    def maturity(self, capability_id: str) -> str:
        """Return the maturity word the register records for *capability_id*, unchanged."""
        return self.capability(capability_id).status


def capability_register(pin_file: Path) -> CapabilityRegister:
    """Read the capability register from the installed REMORA.

    Raises:
        PinMismatchError: If the installed REMORA is not the commit in *pin_file*.
        RegisterError: If the installed package does not carry a readable register.
    """
    commit = check_pin(pin_file)
    path = Path(str(distribution("remora-assurance").locate_file(CATALOGUE)))
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
        entries = {
            str(entry["id"]): Capability(str(entry["id"]), str(entry["name"]), str(entry["status"]))
            for entry in data["capabilities"]
        }
        source = str(data["source"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RegisterError(f"{CATALOGUE} of the installed REMORA cannot be read: {exc}") from exc
    return CapabilityRegister(commit, CATALOGUE, source, hashlib.sha256(raw).hexdigest(), entries)
