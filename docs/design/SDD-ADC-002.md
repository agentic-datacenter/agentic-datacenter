# SDD-ADC-002 — Public entry experience and contributor onboarding

- **Status:** Accepted on 2026-11-25. The owner asked for it to be implemented. Its requirements are `ADC-UX-001` to `ADC-UX-015` in section 11 of SDD-ADC-001, at stage 14.
- **Date:** 2026-11-25
- **Target:** public technical preview
- **Scope:** README, documentation navigation, demonstrations, contribution journeys, release verification
- **Related:** SDD-ADC-001; ADR 0025, 0027, 0029, 0033, 0034; PRs #37–#45

## 1. Objective

Make Agentic-Datacenter immediately understandable and useful to operators, equipment manufacturers, agent developers, governance developers, integrators and researchers.

- **The README is the front door.** It MUST act as the product's front door, not its architecture reference.
- **What a visitor can do without the internal terms.** Visitors MUST be able to:
  - understand the purpose;
  - inspect a result;
  - choose a relevant path;
  - discover what they can contribute and receive in return.

**Positioning:** test autonomous operations before they reach production.

**Product principle:** every supported contribution should return a useful, inspectable result. Do not promise results for paths that are not implemented.

### 1.1 Success targets

These are targets, not measured claims.

| Task | Target |
| --- | --- |
| Explain the product and its purpose | 30 seconds, without scrolling through technical details |
| Open a meaningful existing result | One click, no installation or login for a public repository |
| Find a relevant role entry | One click from the README |
| Run the first local demo | At most three shell command lines after prerequisites; target five minutes, measured and disclosed |
| Find an example input and expected output | One click from a role guide |
| Understand supported against planned features | Immediately, without reading an ADR |
| Locate licence, limitations, support and contribution terms | Within two clicks |

### 1.2 Non-goals

- **Nothing new is built.** No new SaaS, upload endpoint, production OT integration, benchmark engine, telemetry service, frontend framework or marketing microsite.
- **Nothing existing changes.** The change MUST NOT expand simulator capabilities, change policies, modify frozen benchmark semantics or rewrite historical evidence.
- **Nothing is claimed.** No claim of production readiness, vendor endorsement, calibrated site accuracy or independent certification is implied.

## 2. Information architecture

The README contains these blocks, in this order:

| Order | Block | Content and destination |
| --- | --- | --- |
| 1 | Hero | H1, a one-sentence purpose, one supporting sentence |
| 2 | Primary action | Explore the demo → the committed Markdown result report |
| 3 | Role actions | Datacenter, equipment, agent, governance. The agent button offered a language model as an optional agent once one could run (ADR 0035); until then it was labelled Roadmap |
| 4 | Visual | The existing WebP, linked to the original MP4, with a static caption and an explicit video link |
| 5 | Evidence | One short result statement, with a link to the report and its limitations. Tables and report imagery are not duplicated |
| 6 | Try locally | The existing verified commands, and an optional Codespaces link |
| 7 | Public benchmark and contribution | Compact links to the public test, registration, calibration and CONTRIBUTING |
| 8 | Documentation | Start guides, technical reference, design and evidence methodology |
| 9 | Trust and licence | Simulation-only scope, the generic facility's limits, benchmark against facility results, licence and commercial contact |

- **What the hero and role area leave out:** long paragraphs, badge walls, repeated results, unsupported endorsements and lengthy tables.
- **Length:** target at most 500 visible English words, excluding command blocks and image alt text.
- **Nothing substantive is lost.** Policy and rights information is kept by linking to its canonical document, not deleted.

## 3. GitHub-compatible rendering

- **Allowed:**
  - standard Markdown image links for buttons;
  - `<p align="center">`, `<a>` and `<img>` only where needed for layout;
  - local relative paths, so links work on branches, tags and forks.
- **Not allowed:** `<button>`, JavaScript, inline event handlers, custom stylesheets, iframes, HTML forms, remotely generated badges and third-party analytics.
- **The demo button** links to a Markdown result that GitHub renders. It is never called live before a hosted demo exists and is verified.

### 3.1 Buttons

- **Primary button:** `demo.svg`, 320 × 44, background `#176B65`, label `#FFFFFF`, radius 8, text 15 px semibold.
- **Role buttons:** four of 280 × 52, background `#162331`, border `#52647A`, title `#FFFFFF`, subtitle `#D2DCE7`, radius 8, with a simple original line icon and no vendor logos.
- **Labels and subtitles:**

  | Label | Subtitle |
  | --- | --- |
  | Bring your datacenter | Check your facility |
  | Bring your equipment | Use and contribute models |
  | Bring your agent | Language models · optional |
  | Bring your governance | Test your safety controls |

