"""The MMS client drives its own association (ADR 0017, addendum of 2026-11-17).

With the library's own thread, an association that was made could be left
marked "connecting", and its first request was answered "connection-lost".
That needed a loaded machine, so the first test guards against it and does
not reproduce it on demand; the addendum says how it was reproduced.
"""

import socket
import threading
from typing import Any

import pytest


def drivers() -> list[str]:
    return [thread.name for thread in threading.enumerate() if thread.name.startswith("mms-")]


def test_every_new_association_answers_its_first_request(relay_site: Any) -> None:
    from agentic_datacenter_iec61850.client import MmsClient

    port = relay_site.ports["IED-BUS"]
    for _ in range(40):
        with MmsClient("127.0.0.1", port) as client:
            assert drivers() == [f"mms-{port}"]
            assert client.read("IED_BUSLD0/LLN0.Beh.stVal", "ST") == 1
    assert drivers() == [], "a closed client leaves no thread"


def test_no_association_where_nobody_listens(relay_site: Any) -> None:
    from agentic_datacenter_iec61850.client import MmsClient

    del relay_site  # only for its skip where the library is absent
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(ConnectionError, match="connection-rejected"):
        MmsClient("127.0.0.1", port)
    assert drivers() == []
