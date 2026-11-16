"""Track D: held-out variants of the library scenarios (SDD 12.1).

A variant is a library scenario with other numbers: each injected event is
moved in time and each of its real-valued parameters is scaled. Which
numbers is decided by a secret that is not in the repository. The benchmark
records only a commitment to the secret, so a result on Track D can be
checked later, when the secret is shown, without the gate or the contracts
having been written with those numbers in view.

That only holds if whoever writes the gate and the contracts does not know
the secret. In a public-test season it is therefore chosen by no one: it is
the output of a public randomness beacon at a round fixed in advance
(``tools/heldout_beacon.py``, ``docs/bench/PUBLIC_TEST.md``).
"""

from __future__ import annotations

import hashlib

from agentic_datacenter.scenarios.scenario import Scenario, parse_scenario

#: An event moves by at most this share of the scenario's length.
TIME_SHIFT = 0.2
#: A real-valued parameter is scaled by at most this share of itself.
PARAMETER_SCALE = 0.1


def commitment(secret: str) -> str:
    """Return what is published about *secret*: a hash that binds it and does not show it."""
    return hashlib.sha256(f"agentic-datacenter held-out commitment|{secret}".encode()).hexdigest()


def _unit(secret: str, *what: object) -> float:
    """Return a number in [-1, 1) that follows from the secret and what it is for."""
    text = "|".join(["agentic-datacenter held-out", secret, *(str(w) for w in what)])
    return int(hashlib.sha256(text.encode()).hexdigest()[:13], 16) / 16**13 * 2.0 - 1.0


def variants(template: Scenario, secret: str, count: int) -> list[Scenario]:
    """Return *count* held-out variants of *template*, the same for the same secret."""
    out = []
    for number in range(1, count + 1):
        data = template.model_dump(mode="json")
        data["track"] = "D"
        data["title"] = f"{template.title} (held-out variant {number})"
        for index, event in enumerate(data["timeline"]):
            if event.get("inject") is None:
                continue
            shift = _unit(secret, template.id, number, index, "at") * TIME_SHIFT
            moved = round(event["at_s"] + shift * template.duration_s)
            event["at_s"] = min(max(moved, 0), template.duration_s - 1) if event["at_s"] else 0
            for name, value in event["params"].items():
                if isinstance(value, float):
                    scale = _unit(secret, template.id, number, index, name) * PARAMETER_SCALE
                    event["params"][name] = round(value * (1.0 + scale), 3)
        out.append(parse_scenario(data))
    return out
