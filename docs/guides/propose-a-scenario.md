# Propose a scenario

A benchmark is no better than its scenarios, and the people who know what should be tested are the ones who run governance systems, plants and audits. A scenario that joins a frozen version is run against every enrolled system from then on. One good scenario is worth something to everyone who takes part, including you.

## The short way: say it in words

Open the [scenario form](https://github.com/agentic-datacenter/agentic-datacenter/issues/new?template=scenario-proposal.yml) and say two things: what happens, in order, and what a good control does that a weak one does not. That is enough. Someone who knows the simulator writes the file, and you are asked whether it says what you meant.

## The longer way: write it and try it

A scenario is a small file: a length, a timeline of events, and the criteria a run must meet. Copy one from [the library](https://github.com/agentic-datacenter/agentic-datacenter/tree/main/packages/agentic-datacenter-scenarios/src/agentic_datacenter/scenarios/library) that is near what you want, change it, and run your file:

```sh
cp packages/agentic-datacenter-scenarios/src/agentic_datacenter/scenarios/library/AD-11.yaml my-scenario.yaml
# change the id to one that is free, AD-90 to AD-99 or OP-90 to OP-99, and the timeline
uv run agentic-datacenter scenario run my-scenario.yaml --gate static_allowlist --out build/my-scenario
uv run agentic-datacenter scenario run my-scenario.yaml --gate null_gate --out build/my-scenario-no-control
```

Each run prints whether the scenario's criteria were met and writes an evidence bundle with every decision and the action trace. A file that cannot be read is refused with the reason, before anything runs.

The events a timeline can hold are listed in the scenario reader ([`scenario.py`](https://github.com/agentic-datacenter/agentic-datacenter/blob/main/packages/agentic-datacenter-scenarios/src/agentic_datacenter/scenarios/scenario.py)): a fault in the plant, a change of who may act, a work order, a forged statement, a false reading, and others.

## A scenario about the grid

A scenario in which the state of the power grid decides whether a step may be taken goes beside `GR-01` to `GR-03` in `grid/scenarios/`, outside the benchmark's library. It uses one more contract, on the workload of a POD, whose limits come from a country's requirements. Try yours with the contract library that `agentic-datacenter grid contracts <id>` writes:

```sh
uv run agentic-datacenter grid contracts no-nvf-2026-draft --out build/grid
uv run agentic-datacenter scenario run your-file.yaml --contracts build/grid/contracts --gate static_allowlist
```

[What does the grid see of your data center?](grid-requirements.md#hold-a-control-to-the-grids-limits) has the rest.

## What gets a scenario into a version

1. **It tells two controls apart.** Run it with no control, with limits only, and with a control that does what the scenario is about. If all three come out the same, it tests nothing yet. The usual cause is that every step in it is stopped for some other reason; a work order for a step that is sound in every other way fixes that.
2. **It has a control beside it** where it can be over-blocked: the same situation with the step that should go through. A system that refuses everything must not pass.
3. **It is the same run every time.** Nothing in it depends on the wall clock or on chance outside the seed.
4. **No system is the only one that could pass it.** It tests a property that can be stated without naming a product.
5. **Its held-out variants still test the same thing.** Events are moved and values scaled in the hidden track; what the scenario is about must survive that.

Accepted scenarios wait on the main branch and join the next frozen version, which is named before the season it first applies to. A season never changes under those who are in it. The proposer is named in the scenario's file and in the changelog, if they ask for it.

## What you get

- **Your case, run against every system**, in every season from then on, with results you can cite.
- **The same scenario in your own tests.** With [the workflow](https://github.com/agentic-datacenter/agentic-datacenter/blob/main/examples/ci/agentic-datacenter.yml) in your repository, a new scenario here is a new test there, without doing anything.
- **Credit**, in the file and the changelog.

## Whose it is

- **A proposal in words is just that.** Opening the form grants nothing and asks for nothing.
- **A scenario file you wrote is yours, and joins the library under CC-BY-4.0**, with you named in its header. The contribution terms of `CONTRIBUTING.md`, which let the Licensor relicense a change, do not apply to it. Anyone may reuse your scenario with your name on it, here and elsewhere.

## What it is not

A scenario is a simulated situation in a generic facility. It is not a description of a real site, and must not be made from one.
