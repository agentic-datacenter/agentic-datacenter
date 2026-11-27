# Your first half hour, if you maintain a governance system

You need no knowledge of data centers. This page takes you from nothing to a result for your own system, and says what you are looking at on the way.

## The plant, in six lines

- A **data center** keeps computers powered and cool. Here it is simulated: chillers, pumps, air handlers, power trains, generators.
- An **AI agent** watches it and proposes changes, such as "raise the supply air of this room by one degree".
- Each proposal is an **intent contract** with bounds: a named step, its arguments, and the limits it must stay within.
- The simulator works out the **premises** of each proposal itself: is the plant in a state where this step is sound? The agent's own words are never evidence.
- **Your system** is asked about each proposal and answers. Only what it allows is carried out.
- Afterwards every step is played **both ways**, carried out and not. A step was harmful or useful by what the plant then did.

That is all the domain you need. A temperature that goes too high, or computers that lose power, is harm. A sound step that was stopped is a cost.

## Minute 0 to 5: see it work

Requires Git and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/agentic-datacenter/agentic-datacenter && cd agentic-datacenter
uv sync
uv run agentic-datacenter demo --scenario OP-03 --gate static_allowlist --out build/first-run
```

Open `build/first-run/executive.html`. A chiller fails in a heat wave. With no control, an agent built to misbehave overheats the rooms. With a simple control that only checks limits, it does not.

## Minute 5 to 15: put your system in

The shortest way is a command that reads one JSON request and writes one JSON answer. Start from the MIT example and replace its `decide` with a call into your system:

```sh
cp examples/command-gate/adapter.py my_adapter.py      # yours, under your licence
export ADC_GATE_COMMAND="python my_adapter.py" ADC_GATE_NAME=my_system
uv run agentic-datacenter gate check command_gate
uv run agentic-datacenter bench run --tier quick --scenario OP-03 --jobs 4 \
    --gate command_gate --gate static_allowlist --out build/mine
cat build/mine/summary.md
```

A request holds the proposal, the premises and who is asking. An answer is a verdict and a reason: `ALLOW`, `DENY`, `VERIFY` (ask a person) or `ABSTAIN`. Only `ALLOW` and `DENY` are required, and your own words for them are understood (`permit`, `block`, `ask` and others).

`summary.md` puts your system beside two reference controls, no control and limits only: harmful steps let through, sound steps blocked, people asked.

## Minute 15 to 30: the part that is about authority

If your system deals in identity, delegation, credentials or trust, this is where it shows. Run the scenarios in which a mandate is withdrawn, expires, is passed on, or is forged:

```sh
export ADC_GATE_VERIFIES_MANDATES=1
uv run agentic-datacenter bench run --tier quick --jobs 4 \
    --scenario AD-11 --scenario AD-17 --scenario AD-18 --scenario AD-19 \
    --gate command_gate --gate static_allowlist --out build/authority
```

Your system is then sent signed statements and neither the answer nor a trusted record. The summary says how many steps were executed without a mandate. The starter does not look at the statements, so run as it is, it executed 6 of 47 such steps from the hostile agent and 10 of 10 from the careful one; the control that checks only limits executed 29 of 47 and 14 of 14. That gap is what a system that checks authority is for, and the next run shows whether yours closes it. The rule a correct answer follows is one page, with test vectors: [Signed mandate statements](../reference/mandate-statements.md).

## If your system does not decide

It can still take part. See [What does your project bring?](which-way-in.md#what-does-your-project-bring): state findings without deciding, give receipts to be checked, or run your verifier on an evidence bundle.

## What to do with the result

- **Keep it to yourself.** Nothing leaves your machine unless you send it.
- **Keep testing.** Copy [the workflow](https://github.com/agentic-datacenter/agentic-datacenter/blob/main/examples/ci/agentic-datacenter.yml) into your repository. It runs on your every change, and weekly against the newest scenarios here.
- **Enrol.** [Three fields](https://github.com/agentic-datacenter/agentic-datacenter/issues/new?template=gate-registration.yml), no installation. Your system then takes part in every four-week season, and is listed under the same rules as every other, if you tick the box to be named.

## What it costs you, and what it does not

- Running this to develop, test, evaluate or benchmark your system is free under the licence. Your adapter and your system are yours, under your licence; nothing of yours goes into this repository.
- The wire format, the rule for mandate statements and its test vectors may be implemented by anyone.
- A result is a simulation result. It is not a certification, and not a claim about a real facility.
