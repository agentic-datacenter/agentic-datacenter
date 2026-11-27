# Bring your equipment

The equipment registry gives a module of the simulator the values of a named make and model. Each entry records the source of every value, its licence and the right to use it (ADR 0034).

- **Use an entry** in a facility of your own by naming it as `registry:<id>` in a bundle ([Bring your own data center](bring-your-own-datacenter.md)).
- **Submit your own** as a maker: copy the template, check the entry with `uv run agentic-datacenter equipment check`, and open a pull request. An entry from a maker is under CC-BY-4.0.

The registry, its tiers, the eight chiller entries and the full submission steps are in [`equipment/README.md`](https://github.com/agentic-datacenter/agentic-datacenter/blob/main/equipment/README.md) in the repository. That file is outside this documentation site, so it is the one source of truth.

The first entries are water-cooled chillers. The simulator's chiller plant is air-cooled, so only their rated capacity and COP are taken, and each entry says that its COP is likely higher than an air-cooled chiller of the same capacity reaches.
