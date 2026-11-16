# ADR 0006: How the kernel makes a run reproducible

- **Status:** Proposed. Accepted when the Stage 1 kernel PR is merged by the owner.
- **Date:** 2026-11-12
- **SDD:** 5 ("Time base", run modes); requirements `ADC-KRN-001` to `-004`, `ADC-CI-004`

## Context

`ADC-KRN-001` asks for an identical state hash at every step, bit for bit, for the same profile, scenario and seed. The SDD says what must hold, not how. Four choices in the kernel decide whether it can, and none of them is visible from outside until it goes wrong.

## Decision

1. **Time is an integer.** Simulated time is a count of steps times a step length in whole milliseconds. Tasks run on periods that are whole multiples of the base step (100 ms; 1 s for the slow models). Time is never accumulated as a float.
2. **One step has one order.** Tasks that are due run in the order they were added, then time advances. A task sees the time at the start of its step. Events are delivered synchronously, in subscription order.
3. **State is JSON-domain values with one exact encoding.** Mapping keys are sorted, every item is type-tagged and length-prefixed, and a float is written in hexadecimal form so every bit counts. NaN and infinities are refused: a non-finite value in plant state is a fault to surface, not something to hash. The state hash is SHA-256 over that encoding.
4. **Random streams are SplitMix64.** Each named stream is seeded from SHA-256 of the run seed and the stream name. A stream subclasses the standard `random.Random`, so every distribution is available, but its state is a single 64-bit counter plus the cached half of a gauss pair.

## Why SplitMix64 and not the standard generator

Measured on the toy model used by the property tests (two streams), on the development machine:

| Stream generator | Step and hash every step | 24 simulated hours (864,000 steps) |
| --- | --- | --- |
| Standard library (625 words of state per stream) | about 4,000 steps/s | about 213 s |
| SplitMix64 (one word) | about 57,000 steps/s | about 15 s |

`ADC-KRN-004` allows 60 s for 24 hours of the whole generic profile. With the standard generator the stream state alone would have used that budget several times over. The implementation is checked against the published SplitMix64 reference sequence.

## Consequences

- A snapshot survives a JSON round trip and can be restored into a kernel built with another seed; the seed is part of the state.
- Subscriptions and the task list are wiring, not state. A snapshot can only be restored into a simulation built the same way.
- Drawing a number costs a Python-level call, several times slower than the standard generator. A consumer that needs very many draws per step (sensor noise on thousands of points) will need a vectorized stream; that is a decision for the stage that adds it, by ADR.
- Bit-identical results are promised on the reference image only. Functions such as the one behind `gauss` go through the platform's math library, which is why a second architecture is compared to nine significant digits (`ADC-CI-004`), not bit for bit.

## Addendum (profile PR): what the whole plant costs, and what was done about it

Measured on the generic profile with all sixteen modules as stubs (55 instances, 155 connections), on the development machine:

| | Step | 24 simulated hours | State hash |
| --- | --- | --- | --- |
| Every module stepped every 100 ms; state hashed as one value | 294 µs | 254 s | 2.1 ms each |
| Quiescent modules skipped; hash kept per part | 3.9 µs when nothing changes | 3.3 s | 56 µs after a quiet step |

The first row misses `ADC-KRN-004` by a factor of four before any model exists. Two changes, both in `agentic-datacenter-core`, bring it inside the budget:

5. **A module that is quiescent is not stepped.** A module may report that its next fast step would change nothing. The plant then skips it until one of its inputs changes, its one-second step is due, or something outside wakes it (`ModuleContext.wake`, for faults and commands). Change is detected where outputs are collected, so the one-step delay between modules is kept. A property test runs the generic profile with every module forced awake and requires identical port values at every step.
6. **The state hash is taken over per-part digests.** The hash is SHA-256 over the sorted (name, digest) pairs of the parts; a part's digest is recomputed only after it is touched. A test requires the result to equal that of a registry with no caching.

The nightly test for `ADC-KRN-004` runs 24 simulated hours with a state hash at every simulated second: about 10 s here.

What this does not settle: real models are not quiet. Thermal and hydraulic modules change every second and will be stepped and hashed every second. The budget has to be re-measured at each stage that raises a module above `F0`; the nightly test is what will show it.

## Addendum (cooling PR): the budget with real thermal models

With the six cooling modules at `F1`, 24 simulated hours took about 65 s of stepping and about 157 s with a state hash every simulated second. Four further changes brought the nightly test to about 15 s:

7. **The canonical encoding is compact JSON with sorted keys.** Python writes a float as the shortest text that reads back to the same bits, so the encoding is still exact, and it is produced in C. Mapping keys that are not strings would be coerced by JSON, so a full domain check runs the first time a part is encoded and on every thousandth encoding after that; non-finite floats and foreign types are refused on every call.
8. **Port values from the thermal models are reported at a resolution of 0.0001** (`agentic_datacenter.core.ports.settled`). A thermal model approaches steady state without arriving, so without this its outputs change in the twelfth digit every second and every module downstream is stepped for it. Modules keep their own state at full precision.
9. **A slow model that has reached steady state rests** (`SimModule.settled`), until an input changes or it is woken. An input change between one-second steps is remembered until the next one. Totals that grow while nothing else changes are `LazyIntegral`s.
10. **Point writes take a fast path** for the common case of a float inside its declared range.

A property test runs the generic plant for three simulated hours, with a chiller trip in the middle, once with these optimizations and once with every module forced awake, and requires the same port values to three decimals at every minute.

Item 8 is a modelling decision, not only an optimization: it is the resolution at which modules see each other. It is far below any sensor accuracy in the design.

What is still not measured: a day with weather that changes every second, in which nothing rests. On the development machine that is the 65 s case for stepping alone. `ADC-KRN-004` as written (the generic profile, whose weather is constant) is met; a diurnal day is not inside 60 s without hashing less often, and the 7-day optimization scenario will take minutes per run. No measurement has been made on a CI runner, because the workflows have not been able to run.

## Open question for the SDD (narrowed)

Hashing at every 100 ms step now costs about 48 s per 24 hours on a quiet plant, on top of about 3 s of stepping. That fits `ADC-KRN-004` only while the plant is idle. Whether the evidence bundle records a hash per step or per simulated second (`ADC-EVD-001` says per step) should be decided when the bundle is built in Stage 9, with the cost of the real models known. The determinism property test hashes every step regardless. Nothing in the kernel prejudges the answer.
