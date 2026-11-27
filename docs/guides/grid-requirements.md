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

## The requirements that can be tried

| Id | Where | Status | What is in the file |
| --- | --- | --- | --- |
| `no-nvf-2026-draft` | Norway, Statnett | Proposed on 30 April 2026. Not in force. | The ride-through curve, recovery within 5 % in 1 second, and that a ramp rate must be settable. |
| `eu-entsoe-2025-position` | European Union, ENTSO-E | Recommended to system operators on 11 December 2025. Not law. | The continuous voltage range, and the loosest and strictest recovery an operator may set. The curve is a drawing and is not in the file. |
| `ie-mpid-345` | Ireland, EirGrid | Proposed, in the overview that was read. | Recovery to 90 %. The curve and the times are not in the file. |

Every file names its document, the sections and the day it was read. Statnett has said it will set requirements for data centers in particular and send them for consultation; what is finally asked may differ from the Norwegian file, which will then be replaced by a new one beside it.

Two more are known and have no file, because their text has not been read: the requirements for large computational loads in Texas, and the draft rule for large data centers in Australia.

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