- **The agent button** says what runs: a language model, as an option. Until ADR 0035 it said Roadmap, and its alt text said planned.
- **Layout:** two buttons per row in ordinary inline flow, which wraps on narrow screens.
- **What every SVG must be:** a static picture.
  - It has explicit dimensions and a viewBox.
  - It has no script, external resource, font download, `foreignObject`, animation or link.
  - It is at most 10 KiB.
  - The Markdown anchor around it provides the action.

### 3.2 The animation

- **Kept unchanged:** `docs/media/agentic_datacenter_visual.webp` and `.mp4`, unless the maintainer approves a replacement.
- **The WebP is animated:** it has 300 frames and plays once. That was checked on 2026-11-25.
- **The README shows the animation.** A still frame was tried on 2026-11-27 to make the page lighter, and the owner asked for the animated clip back the same day. The animated WebP is 6.8 MB; it links to the video.
- **The caption:** it says the facility is illustrative and links to the video.
- **The media is supplementary.** Every action and claim stays understandable without it.

## 4. The README

The README follows section 2. The evidence statement is taken from `docs/demo/result-report.md` and is checked against it by a test. The licence language links to `LICENSE` and `COMMERCIAL_LICENSING.md` and is not paraphrased beyond that.

## 5. Role journeys

Every entry guide follows the same structure:

1. what you get;
2. what you bring;
3. try an existing example;
4. use your own input, if that is implemented;
5. inspect the actual output, and its limitations;
6. contribute or get help.

| Path | Destination | First action | Value returned | Status |
| --- | --- | --- | --- | --- |
| Demo | `docs/demo/result-report.md` | Read the existing development report | Temperature, lost IT energy, decisions and approvals | Exists; not a live hosted demo |
| Datacenter | `docs/guides/bring-your-own-datacenter.md` | `facility check examples/byodc` | Facility-fit report, missing contracts and scenarios, provenance, baseline | Implemented (ADR 0033) |
| Equipment | `equipment/README.md` | Use a `registry:<id>` entry in a bundle | Values, source, rights, rated conditions, fit and tier | Implemented (ADR 0034); eight factual chiller entries |
| Agent | `docs/guides/bring-your-own-agent.md` | Replay the recorded example, then run a model with one's own key | A run and a card of a model, labelled apart, with its transcript | Implemented as an option (ADR 0035); an agent served over HTTP is planned |
| Governance | `docs/guides/bring-your-own-gate.md` | `gate check` and a quick run | Result card: harms, useful blocks, approvals | Implemented |
| Data and research | `docs/calibration/contribute-data.md`, `docs/bench/PUBLIC_TEST.md` | Measured weather, the frozen benchmark | Traceable inputs and results | Weather only; plant calibration is not promised |

**The agent path.** The guide's first paragraph says that a language model can be the agent, that it is optional, that runs use the scripted agents otherwise, and that an agent served over HTTP is planned. Its first command replays a recorded example and needs no key. It gives no command for an integration that is not built. When an external-agent interface was implemented (ADR 0035), the same pull request did all of these:

- added a verified example, its output and a conformance test (`examples/llm-agent/`, `tests/scenario/test_llm_agent.py`);
- removed the Roadmap label.

**The governance path.** REMORA and shirudo are described by their implemented scope. A simulated keepalive with a software key is not TPM attestation or production protection.

## 6. Files

- `README.md`
- `docs/index.md`
- `docs/design/SDD-ADC-002.md`
- `docs/guides/bring-your-own-agent.md`
- `docs/guides/equipment.md`, which points into `equipment/README.md` from the documentation site
- `docs/media/buttons/{demo,datacenter,equipment,agent,governance}.svg`
- `tests/conformance/test_readme_experience.py`

## 7. Requirements

The requirements are in SDD-ADC-001, section 11, as `ADC-UX-001` to `ADC-UX-015`. Their tests are named there.

Four of them are checked by people, not by a test:
- `ADC-UX-004`: rendering at the widths 360, 390, 768 and 1280, in the light and dark themes, with the keyboard and with images off;
- `ADC-UX-005`, in part: opening the report without being signed in, once the repository is public;
- `ADC-UX-012`, in part: a review of the licence and commercial language by the maintainer;
- `ADC-UX-015`: two independent first-time users.

They stay open until the result is recorded.

## 8. Order of work

1. Tests first: route order, local assets, link validity, maturity labels.
2. Buttons and the agent roadmap guide. The original media is kept.
3. README and `docs/index.md`, and the navigation. The report picture stays in the operator guide.
4. The full checks of CONTRIBUTING, and a fresh-clone run of the demo and of the role examples, with their times recorded.
5. External usability and rendering checks.

Publication waits for the maintainer. The repository's visibility is never changed by this work.

## 9. Definition of done

- Every requirement with a test passes. The manual ones are recorded, or listed as open.
- The README has five truthful, working entry actions, and the agent button says what runs.
- The animation, the video and the integrity of the evidence are unchanged.
- No frozen benchmark input is altered, and no production-safety claim is made.
- Two independent first-time users have found their path.
- The maintainer has authorised publication.
