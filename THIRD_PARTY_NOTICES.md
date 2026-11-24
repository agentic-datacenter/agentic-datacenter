# Third-party notices

Required by `ADC-PRV-005`. This file lists what was consulted to design Agentic-Datacenter and what third-party software it uses. It is updated in the same PR that adds a source or a dependency.

## Unpublished reference

**The reference specification** (a construction specification for a modular data center, unpublished). Consulted for the kinds of plant, control behaviour and interfaces a facility of this type has. It is referred to only by that description: the repository does not identify or quote it, and holds no value taken from it. Everything else that informed the model is public practice and the standards listed below.

- No text from it is reproduced in this repository. Behaviour is restated as original requirements and state machines (`ADC-PRV-001`).
- Nothing that identifies it appears in this repository: not the names of its project, owner, engineer or site, nor its title, issue or section numbers (`ADC-PRV-002`).
- No value taken from it is in this repository. Such values may live only in `profiles/restricted_ref.yaml`, which is excluded from version control; the public profile `profiles/generic_dc.yaml` uses independently chosen values (`ADC-PRV-003`).

## Measured datasets

**No measured dataset is included in this repository or in any Agentic-Datacenter distribution.** The measured-input layer (`agentic-datacenter-data`, ADR 0018) reads a series the user supplies at run time from outside the repository. The licence of such a dataset is recorded, as its source states it, in the dataset's own manifest, and derived data is not redistributed until its owner has cleared it in writing.

Datasets suggested for later calibration work are listed in `docs/calibration/suggested_resources.md`. None of them is used, included, fetched or redistributed, so none is a third party to this repository.

Whoever runs Agentic-Datacenter on a measured dataset of their own gives the attribution that dataset's licence requires.

## Media

`docs/media/agentic_datacenter_visual.mp4` and `docs/media/agentic_datacenter_visual.webp` were made by the owner of this repository, based on this project, and are under the licence of this repository. They show a rendered, illustrative facility, not a real site.

`docs/media/season1-register-banner.webp` is an original AI-generated promotional illustration created using OpenAI image generation for the Season 1 registration pages and optimized into WebP format. It contains no photograph, third-party facility design or measured plant data. The pictured infrastructure and control-system annotations are illustrative, not a diagram of a deployed or calibrated facility. This record concerns media provenance and does not establish the model's engineering validity.

## Services used at run time

| Service | Used by | What is taken from it |
| --- | --- | --- |
| drand "quicknet" randomness beacon, run by the League of Entropy, read through the relays `api.drand.sh` and `drand.cloudflare.com` | `tools/heldout_beacon.py` | One public random value per public-test season, the secret of the held-out variants (`docs/bench/PUBLIC_TEST.md`). Nothing is stored or redistributed but that value. |

## Standards cited

**No text from any standard is reproduced in this repository.** Standards are cited by number for vocabulary, structure and the names of requirements. Where a numeric limit is used, it was taken from the freely available secondary source listed below and is tagged that way in the profile, to be replaced when the standard text or an equipment datasheet is available.

| Standard | Used for |
| --- | --- |
| ISA/IEC 62443-3-2 | Zone and conduit method, target security levels |
| ISA/IEC 62443-3-3 | Foundational and system requirement numbers and titles for the generated matrix |
| ISA/IEC 62443-2-1, 2-4, 4-1, 4-2 | Vocabulary only |
| IEC 61850 (parts 6 and 7-4, and MMS services) | Logical node names, engineering file format, service list for the MV relays |
| IEC 62351-3 and -4 | Named as the transport security for MMS in `compose` mode |
| IEC standard inverse-time overcurrent characteristic (IEC 60255-151) | The relay trip-time formula |
| ISO 8528-5 | Generator performance classes and transient limits |
| ITI (CBEMA) curve | Voltage tolerance of IT equipment |
| ASHRAE TC 9.9 thermal guidelines | Recommended and allowable inlet temperature ranges |
| EN 15232 | Named in `ADC-PRV-005`; no value or requirement in the design is taken from it so far |
| DOE-2 chiller performance curve form | The shape of the chiller capacity and efficiency curves; no coefficient data is taken from it |
| RFC 2119 | The meaning of MUST, SHOULD and MAY |

Modbus, BACnet/IP, SNMP and OPC UA are named as the protocols the simulated servers speak, through the libraries listed under Software; no text of their specifications is reproduced.

Not verified against the standard text, and stated as such in the design document (4.4): the requirement-enhancement numbers of IEC 62443-3-3 and the security level at which each requirement applies.

## Secondary sources consulted

Opened on 2026-11-12. Used for the values and facts noted; nothing is copied from them.

| Source | Used for |
| --- | --- |
| ISA, table of contents of ISA-62443-3-3 (published freely by ISA) | System requirement numbers and titles |
| Cummins, "Transient performance of generating sets"; UFGS 16237N performance class table | ISO 8528-5 class limits used as profile defaults |
| ITI (CBEMA) curve application note, as reproduced by PQBlog | IT equipment voltage tolerance used as profile defaults |
| `libiec61850` repository; `pyiec61850-ng` on PyPI | Library capabilities and licence |

Links are in the "Sources" section of `docs/design/SDD-ADC-001.md`.

## Software

Agentic-Datacenter is licensed under the Business Source License 1.1 (`LICENSE`). The components below are third-party; each keeps its own licence. None is vendored into this repository, and none is modified from it.

### Runtime dependencies

As installed from `uv.lock` on 2026-11-13, with the licence each project declares in its package metadata.

