# Baton: literature survey and unique selling points

*Prepared 12 October 2026 for the Google Cloud AI Builder Cup 2026 judging. Sources are public vendor pages, press releases, regulator guidance and papers. Vendor claims are reported as claims. None was independently verified, and "not found" means not found in the material reviewed, not "does not exist".*

## 1. The problem: handover is where information gets lost

Failures of communication at shift handover recur in the investigation reports of major process accidents.

- The Cullen Report on Piper Alpha named failed information transfer at shift handover as one of the contributing factors. The removal of a pressure safety valve, replaced by a blind flange, was not passed between shifts, and no written handover procedure existed. A review by the Keil Centre says handover failures went on to feature in later investigations, including Buncefield, where effective handover arrangements were absent, and the US Chemical Safety Board's report on BP Texas City ([IChemE Loss Prevention Bulletin](https://www.icheme.org/media/2309/lpb229_pp25.pdf), [AIDIC](https://www.aidic.it/cet/13/31/050.pdf)).
- The Energy Institute's briefing on communications lists poor handover communication among the key contributors to Piper Alpha, Grangemouth, Texas City and Buncefield ([Energy Institute](https://publishing.energyinst.org/special-offers/free-to-download/human-and-organisational-factors/human-factors-briefing-note-no.-10-communications)).
- The UK HSE says handover should be face-to-face, two-way and use both verbal and written communication, with higher-risk handovers identified, and that the incoming shift should cross-check what it has been given ([HSE: shift handover](https://www.hse.gov.uk/humanfactors/topics/shift-handover.htm)). Its permit-to-work guidance requires a formal handover when work spans shifts, so the incoming shift knows which permit-controlled jobs are outstanding and the state of the plant ([HSE: permit to work](https://www.hse.gov.uk/humanfactors/topics/ptw.htm), [HSG250](https://books.hse.gov.uk/gempdf/hsg250.pdf)).

*Caveat:* the frequently quoted claim that every second process incident involves handover comes from one company's internal research as reported by [EHS Today](https://www.ehstoday.com/safety/why-poor-shift-handover-can-lead-serious-oil-gas-incidents). We treat it as anecdotal and do not rely on it.

The recurring failure is not a lack of notes. It is that what the outgoing shift *believes* about the plant (a lock-out is on, a permit is closed) is never checked against what the plant *is*, and the incoming shift is never made to confirm it understood.

## 2. What exists today

### A. Digital shift logbooks and handover
- **Hexagon j5**: operations logbook, shift handover, standing orders, work instructions, a separate permit-to-work application whose summaries appear in handover reports, and operator rounds that work offline on mobile devices. Hexagon reports 100 customers, 400 sites and 30,000 users ([Hexagon overview](https://aliresources.hexagon.com/articles-blogs/integrated-transparent-efficient-approach-to-operations-management), [operator rounds](https://bynder.hexagon.com/m/3db078ab8d12b446/original/PPM_j5_OperatorRounds_Brochure_A4.pdf)). A third-party comparison describes enterprise pricing and 6 to 12 month implementations ([Fabrico comparison](https://www.fabrico.io/blog/best-shift-handover-software/)); this is the reviewer's claim.
- **ShiftConnector (Eschbach)**: a digital shift book for 24/7 process industries ([Eschbach](https://www.eschbach.com/en/shiftlog/)). The same comparison notes it needs integration work to link a maintenance system.
- **Other logbooks** (eLogbook, Innovapptive and similar): structured digital notebooks that replace paper ([Innovapptive](https://www.innovapptive.com/blog/electronic-logbooks-streamlined-shift-handovers-efficiency)).

### B. Permit to work and control of work
- **Sphera Control of Work** (which includes the former Petrotechnics Proscient, acquired in 2019): electronic permits, isolations, hazard assessment and simultaneous-operations (SIMOPS) visualisation and conflict detection ([Sphera](https://sphera.com/control-of-work-software/), [acquisition report](https://www.oilfieldtechnology.com/special-reports/09012019/sphera-acquires-petrotechnics/)).
- **DNV Synergi Life** permit module: electronic creation, approval and tracking, linked to job safety analysis, risk assessment and isolation modules, with audit trails ([DNV](https://www.dnv.com/software/services/synergi-life/permit-management-software/)).

### C. Industrial AI assistants and copilots
- **Siemens Industrial Copilot**: a generative assistant that surfaces manuals and standard operating procedures at the machine, with a reported 25% reduction in reactive maintenance time in a pilot (a vendor figure) ([Automation World](https://www.automationworld.com/factory/digital-transformation/news/55248289/thyssenkrupp-adopts-siemens-industrial-copilot)).
- **AVEVA Industrial AI Assistant**, previewed with Microsoft on Azure OpenAI, to answer multi-step questions across scattered industrial data ([AVEVA](https://www.aveva.com/en/about/news/press-releases/2024/aveva-previews-industrial-ai-assistant-in-collaboration-with-microsoft-at-hannover-messe/)).
- **Cognite Atlas AI**: an agent workbench over an industrial knowledge graph, aimed at field workers, deployable into Microsoft Copilot ([Cognite](https://www.cognite.com/en/press-release/introducing-cognite-atlas)).
- **Honeywell Experion Operations Assistant** (commercial launch March 2026): control-room assistant that combines historical and real-time data; Honeywell reports it predicted problems 5 to 10 minutes before alarms in pilots with Chevron and TotalEnergies ([Honeywell](https://www.honeywell.com/us/en/press/2026/03/honeywell-unveils-commercial-launch-of-ai-powered-control-room-assistant-following-successful-pilot)).

### D. Voice-first field reporting
- **Log Sheet** offers a digital logbook with a voice bot that takes the operator's shift report and carries open items forward ([GitHub listing](https://github.com/Logsheet)).
- **Shift Pilot**, a hackathon entry (August 2026): voice-first handover where speech is transcribed, corrected, and equipment mentions are resolved against a real asset catalogue ([lablab.ai](https://lablab.ai/submissions/y38zs1g3chl617zrh6m2az5o)). The closest prior art we found.
- **Field Proxy** and **EZOps** offer voice documentation for oilfield work with offline modes ([Field Proxy](https://www.fieldproxy.ai/ai-agents/oilgas-field-voice), [Drilling Contractor](https://drillingcontractor.org/?p=78246)); **Alan AI with Incture** deployed voice data entry for Murphy Oil in 2020 ([Alan](https://alan.app/blog/alan-ceo-talks-to-incture)).

### E. Research on language models for industrial documents
Studies of retrieval-augmented generation (RAG) over maintenance and safety documents report better grounding than plain models but with real trade-offs: one maintenance-assistant thesis averaged 32.5 s per answer, a 2026 chiller study saw about 28% more latency for 31% fewer hallucinations, and a 2026 industrial benchmark found accuracy dropping with distractors and paraphrased questions, without human-in-the-loop validation ([arXiv 2607.24824](https://arxiv.org/pdf/2607.24824), [arXiv 2511.11847](https://arxiv.org/pdf/2511.11847v2), [ISARC 2025](https://www.iaarc.org/publications/2025_proceedings_of_the_42nd_isarc_montreal_canada/rag-enhanced_safety_information_retrieval_for_construction_integration_of_large_language_models_with_domain-specific_information.html)). Most evaluations are small or preliminary.

## 3. Comparison

As documented in the public material reviewed. ✅ documented, ◐ partial or unclear, — not found.

| Capability | Digital logbooks (j5, ShiftConnector) | Permit / control of work (Sphera, DNV) | AI copilots (Siemens, AVEVA, Cognite, Honeywell) | Voice-first logs (Log Sheet, Shift Pilot) | **Baton** |
|---|---|---|---|---|---|
| Records what the operator reports | ✅ | ◐ | — | ✅ | ✅ |
| Speak a note on a phone | ◐ | — | — | ✅ | ✅ (and in a browser) |
| Checks the report against the plant state at handover by deterministic rules | — | ◐ (permit and SIMOPS conflicts) | — | — | ✅ (R1 to R4) |
| A model can never override a safety verdict | — | n/a | — | — | ✅ (verdict lock, no false all-clear) |
| Interview of the outgoing operator on each open conflict | — | — | — | ◐ (asks on ambiguous equipment) | ✅ |
| Incoming supervisor must read critical items back before transfer | — | ◐ (permit approvals) | — | — | ✅ (gated) |
| Answers workers' questions from procedures, with citations | ◐ (work instructions) | ◐ | ✅ | — | ✅ |
| Answers tailored to the permit being worked, with expired-permit alert | — | ◐ | — | — | ✅ |
| Open conflicts always shown beside an answer | — | — | — | — | ✅ |
| Works as a link in a browser, same code as the phone app | ◐ (web logbook) | ◐ | ◐ | — | ✅ |
| Multilingual voice with asset tags kept intact | ◐ (local languages) | — | ◐ | ◐ | ✅ (question answering verified in English, Tamil and Malay) |
| On-device reading of notes (no connection needed) | — | — | — | ◐ | ✅ on Android; server model on web |
| Live plant telemetry | ✅ (historian links) | ◐ | ✅ | — | ✗ simulated feed (see limits) |
| Proven at scale in plants | ✅ | ✅ | ◐ (pilots) | — | ✗ prototype |

## 4. The gap

The established products record and route information well, and the new copilots answer questions well. In the material we reviewed, no product combines the three things the accident record points at, in one flow:

1. checking the outgoing shift's claims against the plant state by rules a model cannot overrule;
2. making the incoming supervisor confirm the critical items back, so acknowledgement is a recorded act and never a silent default;
3. letting any worker ask the plant's own documents a question, shaped by the permit and equipment they are on, while the open safety conflicts stay on screen.

## 5. Baton's unique selling points

1. **Rules decide, AI reads and explains, people accept.** Safety verdicts come only from deterministic code. Models read notes, retrieve procedures and write briefs, and are barred in code from softening a verdict or claiming work is safe while a conflict is open. Acknowledging is recorded as acknowledged, never resolved.
2. **It checks the claim, not just the note.** "Pump P-201B is isolated" is compared with the plant state at the moment of handover. A mismatch becomes a CRITICAL conflict the same second, before the next shift relies on it.
3. **Accountable transfer.** The outgoing operator is interviewed on each distinct open conflict; the incoming supervisor reads every CRITICAL item back in their own words, with name and time recorded, before responsibility can be transferred. This implements the HSE's two-way, cross-checked handover as software.
4. **Ask the plant's documents, on the spot.** Query mode returns the matching documents in about 0.8 s and a cited answer with ordered steps and stop-work cautions in about 3 to 4 s (measured on the live documents). When the worker selects a permit, the search and answer are about that job, and an expired permit is a red stop notice added by code.
5. **Speak first, in your language.** Voice or typed notes, with asset tags preserved (question answering was verified in English, Tamil and Malay); the on-device model reads notes with no connection on Android, and the server model does the same on the web.
6. **Nothing to install to try it.** The same Flutter code runs as an Android app and as a website, so a judge or a pilot site can use it from a link.
7. **Lightweight and auditable.** One Google Cloud stack (Cloud Run, Pub/Sub, Firestore vector search, Gemini, Google ADK). Every agent step, retrieved record and guardrail trigger is in a trace the supervisor can open in the Control Room. Compared with the 6 to 12 month enterprise rollouts a third-party reviewer reports for some logbook suites, a prototype like this can be adopted in days; that is an architectural advantage, not a measured outcome.

## 6. Limits and what to validate next

- The plant feed and permit register are **simulated**; Baton has not been connected to a historian or permit system, which the established products already do.
- The corpus is 8 demonstration documents. Answer quality on a real, messy document set, with conflicting revisions, is unproven.
- Measurements are from small internal evaluations (12 retrieval questions, 3 handover scenarios, 20-sync load test). There is no field trial and no independent assessment.
- A pilot should measure: conflicts caught that were missed on paper, time to hand over, read-back completion, answer correctness judged by operators, and the rate of "no matching record" responses.
- The natural next step is integration with an existing logbook or permit system rather than replacing it.
