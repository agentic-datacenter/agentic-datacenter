"""Seeded random streams: reproducible, independent, restorable."""

from agentic_datacenter.core.rng import RandomStreams


def draws(streams: RandomStreams, name: str, n: int = 5) -> list[float]:
    return [streams.stream(name).random() for _ in range(n)]


def test_same_seed_and_name_give_the_same_sequence() -> None:
    assert draws(RandomStreams(42), "sensor") == draws(RandomStreams(42), "sensor")


def test_different_names_give_different_sequences() -> None:
    streams = RandomStreams(42)
    assert draws(streams, "sensor") != draws(streams, "load")


def test_different_seeds_give_different_sequences() -> None:
    assert draws(RandomStreams(1), "sensor") != draws(RandomStreams(2), "sensor")


def test_drawing_from_one_stream_does_not_disturb_another() -> None:
    alone = draws(RandomStreams(42), "sensor")
    mixed = RandomStreams(42)
    out = []
    for _ in range(5):
        mixed.stream("load").random()
        out.append(mixed.stream("sensor").random())
    assert out == alone


def test_order_of_first_use_does_not_matter() -> None:
    first = RandomStreams(42)
    first.stream("a")
    a_then_b = draws(first, "b")
    assert a_then_b == draws(RandomStreams(42), "b")


def test_stream_returns_the_same_generator_for_a_name() -> None:
    streams = RandomStreams(42)
    assert streams.stream("sensor") is streams.stream("sensor")


def test_restore_continues_the_sequence_where_the_snapshot_was_taken() -> None:
    streams = RandomStreams(42)
    draws(streams, "sensor", 3)
    saved = streams.snapshot()
    expected = draws(streams, "sensor", 4)
    streams.restore(saved)
    assert draws(streams, "sensor", 4) == expected


def test_restore_into_streams_built_with_another_seed() -> None:
    source = RandomStreams(42)
    draws(source, "sensor", 3)
    saved = source.snapshot()
    target = RandomStreams(7)
    target.restore(saved)
    assert draws(target, "sensor") == draws(source, "sensor")
    assert draws(target, "new") == draws(RandomStreams(42), "new")


# --- generator with a small state -------------------------------------------
# The state hash is taken often (ADC-KRN-001, ADC-EVD-001), so a stream's
# state must be a few numbers, not the 625 words of the standard generator.


def test_splitmix64_matches_the_published_reference_sequence() -> None:
    from agentic_datacenter.core.rng import splitmix64_next

    state, outputs = 1234567, []
    for _ in range(5):
        state, value = splitmix64_next(state)
        outputs.append(value)
    assert outputs == [
        6457827717110365317,
        3203168211198807973,
        9817491932198370423,
        4593380528125082431,
        16408922859458223821,
    ]


def test_stream_state_is_small() -> None:
    from agentic_datacenter.core.state import canonical_bytes

    streams = RandomStreams(42)
    draws(streams, "sensor", 100)
    assert len(canonical_bytes(streams.snapshot())) < 120


def test_random_is_in_unit_interval_with_plausible_mean() -> None:
    stream = RandomStreams(42).stream("sensor")
    values = [stream.random() for _ in range(100_000)]
    assert all(0.0 <= v < 1.0 for v in values)
    assert abs(sum(values) / len(values) - 0.5) < 0.005


def test_getrandbits_respects_the_requested_width() -> None:
    stream = RandomStreams(42).stream("sensor")
    for k in (1, 7, 53, 64, 65, 200):
        values = [stream.getrandbits(k) for _ in range(200)]
        assert all(0 <= v < 2**k for v in values)
        assert max(values).bit_length() == k
    assert stream.getrandbits(0) == 0


def test_randrange_covers_its_range_evenly() -> None:
    stream = RandomStreams(42).stream("sensor")
    counts = [0] * 10
    for _ in range(50_000):
        counts[stream.randrange(10)] += 1
    assert min(counts) > 4_700 and max(counts) < 5_300


def test_gauss_has_plausible_moments() -> None:
    stream = RandomStreams(42).stream("sensor")
    values = [stream.gauss(0.0, 1.0) for _ in range(100_000)]
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    assert abs(mean) < 0.01 and abs(variance - 1.0) < 0.02


def test_restore_between_the_two_halves_of_a_gauss_pair() -> None:
    streams = RandomStreams(42)
    stream = streams.stream("sensor")
    stream.gauss(0.0, 1.0)  # leaves the second value of the pair cached
    saved = streams.snapshot()
    expected = [stream.gauss(0.0, 1.0) for _ in range(3)]
    stream.gauss(0.0, 1.0)
    streams.restore(saved)
    assert [stream.gauss(0.0, 1.0) for _ in range(3)] == expected
