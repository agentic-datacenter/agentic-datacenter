# ADR 0004: Licence of the repository and position on the GPLv3 protocol library

- **Status:** Decided by the repository owner on 2026-11-12. Nothing here is legal advice.
- **Date:** 2026-11-12
- **SDD:** 8.5 ("Stage 0 MUST record in an ADR how GPLv3 for this one component sits with the licence chosen for the agentic-datacenter repository"), 14

## Context

The SDD makes this the owner's decision and forbids the build from assuming an answer. This ADR records the facts and the options so the decision can be taken once and written down.

Facts as of Stage 0:

- **The repository has no licence.** It is private, and no `LICENSE` file or licence metadata has been added.
- **`libiec61850`** is the practical open implementation of IEC 61850 MMS. It is published under GPLv3, with a commercial licence sold by its vendor. The Python wheel considered for it is also GPLv3 and describes itself as experimental.
- **REMORA** declares `BUSL-1.1` with a separate commercial licence. It is a dependency of `agentic-datacenter-remora` only.
- **The SDD already limits the exposure:** the protocol library is used only in the optional distribution `agentic-datacenter-iec61850`, which runs as its own process and talks to the rest of Agentic Datacenter over a local socket. No other package imports or links it (`ADC-IEC-005`).
- **No code uses either library today.** `agentic-datacenter-iec61850` is an empty package with no dependency on the protocol library.

## Questions the owner needs to answer

1. What licence does the Agentic Datacenter repository carry, if any, while private, and what is intended if it becomes public?
2. Is `agentic-datacenter-iec61850` itself licensed under GPLv3 (the straightforward reading for code that imports a GPLv3 library), with the other seven distributions under the repository licence?
3. Is the process boundary accepted as sufficient separation for the other distributions, or is the vendor's commercial licence preferred?
4. Does the BUSL-1.1 licence of REMORA place any condition on publishing `agentic-datacenter-remora` or benchmark results obtained with it?

## Options

| Option | What it means | Main cost |
| --- | --- | --- |
| A. Per-distribution licences | `agentic-datacenter-iec61850` under GPLv3; everything else under the licence chosen for the repository; the two meet only at a socket | Two licences in one repository; the licence scan must enforce the boundary |
| B. Commercial licence for the library | Buy the vendor's licence; one licence for the whole repository | Cost; a contributor without the licence cannot build that package |
| C. Defer IEC 61850 on real sockets | Keep the in-process relay model (which needs no library) and add MMS sockets later | `ADC-IEC-001` to `-003` and the Stage 6 exit criterion cannot be met as written; needs an SDD change |
| D. Different implementation | Write or adopt an MMS server under another licence | No mature candidate is known; large effort |

## What is fixed regardless of the answer

- Until this ADR was decided, no dependency on the protocol library was added and no licence file was committed.
- The import contract and the licence scan that keep the library inside `agentic-datacenter-iec61850` are added in Stage 6 with the first code that uses it.
- This ADR must be decided before Stage 6 starts. It does not block Stages 1 to 5.

## Decision

Taken by the owner on 2026-11-12: the repository is private and the work is licensed under the Business Source License 1.1.

1. **The repository carries BUSL-1.1** (`LICENSE`), the same licence family as REMORA. This answers question 1.
2. **Option A for the protocol library.** `agentic-datacenter-iec61850` is licensed GPL-3.0-or-later, because code that imports a GPLv3 library is most simply read as covered by it. The other seven distributions are BUSL-1.1 and meet it only at a local socket (`ADC-IEC-005`). This answers questions 2 and 3.
3. **Question 4** (whether REMORA's licence conditions publishing `agentic-datacenter-remora` or results) does not arise while both repositories are private and have one owner. It is asked again before any publication.

Parameters of the licence that the owner did not state and that were filled in when the file was written. Each is the owner's to change:

| Parameter | Value written | Why |
| --- | --- | --- |
| Licensor | The licensor named in REMORA's licence | Same owner |
| Additional Use Grant | None | The narrowest choice; a grant can be added later, it cannot be taken back |
| Change Date | 2030-11-12 | Four years from the decision, the longest the licence allows for one version |
| Change License | GNU General Public License version 2.0 or later | As in REMORA |

What follows:

- The text of the GPL is added to `packages/agentic-datacenter-iec61850` with the first code there that uses the library. Until then the package is empty and only declares its licence.
- The licence scan that keeps the library inside that package is added with the same code.
- IEC 61850 is no longer blocked by this record.
