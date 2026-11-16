"""Canonical encoding, state hash and the registry of state-holding parts."""

import math

import pytest

from agentic_datacenter.core.state import JsonValue, StateRegistry, canonical_bytes, state_hash


class Box:
    """Smallest possible state-holding part."""

    def __init__(self, value: JsonValue) -> None:
        self.value = value

    def snapshot(self) -> JsonValue:
        return {"value": self.value}

    def restore(self, state: JsonValue) -> None:
        assert isinstance(state, dict)
        self.value = state["value"]


def test_hash_is_a_sha256_hex_digest() -> None:
    digest = state_hash({"a": 1})
    assert len(digest) == 64 and int(digest, 16) >= 0


def test_key_order_does_not_change_the_encoding() -> None:
    assert canonical_bytes({"a": 1, "b": 2}) == canonical_bytes({"b": 2, "a": 1})


def test_list_order_changes_the_encoding() -> None:
    assert canonical_bytes([1, 2]) != canonical_bytes([2, 1])


def test_int_float_and_bool_are_distinct() -> None:
    encodings = {canonical_bytes(v) for v in (1, 1.0, True)}
    assert len(encodings) == 3


def test_none_false_zero_and_empty_string_are_distinct() -> None:
    encodings = {canonical_bytes(v) for v in (None, False, 0, "", [], {})}
    assert len(encodings) == 6


def test_floats_are_encoded_exactly() -> None:
    assert canonical_bytes(0.1 + 0.2) != canonical_bytes(0.3)
    assert canonical_bytes(0.0) != canonical_bytes(-0.0)


def test_nesting_is_not_ambiguous() -> None:
    assert canonical_bytes([[1], 2]) != canonical_bytes([1, [2]])
    assert canonical_bytes(["ab", "c"]) != canonical_bytes(["a", "bc"])


def test_tuple_encodes_as_list() -> None:
    assert canonical_bytes((1, 2)) == canonical_bytes([1, 2])


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_float_is_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        canonical_bytes({"x": bad})


@pytest.mark.parametrize("bad", [{1, 2}, object(), b"bytes", {1: "int key"}])
def test_value_outside_the_json_domain_is_refused(bad: object) -> None:
    with pytest.raises(TypeError):
        canonical_bytes(bad)  # type: ignore[arg-type]


def test_registry_hash_changes_when_a_part_changes() -> None:
    registry = StateRegistry()
    box = Box(1.0)
    registry.register("box", box)
    before = registry.hash()
    box.value = 1.0000000000000002
    assert registry.hash() != before


def test_registry_refuses_a_duplicate_name() -> None:
    registry = StateRegistry()
    registry.register("box", Box(1))
    with pytest.raises(ValueError, match="box"):
        registry.register("box", Box(2))


def test_snapshot_is_independent_of_later_changes() -> None:
    registry = StateRegistry()
    box = Box([1, 2])
    registry.register("box", box)
    saved = registry.snapshot()
    assert isinstance(box.value, list)
    box.value.append(3)
    assert saved == {"box": {"value": [1, 2]}}


def test_restore_brings_every_part_back() -> None:
    registry = StateRegistry()
    a, b = Box(1), Box("x")
    registry.register("a", a)
    registry.register("b", b)
    saved = registry.snapshot()
    before = registry.hash()
    a.value, b.value = 2, "y"
    registry.restore(saved)
    assert (a.value, b.value) == (1, "x")
    assert registry.hash() == before


def test_restore_refuses_a_snapshot_with_other_parts() -> None:
    registry = StateRegistry()
    registry.register("a", Box(1))
    with pytest.raises(ValueError, match="missing.*'a'"):
        registry.restore({})
    with pytest.raises(ValueError, match="unknown.*'z'"):
        registry.restore({"a": {"value": 1}, "z": {"value": 1}})


# --- incremental hash --------------------------------------------------------
# A part registered as tracked is re-encoded only after it is touched. The
# result must be exactly the hash an untracked registry gives.


