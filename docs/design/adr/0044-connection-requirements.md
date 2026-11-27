# ADR 0044: A facility tried against a system operator's connection requirements

- **Status:** Accepted on 2026-11-27. The owner asked for tests for Norway that anyone interested can run, and for the same in other countries where there is something to read.
- **Date:** 2026-11-27
- **SDD:** 6.6, 9.6; ADR 0029, 0033, 0034

## Context

System operators are writing requirements for data centers as consumers of power. On 9 November 2026 Statnett stopped new reservations of grid capacity for data centers until it has set functional requirements for them. Its consultation of 30 April 2026 on the national guide (NVF) already proposes some for large consumption facilities. ENTSO-E recommended a minimum set to its members in December 2025. EirGrid has put a change to the Irish grid code for large energy users to its regulator.

They ask the same question in different numbers: when the voltage dips, does the facility stay connected, and how soon is it back at what it drew?

The simulator has an answer of a kind. Its UPS has an input range and goes to battery outside it, its battery recharges at a rate, and the power the incomers carry is recorded every 100 ms. What it does not have is a grid: the incomer's voltage is set by the scenario and does not depend on the load.

## Decision

**Requirements are data.** One file per set of requirements, in `grid/`: who set them, whether they are proposed, recommended or in force, the document and the sections each value was read from, the day it was read, and what the model leaves out and why. A value that was not read is not in the file. No limit is in code.

**A check plays them.** `agentic-datacenter grid check <id>` runs the facility to normal operation, sets the voltage of every incomer to a dip and back, and reports what the incomers drew as a share of the draw before: the lowest, the highest after, the largest change within one second, whether a UPS went to battery, whether IT load was lost, and how long until the draw was back at the level asked and stayed there.

**The dips come from the curve.** A ride-through curve is the lowest voltage a facility must stay connected through. For each of a few retained voltages the check plays the longest rectangular dip that stays on or above the curve, in whole steps: the edge of what is asked.

**A time is judged with the model's delay and without it.** A change of voltage travels one module per step down to the loads and back, half a second in the generic facility. That delay is the model's and no property of a facility. A time is *met* when it is inside the limit even counting the delay, *not met* when it is outside even without it, and *too close to tell* between the two.

**A verdict only where a number was read.** Where a requirement leaves a value to the operator, as both the Norwegian proposal and ENTSO-E do for ramping, the check reports what it measured and gives no verdict, unless the person running it gives a limit.

**It is no part of the benchmark.** The check has no agent and no gate. It reads no scenario, contract or judge, and changes none: every hash of `benchmark-v1.6` is as it was. Its report carries no score.

**It never says compliant.** Every report states the status of the requirements, what was not checked and why, and what the model cannot show, and ends by saying it is not a statement of compliance.

## What the first run showed

The generic facility against the Norwegian proposal: at every dip its UPS units carry the IT load on battery, so the draw falls to the fifth that the cooling plant takes. When the voltage is back the load returns in one step, and the batteries recharge at a tenth of the UPS rating, which holds the draw 12 % above what it was, outside the 5 % the proposal allows, for about 5 to 10 seconds against the 1 second asked. With a recharge of 2 % of the rating the draw is inside the band at once.

That is a property of an assumed recharge rate in a generic model. It is also the mechanism the operators describe.

## Consequences

- A person with an interest in one country's requirements can run them in seconds, and see which numbers the answer turns on.
- A person who knows another country's requirements can add them as one file, with no code.
- The check is only as good as the plant's electrical model at fidelity F1. It cannot show oscillations, anything faster than 100 ms, current limits or reactive power, and says so.

## What it is not, yet

- **No agent and no control.** The requirements on ramping and on reducing consumption at low frequency are about load that software moves. The plant has no contract that lets an agent move IT load, so there is no scenario in which an agent ramps faster than allowed and a gate must stop it. That needs a new contract, and so a new benchmark version or a track of its own.
- **No grid that answers.** A source impedance at the incomer would let the load move the voltage. Oscillations between a facility and the grid need more than that, and validation against measurements.
- **Curves that are drawings.** ENTSO-E's and EirGrid's curves are not in their files, because the points were not read.
