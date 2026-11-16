"""Repository-wide pytest plugin: record which requirement each test verifies.

With ``--req-report=FILE`` the outcome of every test carrying
``@pytest.mark.req("ADC-XXX-NNN")`` is written as JSON, for
``tools/traceability.py`` (ADC-CI-001).
"""

import json
from pathlib import Path

import pytest

_REPORT: dict[str, dict[str, list[str]]] = {}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--req-report", default=None, help="Write the requirement report here.")


def _ids(item: pytest.Item) -> list[str]:
    return [str(mark.args[0]) for mark in item.iter_markers(name="req") if mark.args]


def _record(req_id: str, outcome: str, nodeid: str) -> None:
    _REPORT.setdefault(req_id, {}).setdefault(outcome, []).append(nodeid)


def pytest_deselected(items: list[pytest.Item]) -> None:
    for item in items:
        for req_id in _ids(item):
            _record(req_id, "deselected", item.nodeid)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):  # type: ignore[no-untyped-def]
    outcome = yield
    report = outcome.get_result()
    failed_early = report.when == "setup" and report.outcome != "passed"
    if report.when == "call" or failed_early:
        for req_id in _ids(item):
            _record(req_id, report.outcome, item.nodeid)


def pytest_sessionfinish(session: pytest.Session) -> None:
    path = session.config.getoption("--req-report")
    if path:
        text = json.dumps(_REPORT, indent=2, sort_keys=True) + "\n"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding="utf-8")
