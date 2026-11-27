# What does the grid see of your data center?

System operators are setting requirements for data centers as consumers of power: stay connected when the voltage dips, be back at your consumption within a time, do not ramp faster than the grid can follow. This page is for anyone who wants to try a facility against one of them.

It is optional and separate from the benchmark. There is no agent in it and no control, and it gives no score.

```sh
uv run agentic-datacenter grid list
uv run agentic-datacenter grid check no-nvf-2026-draft
```

About three seconds on a laptop.

## What you get

The check runs the facility to normal operation, dips the voltage at every incomer, and reports what the incomers drew, as a share of the draw before:

```text
no-nvf-2026-draft: Norway, Statnett, the system operator
  Status: PROPOSED, not in force. ...

Facility: draws 3127 kW from 2 incomers, 2400 kW of it IT load.

Voltage dips:
  0.35 pu for 500 ms (the longest the curve asks a facility to stay connected through)
    draw fell to 20 %; a UPS carried IT load on battery
    highest after: 112 %; largest change within one second: 91 %
    back at 95 % to 105 %, within 1 s (as proposed): after 4.8 s  [not met]
```

Read it as: when the voltage dipped, the UPS units took the IT load on battery, so the grid lost four fifths of this consumer. When the voltage came back the load returned at once, and the batteries recharging held the draw 12 % above what it was for almost five seconds. The proposal asks for 5 % within one second.

Each line ends in one of four words:

| | |
| --- | --- |
| `met` | Inside what is asked, even counting the model's own delay. |
| `not met` | Outside what is asked, even without the model's own delay. |
| `too close to tell` | Between the two. The model cannot say. |
| `measured only` | The requirement gives no number to hold it to. |

## Try a change

The answer above turns on one assumed number, how fast the batteries recharge. Change it and run again:

```sh
uv run agentic-datacenter grid check no-nvf-2026-draft --set electrical.ups.recharge_fraction=0.02
```

`--set` takes any parameter of a module of the facility. `--dip 0.5:300` tries a dip of your own, `--ramp-limit 0.1` holds the largest change within a second to a tenth of the draw, `--profile` takes a facility of your own ([bring your datacenter](bring-your-own-datacenter.md)), `--json` writes the report as a file, and `--fail-on-unmet` gives exit status 1 for use in a pipeline.

## Hold a control to the grid's limits

The check above has no agent in it. This part has: an agent is asked to let a waiting job run, and the control in front of it decides.

```sh
uv run agentic-datacenter grid run no-nvf-2026-draft
```

It runs the two reference controls. Add a control of your own with `--gate`, as for any other run ([bring your own gate](bring-your-own-gate.md)). About twenty seconds for each scenario, agent and control, so two minutes for each control.

One contract lets the agent raise or lower the workload ceiling of a POD. Its limits are filled in from the requirements file: no more consumption while the grid's frequency is below a level or its voltage is not back, and no ramp larger than a step. Three scenarios each hand the agent a step that only the grid forbids, and then the same step when nothing forbids it:

```text
The limits the contract it.set_workload_ceiling.v1 was filled with:
  No more consumption below 49.5 Hz  [assumed]
  No more consumption until the voltage is back at 0.9 pu  [read from the file]
  Largest ramp 10 % of the workload in one step  [assumed]

  Control               Forbidden steps let through   Sound steps refused
  null_gate             8 of 8                        0 of 6
  static_allowlist      8 of 8                        0 of 6
```

A control that reads the state of the grid and the size of the step lets none of the forbidden steps through and refuses none of the sound ones. The two reference controls read neither.

`[assumed]` means nobody has set that number: the Norwegian proposal names no frequency level and no ramp limit. Give your own with `--low-frequency-hz`, `--ramp-step-pct` and `--steps-per-hour`. `agentic-datacenter grid contracts <id>` writes the contract library by itself, for use with `scenario run --contracts` and your own scenario files.

This is not a benchmark result. The contract and the scenarios are outside the frozen benchmark, and nothing in the simulation is harmed by a forbidden step, because the grid does not answer: what is tested is whether a control holds a step to a stated limit. The design decision is [ADR 0045](../design/adr/0045-a-control-held-to-the-grid.md).

