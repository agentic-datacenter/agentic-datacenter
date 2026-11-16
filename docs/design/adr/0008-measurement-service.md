# ADR 0008: Sensors are a kernel service implemented by a module

- **Status:** Accepted with the Stage 4 sensors PR.
- **Date:** 2026-11-12
- **SDD:** 5.1, 6.5; requirements `ADC-CTL-006`, `ADC-MOD-002`

## Context

SDD 6.5 says every measured point passes through a sensor model, and the repository layout gives sensors their own plant module. SDD 5.1 says no plant module may import another and that modules exchange values only through ports. A POD's controller needs the reading of its zone sensors in the same step in which the hall temperature is computed; a port would deliver it one step late and would need one port per sensor.

A measurement is also not a flow between subsystems. Nothing is conserved, and the sensor belongs to the equipment it is mounted on.

## Decision

1. `agentic-datacenter-core` defines `MeasurementService`: `measure(tag, true_value, kind)` returning a reading and whether its quality is good, and `is_static(owner)`.
2. The `sensors` module implements it. A plant has at most one such module; two is a wiring error.
3. The plant hands the service to every other module through `ModuleContext.measure(name, true_value)`. The tag is the instance name plus the point name, so a module can only read its own sensors. No module imports `sensors`, and the independence contract still holds.
4. With no sensor module in the plant, `measure` returns the true value with good quality. A module can therefore be tested alone, and the subset rule of `ADC-MOD-004` is kept.
5. Each sensor draws from its own random stream, named by its tag, so readings do not depend on the order in which modules run.

## Consequences

- This is a deliberate exception to "ports, not imports": a synchronous call from one module into another module's code, through an interface the kernel owns. It is the only one.
- The sensor module's state changes when another module reads a sensor, so the plant marks that state as changed on every reading.
- A sensor fault is injected on the sensor module, which then wakes the module that owns the sensor; otherwise a resting POD would never read its failed sensor.
- A POD may rest at steady state only while its sensors are static (`ModuleContext.measurements_static`). A drifting or noisy sensor keeps it stepping, which is what lets the cross-check see the drift.
- Only the POD zone array uses the service so far. SDD 6.5 says every measured point; the other points still report true values, and the module specs say so.
