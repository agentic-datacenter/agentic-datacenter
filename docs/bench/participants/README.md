# Entries of enrolled systems

One file per governance system, `<id>.yaml`, added only after its maintainers enrolled it themselves with the registration form and ticked the consent to be listed by name. `tools/participants.py` checks every entry and writes [`../participants.md`](../participants.md) from them; a test fails when an entry lacks its registration issue or its consent, or the page is not up to date.

```yaml
id: my-gate                      # the file name
name: My Gate                    # as the maintainers gave it
gate: my_gate                    # the name on its cards (ADC_GATE_NAME)
version: 40-character commit SHA, package hash or image digest
connection: http_gate            # http_gate, command_gate, package or chain_gate member
relation: independent            # or benchmark_authors
enrolled:
  issue: https://github.com/darklordVirtual/agentic-datacenter/issues/<n>
  date: 2026-12-01
  listing_consent: true          # ticked in the issue; no consent, no name
project_url: https://example.org # optional
results:                         # oldest first; the last is shown
  - card: docs/bench/results/my-gate/<version>/result_card.json
    agentic_datacenter: benchmark-v1.3
    kind: verified               # or self_reported
findings:
  - id: F-001
    scenario: AD-04
    seen_in: benchmark-v1.3
    summary: A decision reference was accepted twice.
    status: reported_privately   # then open, fixed or wont_fix
    fixed_in: null
    disclosed: null              # the date it was published; required once it is not private
```

A finding goes to the maintainers first and is described on the page once they have fixed it or agreed to its publication.
