"""Shared fixture: the hand-driven module rig."""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_spec = importlib.util.spec_from_file_location("cooling_rig", Path(__file__).parent / "rig.py")
assert _spec and _spec.loader
_rig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rig)


@pytest.fixture(scope="session")
def rig() -> Any:
    """The ModuleRig class."""
    return _rig.ModuleRig