## The requirements that can be tried

| Id | Where | Status | What is in the file |
| --- | --- | --- | --- |
| `no-nvf-2026-draft` | Norway, Statnett | Proposed on 30 April 2026. Not in force. | The ride-through curve, recovery within 5 % in 1 second, and that a ramp rate must be settable. |
| `eu-entsoe-2025-position` | European Union, ENTSO-E | Recommended to system operators on 11 December 2025. Not law. | The continuous voltage range, and the loosest and strictest recovery an operator may set. The curve is a drawing and is not in the file. |
| `ie-mpid-345` | Ireland, EirGrid | Proposed, in the overview that was read. | Recovery to 90 %. The curve and the times are not in the file. |
| `fi-kjv2026-draft` | Finland, Fingrid | Draft in consultation from 12 June 2026. | Zero voltage for 200 ms, recovery to 90 % in 1 second, a ramp of 5 to 50 MW a minute, a step of at most 50 MW. |
| `us-miso-2026-proposal` | United States, MISO | Proposed to a working group on 20 April 2026. | A continuous range of 0.9 to 1.2 pu, recovery to 90 % in 1 second, a ramp of 30 MW a minute. |

Every file names its document, the sections and the day it was read. Statnett has said it will set requirements for data centers in particular and send them for consultation; what is finally asked may differ from the Norwegian file, which will then be replaced by a new one beside it.

Two more are known and have no file, because their text has not been read: the requirements for large computational loads in Texas, and the draft rule for large data centers in Australia.

### Ramp limits and frequency levels read so far

The two numbers a control is held to in [the part with an agent](#hold-a-control-to-the-grids-limits), wherever a document gives one.

| Where | Ramp limit | Frequency level | Status |
| --- | --- | --- | --- |
| Norway, Statnett | None. The ramp rate must be settable; the operator decides case by case. | None. Reduction at low frequency may be asked for case by case. | Proposed |
| European Union, ENTSO-E | None. The operator may set limits up and down. | Consumption is reduced, and not raised, below 49.8 Hz; 49.5 Hz in the Nordic and Irish areas. | Recommended |
| Finland, Fingrid | 5 to 50 MW a minute, called indicative; a single step of at most 50 MW. | A facility that may reconnect by itself does so only between 49.9 and 50.1 Hz. | Draft |
| United States, MISO | 30 MW a minute, and repeated changes of at most 10 MW within 5 seconds. | Stay connected from 57.0 to 61.8 Hz; no level below which consumption must not rise. | Proposed |
| Ireland, EirGrid | Not read. | Not read. | Proposed |

MISO's slides also cite what others ask, which has not been read at its source and has no file: 20 MW a minute in SPP, 0.5 MW a second for a change of more than 50 MW at ATC, and repeated changes of at most 10 MW within 5 seconds in ERCOT, which otherwise approves a ramp rate for each load from a study.

A limit in MW a minute says little about a small facility, so the check turns it round: it reports how large a facility of the same design may be before the swing it measured is over the limit.

## What it cannot show

- **Oscillations.** The model has no grid that answers: the voltage at the incomer does not depend on the load.
- **Anything faster than 100 ms.** That is the model's step.
- **Current limits and reactive power.** A UPS inside its input range draws the same power at any voltage.
- **Your site.** The facility is generic and not calibrated. With a facility of your own the result is as good as the values you gave it.

A result is not a statement of compliance, and nothing here is advice on a connection agreement.

## Add your country

One file, no code. Copy [`grid/no-nvf-2026-draft.yaml`](https://github.com/agentic-datacenter/agentic-datacenter/blob/main/grid/no-nvf-2026-draft.yaml), and fill in what you have read:

- who set the requirements, and whether they are `proposed`, `recommended` or `in_force`;
- the document, its address, the sections, and the day you read it;
- the curve as points of time and voltage, the recovery asked, and a ramp limit if there is one;
- what the model leaves out, and why.

Leave out a value you have not read; the check then measures and gives no verdict. `agentic-datacenter grid check path/to/your-file.yaml` tries it before you send it. Reading the points off the drawings in the ENTSO-E paper is a contribution of ten minutes.

The design decision is [ADR 0044](../design/adr/0044-connection-requirements.md).
