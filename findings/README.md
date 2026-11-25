# Operational findings

A finding is one claim that runs support, kept so that what one run showed is not lost when the next one is made. Each is a file, `ADC-FIND-<nnnn>.yaml`, checked by `tools/findings.py` and by the tests, and listed on [the findings page](../docs/reference/findings.md).

| Field | What it holds |
| --- | --- |
| `finding_id` | `ADC-FIND-<nnnn>`, the file's name |
| `status` | `hypothesis`, `supported`, `replicated`, `contradicted` or `superseded` |
| `visibility` | `public`; only public findings are kept here |
| `claim` | the claim, in one or two sentences |
| `scenarios`, `facility_class`, `gates`, `agents` | where it was seen |
| `evidence_refs` | files in this repository with their SHA-256: a card, a bundle, a recording |
| `depends_on` | the hash of each scenario, equipment entry and profile it rests on |
| `validity_conditions`, `limitations` | when it holds, and what it does not say |
| `independent_replications` | who ran it again, with their evidence, and whether it `confirms` or `contradicts` |
| `supersedes`, `superseded_by` | the finding it replaces, or that replaced it |
| `credited_to` | who contributed it, by the name they agreed to |

**When an input changes.** A scenario, an equipment entry or a profile that a finding depends on gets another hash, and the finding is *stale*. A `supported` or `replicated` finding that is stale fails the check until someone looks at it again: runs it, records the new hashes, or changes its status. That is how a change to a model shows which knowledge it touches.

**Search.** `python tools/findings.py search --scenario OP-03 --gate remora_governed` lists the findings that match; `--equipment <id>` and `--facility-class` narrow it too.

**Private findings.** A finding about a site or a gate that is not public is kept by its owner with the same schema, and checked with `python tools/findings.py --dir <directory> --check`. Nothing private belongs in this repository.

**Add one, or a replication.** Open a pull request with the file. A replication adds an entry to `independent_replications` with your evidence; a contradiction is as welcome as a confirmation.