def test_tracked_and_untracked_registries_agree() -> None:
    plain, tracked = StateRegistry(), StateRegistry()
    for registry, flag in ((plain, False), (tracked, True)):
        registry.register("a", Box(1.5), tracked=flag)
        registry.register("b", Box([1, 2]), tracked=flag)
    assert plain.hash() == tracked.hash()


def test_tracked_part_is_rehashed_after_touch() -> None:
    registry, reference = StateRegistry(), StateRegistry()
    box, same = Box(1), Box(1)
    registry.register("box", box, tracked=True)
    reference.register("box", same)
    registry.hash()
    box.value = same.value = 2
    registry.touch("box")
    assert registry.hash() == reference.hash()


def test_restore_drops_every_cached_part_hash() -> None:
    registry = StateRegistry()
    box = Box(1)
    registry.register("box", box, tracked=True)
    saved = registry.snapshot()
    before = registry.hash()
    box.value = 2
    registry.touch("box")
    assert registry.hash() != before
    registry.restore(saved)
    assert registry.hash() == before


def test_touching_an_unknown_part_is_refused() -> None:
    with pytest.raises(KeyError):
        StateRegistry().touch("nothing")


# --- comparison across CPU architectures (ADC-CI-004) ----------------------


@pytest.mark.req("ADC-CI-004")
def test_quantized_hash_ignores_differences_beyond_nine_significant_digits() -> None:
    from agentic_datacenter.core.state import quantized_hash

    a = {"t": 21.123456789012345, "n": 3, "s": "x", "list": [1.0000000001234, True]}
    b = {"t": 21.123456789099999, "n": 3, "s": "x", "list": [1.0000000001999, True]}
    assert state_hash(a) != state_hash(b)
    assert quantized_hash(a) == quantized_hash(b)


@pytest.mark.req("ADC-CI-004")
def test_quantized_hash_sees_a_difference_in_the_ninth_digit() -> None:
    from agentic_datacenter.core.state import quantized_hash

    assert quantized_hash({"t": 21.1234567}) != quantized_hash({"t": 21.1234568})
    assert quantized_hash({"t": 1.5e-7}) != quantized_hash({"t": 1.6e-7})


@pytest.mark.req("ADC-CI-004")
def test_quantized_hash_keeps_integers_and_booleans_exact() -> None:
    from agentic_datacenter.core.state import quantized_hash

    assert quantized_hash({"n": 10**12}) != quantized_hash({"n": 10**12 + 1})
    assert quantized_hash({"b": True}) != quantized_hash({"b": 1})


# --- fast path of the registry hash ------------------------------------------


def test_registry_hash_equals_the_hash_of_the_canonical_encoding_of_each_part() -> None:
    import hashlib

    registry = StateRegistry()
    parts = {"a": Box({"x": 1.5, "y": [1, True, None, "s"]}), "b": Box(-0.0)}
    outer = hashlib.sha256()
    for name in sorted(parts):
        registry.register(name, parts[name])
        digest = hashlib.sha256(canonical_bytes(parts[name].snapshot())).digest()
        raw = name.encode()
        outer.update(b"%d:" % len(raw) + raw + digest)
    assert registry.hash() == outer.hexdigest()


def test_registry_refuses_a_part_whose_snapshot_is_outside_the_json_domain() -> None:
    for bad in ({1: "int key"}, {"x": float("nan")}, {"x": {2, 3}}):
        registry = StateRegistry()
        registry.register("box", Box(bad))  # type: ignore[arg-type]
        with pytest.raises((TypeError, ValueError)):
            registry.hash()


def test_registry_notices_a_part_that_starts_using_a_bad_key_later() -> None:
    registry = StateRegistry()
    box = Box({"ok": 1})
    registry.register("box", box)
    registry.hash()
    box.value = {1: "int key"}  # type: ignore[dict-item]
    with pytest.raises(TypeError):
        for _ in range(2000):
            registry.hash()