| Component | Version | Declared licence | Used by |
| --- | --- | --- | --- |
| `pydantic` (with `pydantic_core`, `annotated-types`, `typing-inspection`, `typing_extensions`) | 2.14.3 | MIT; `typing_extensions` PSF-2.0 | every distribution |
| `PyYAML` | 6.0.3 | MIT | `agentic-datacenter-core` |
| `fastapi` (with `starlette`, `anyio`, `idna`, `annotated-doc`, `opentelemetry-api`) | 0.162.5 | MIT; `starlette` and `idna` BSD-3-Clause; `opentelemetry-api` Apache-2.0 | `agentic-datacenter-supervisory` |
| `pymodbus` | 3.16.2 | BSD-3-Clause | `agentic-datacenter-net` |
| `bacpypes3` | 0.0.110 | MIT as its licence expression, with the classifier "BSD License"; the package and its repository carry no licence text (ADR 0013) | `agentic-datacenter-net` |
| `pysnmp` (with `pyasn1`) | 7.1.32 (`pyasn1` 0.6.5) | BSD-2-Clause, from the licence file in the package (its metadata declares none); `pyasn1` BSD-2-Clause | `agentic-datacenter-net` |
| `asyncua` (with `aiosqlite`, `pytz`, `sortedcontainers`, `python-dateutil`, `cryptography`) | 2.1.0 | LGPL-3.0-or-later; `aiosqlite` and `pytz` MIT; `sortedcontainers` Apache-2.0; `python-dateutil` BSD-3-Clause; `cryptography` Apache-2.0 or BSD-3-Clause | `agentic-datacenter-net` |
| `cryptography` | 50.0.2 | Apache-2.0 or BSD-3-Clause | `agentic-datacenter-governance`, for the host keys and quotes of ADR 0032; also installed with `asyncua` above |
| REMORA (`remora-assurance`) | 0.12.0 at the commit in `REMORA_PIN` | BUSL-1.1, with a separate commercial licence, as declared by that project | `agentic-datacenter-remora` only |
| `pyiec61850-ng`, carrying `libiec61850` 1.6.1 and Mbed TLS | 1.6.1.10 | GPLv3; Mbed TLS Apache-2.0 | `agentic-datacenter-iec61850` only, on Linux only (ADR 0017). That distribution is GPL-3.0-or-later; its licence text is `packages/agentic-datacenter-iec61850/LICENSE` |

`asyncua` is under the GNU Lesser General Public License, version 3 or later. Agentic-Datacenter uses it as an unmodified package installed separately from PyPI; it is not copied into this repository and not changed (ADR 0015). If Agentic-Datacenter is ever distributed, the distribution must say that it uses `asyncua` under the LGPL, include the texts of the GPL-3.0 and the LGPL-3.0, and leave the recipient able to replace the library with a modified version, which rules out freezing it into a single executable.

`libiec61850` is under the GPLv3. It is not in this repository: whoever installs the `iec61850` group fetches it from PyPI. When it is loaded, it runs in one process with `agentic-datacenter-iec61850` (GPL-3.0-or-later) and with the packages that distribution loads, which are under the Business Source License 1.1. Running that is open to anyone under both licences. Conveying it as one work, for example a container image or an executable that holds the library together with those packages, is not, because the terms of the Business Source License 1.1 are not compatible with the GPLv3. No such image or executable is published from this repository (ADR 0004, addendum of 2026-11-17 on publication).

### Formats and test data from shirudo

[shirudo](https://github.com/shirudo-dev/shirudo), BSD-2-Clause, copyright (c) 2026 Authors of shirudo, at commit `6514073a6b62bb0ae1e2b55a8ab7dabe8c50e414`, the commit in `SHIRUDO_PIN` (ADR 0032).

- **The keepalive format `shirudo.keepalive/1`.** `agentic_datacenter.governance.keepalive` makes and checks keepalive bodies and quotes in this format. It was written from shirudo's published description of the format and of `shirudo-quote-check`; no shirudo source code is copied into it or translated from it.
- **Five test files, copied unchanged** into `tests/fixtures/shirudo/keepalive/` from shirudo's `testing/fixtures/keepalive/`: four keepalive bodies and `quotes.tsv`. They stay under shirudo's licence, whose text is in `tests/fixtures/shirudo/LICENSE`, as the licence asks. `SHIRUDO_PIN` lists their SHA-256. They are used by the tests only and are in no wheel or source distribution of Agentic-Datacenter.
- Nothing of shirudo is installed, built or run. Its BPF programs, which are dual-licensed BSD/GPL, and the files it vendors from other projects under their own licences are not used.
- shirudo is named only to say which format is implemented. Its name and logos are not used for anything else, and nothing here says that its authors endorse Agentic-Datacenter.

### Development and test tools

`uv`, `ruff`, `mypy`, `pytest`, `pytest-xdist`, `hypothesis`, `import-linter`, `hatchling`, `httpx`, `mkdocs`, `pip-audit`. Each under the licence its project declares; versions are fixed by `uv.lock`. They are not part of what Agentic-Datacenter distributes.

## Licence of this repository

Business Source License 1.1, in `LICENSE`, for everything except `packages/agentic-datacenter-iec61850`, which is GPL-3.0-or-later. Decided by the owner on 2026-11-12; see `docs/design/adr/0004-licence-position.md`. Who the Licensor is, and who handles commercial licences, is in `COMMERCIAL_LICENSING.md`. The example gates in `examples/` are under the MIT licence (`examples/LICENSE`), so that a gate started from them can be kept under any licence.
