"""Draw the Track D secret from a public randomness beacon, at a round fixed in advance.

The held-out variants of Track D are only held out if nobody who writes a gate
or the contracts knows the secret before the gate is fixed. This tool takes
the secret from the drand "quicknet" beacon, run by independent organizations:
a round is chosen and published before it is emitted, so no one, the authors
of Agentic-Datacenter included, can know the secret until then, and afterwards anyone can
fetch the same round and check it.

    python tools/heldout_beacon.py round-at 2026-12-15T12:00:00Z
    python tools/heldout_beacon.py secret --round 27452345 --out build/heldout.secret
    agentic-datacenter bench run ... --heldout-secret-file build/heldout.secret

The round is read from two relays, which must agree, and the randomness is
checked against the signature it is derived from (randomness = SHA-256 of the
signature). The BLS signature itself is not verified here; any drand client
can verify it against the chain's public key.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from agentic_datacenter.scenarios.heldout import commitment

#: drand quicknet: unchained BLS on G1, a round every 3 s.
CHAIN = "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971"
GENESIS = 1692803367
PERIOD = 3
RELAYS = ("https://api.drand.sh", "https://drand.cloudflare.com")

Fetch = Callable[[str], dict[str, Any]]


class BeaconError(RuntimeError):
    """The round could not be established."""


def round_at(unix_s: int) -> int:
    """Return the first round emitted at or after *unix_s*."""
    if unix_s <= GENESIS:
        return 1
    return -(-(unix_s - GENESIS) // PERIOD) + 1


def emitted_at(round_number: int) -> int:
    """Return the Unix time at which *round_number* is emitted."""
    return GENESIS + (round_number - 1) * PERIOD


def _fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "agentic-datacenter-heldout-beacon/1"}
    )
    with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - fixed https relays
        answer: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        return answer


def secret_for(round_number: int, fetch: Fetch = _fetch) -> str:
    """Return the Track D secret of *round_number*, the same for everyone who asks.

    A round not yet emitted is refused by the relays; nothing here reads a clock.
    """
    seen = []
    for relay in RELAYS:
        beacon = fetch(f"{relay}/{CHAIN}/public/{round_number}")
        if beacon.get("round") != round_number:
            raise BeaconError(f"{relay} answered for round {beacon.get('round')}")
        signature, randomness = str(beacon["signature"]), str(beacon["randomness"])
        if hashlib.sha256(bytes.fromhex(signature)).hexdigest() != randomness:
            raise BeaconError(f"{relay}: randomness is not derived from its signature")
        seen.append(randomness)
    if len(set(seen)) != 1:
        raise BeaconError("the relays disagree on the round")
    return f"drand-quicknet:{CHAIN}:{round_number}:{seen[0]}"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    actions = parser.add_subparsers(dest="action", required=True)
    at = actions.add_parser("round-at", help="The round emitted at an ISO 8601 time.")
    at.add_argument("when")
    draw = actions.add_parser("secret", help="Write the secret of an emitted round.")
    draw.add_argument("--round", type=int, required=True)
    draw.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.action == "round-at":
        when = datetime.fromisoformat(args.when.replace("Z", "+00:00"))
        number = round_at(int(when.timestamp()))
        emitted = datetime.fromtimestamp(emitted_at(number)).astimezone().isoformat()
        print(f"round {number}, emitted at {emitted}")
        return 0
    try:
        secret = secret_for(args.round)
    except (BeaconError, OSError, ValueError, KeyError) as error:
        print(f"heldout_beacon: {error}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(secret + "\n", encoding="utf-8")
    print(f"secret of round {args.round} written to {args.out}; commitment {commitment(secret)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
