# Baton backend: agents, pipeline and how to run them

Baton checks shift handovers at a process plant. An operator's logged facts are compared with the plant state,
and the incoming supervisor gets a cited brief. The one rule that shapes everything below:

> **Rules decide, Gemini reads and explains.** Safety verdicts come only from deterministic code (`app/rules.py`).
> Models retrieve, explain, brief and answer. A model can add concerns; it can never remove, soften or contradict a
> rule verdict, and it can never say a conflict is clear while one is open.

Everything on this page is implemented and was verified against the deployed Cloud Run services
(project `ai-builder-cup-2026-509818`, region `asia-southeast1`).

## 1. Architecture

```
Android app ──batch_sync──▶ baton-api (FastAPI, Cloud Run)
                              │ 1. facts + rules R1–R4 (deterministic, app/safety.py)   ← response returns here (~0.3 s)
                              │ 2. save session + event to Firestore
                              │ 3. publish "handover.synced" (ids only, no transcripts)
                              ▼
                        Pub/Sub topic baton-handover-events ──push (OIDC)──▶ baton-agents (Cloud Run, private)
                              │ 5 failed attempts                               │ claim agent_runs/{run} (idempotent)
                              ▼                                                 ▼
                  baton-handover-events-dlq (+ hold sub)        ADK HandoverPipeline (section 2)
                                                                   │
                         Firestore: knowledge_chunks · handover_capsules · handover_briefs · device_updates · agent_runs(+steps)
                                                                   │
Dashboard (/dashboard) ◀── /api/v1/dashboard/stream (attaches the brief) ──┘
Ask the logs:  POST /api/v1/ask  (baton-api, one ADK agent, section 4)
Device alerts: GET  /api/v1/devices/{id}/updates
```

Two Cloud Run services share one container image; `baton-agents` starts `app.worker_main:app` instead of `app.main:app`.

## 2. The handover pipeline (`app/agents/pipeline.py`)

An ADK `SequentialAgent`. Model stages run inside a `GuardedStage` that validates output in code (section 5).

| # | Stage | Kind | Model | What it does |
|---|---|---|---|---|
| 1 | Intake | custom, no model | – | Store capsules, chunk, embed, write `knowledge_chunks`; record `devices/{id}` |
| 2a | SOPRetriever | LLM + tool | fast (`GEMINI_FAST_MODEL`) | Writes ≤2 natural-language queries, calls `search_sops`, picks relevant chunks |
| 2b | HistoryRetriever | LLM + tool | fast | Calls `search_history` per asset (other shifts, 72 h), picks relevant events |
| 2c | ContextAssembler | custom | – | Turns the selections into prompt text; only chunks actually retrieved |
| 3 | RulesGate | custom, no model | – | Runs R1–R4 via `evaluate_rules`; reads plant feed; lists unit conflicts. Verdicts are final |
| 4 | SafetyCrossCheck | LLM | main (`GEMINI_MODEL`) | Explains each verdict with SOP citations; may add *advisory* items (never CRITICAL) |
| 5 | Briefing | LLM | main | Writes the incoming-shift brief |
| 6 | Distill | custom | – | Saves `handover_briefs/{id}` and the short `device_updates/upd-{id}` |

2a and 2b run in parallel. Structured outputs are Pydantic models (`app/agents/schemas.py`): `Retrieval`,
`SafetyAssessment`, `ShiftBrief`, `DeviceUpdate`.

### Tools (`app/agents/tools.py`, bound per run by `make_tools(run_ctx)`)

| Tool | Returns |
|---|---|
| `search_sops(query, asset_tag="")` | ≤4 SOP/bulletin/manual chunks (id, title, ≤500 chars, distance, `supersedes`) |
| `search_history(query, unit="", asset_tag="", since_hours=72)` | ≤4 earlier-shift chunks; the current handover is excluded |
| `get_scada(asset_tags)` | Readings from the **simulated** plant feed (`app/plant_data.py`) |
| `evaluate_rules(handover_id)` | Rule verdicts R1–R4 with evidence (same code as `batch_sync`) |
| `get_handover(handover_id)` | Facts and interview answers |
| `get_open_conflicts(unit)` | Unresolved conflicts in the last 24 h: rule, severity, asset, status (OPEN / ACKNOWLEDGED) |

Every search result is recorded in the run so citations can be checked against what was really retrieved.

### Time budgets and fallbacks

Pipeline 100 s · retrievers 25 s · main-model stages 35 s (must stay under the worker's 120 s Cloud Run timeout and 120 s ack
deadline). A stage that fails or runs out of time is replaced by a deterministic version built from the rule verdicts, so the
verdicts always reach the supervisor. Malformed JSON is retried once. Only infrastructure failures before the agents (for
example a missing handover) return 5xx and are retried by Pub/Sub.

## 3. Data model (Firestore, native mode)

| Collection | Key | Purpose |
|---|---|---|
| `batch_sync_events` | handover id | Dashboard ledger entry per sync (capsules, conflicts, summary) |
| `handover_sessions` | handover id | Facts and conflicts per sync |
| `handover_capsules` | capsule uuid | One record per capsule, written by Intake. Seeded demo records carry `seeded: true` |
| `knowledge_chunks` | sha256(type+source+index+text) | Vector store. Fields: `source_type` SOP/HANDOVER/OBSERVATION, `source_id`, `title`, `text` (<1,500 chars), `language`, `unit`, `asset_tags`, `created_at`, `embedding` (768-d, `gemini-embedding-001`), `doc_type`, `revision`, `supersedes`, `seeded` |
| `agent_runs` | `run-<handover>` or `ask-<id>` | Run record: status, timing, models, tokens, `guardrails_triggered`, `attempts`. Subcollection `steps/{seq}` has one document per agent start/end, tool call/result, model call and guardrail trigger |
| `handover_briefs` | handover id | The brief, citation titles, model, `guardrail_status` (`passed` / `modified` / `fallback`) |
| `device_updates` | `upd-<handover>` | Short alert for devices: severity, alerts, required actions, summary (<400 chars) |
| `devices` | device id | `unit` and `last_sync`, used to find a device's updates |

Vector indexes (`firestore.indexes.json`, recreate with `scripts/create_indexes.sh`): vector-only; with `source_type`, `unit`,
`asset_tags`; `unit`+`source_type`; `unit`+`asset_tags`; plus `device_updates` by `unit` and `created_at`.

## 4. Ask the logs and device updates

`POST /api/v1/ask` (header `X-Aegis-Key`): `{question, unit, asset_tag?, language?, device_id?}` →
`{answer, answer_language, citations[], rule_verdicts[], confidence_note, run_id, model, latency_ms}`.

One ADK agent with `search_sops`, `search_history`, `get_scada`, `get_open_conflicts`. It answers only from retrieved
evidence, in the question's language (verified for English, Tamil and Malay). Code, not the model, builds `citations` (only chunks
retrieved in the run), supplies `rule_verdicts` (the unit's open conflicts, quoted unchanged) and appends any open conflict the
answer left out. Off-topic questions are declined with no citations. A 20 s budget returns retrieved records instead of an
answer if the model is slow or fails. 500-character question limit; 30 requests/minute/IP.

`GET /api/v1/devices/{device_id}/updates?since=<ISO>[&unit=]` returns up to 20 updates for the device's unit, newest first.

Read endpoints behind the dashboard (all need `X-Aegis-Key`; none returns embeddings or transcripts):
`GET /api/v1/agents/runs?limit=` (recent runs), `GET /api/v1/agents/runs/{run_id}` (run, ordered steps with retrieved chunks resolved to
titles and dates, and the brief), `GET /api/v1/agents/chunks/{chunk_id}` (the text of a cited record).

## 5. Guardrails (`app/agents/guardrails.py`, all deterministic, all logged in the trace)

1. **Verdict lock.** Every rule verdict must appear with the same rule and at least its severity. Violation: the model output is
   discarded and the deterministic version is used.
2. **No false all-clear.** While any conflict is OPEN or ACKNOWLEDGED, text is rejected if it *claims* things are fine
   ("interlock is clear", "all clear", "issue is resolved", "safe to proceed", "no further action required"...). Conditionals and
   negations are allowed ("must be resolved before work resumes", "cannot confirm it is safe"). Acknowledged is not resolved:
   `clear_alert` records ACKNOWLEDGED, and nothing in the system produces RESOLVED.
3. **Citations must exist.** Any citation not retrieved in this run is stripped.
4. **Advisory cap.** Model-added items are capped at WARNING; only rules raise CRITICAL.

`scripts/live_guardrail_check.py` proves 1 and 2 against real model output (the model is told to misbehave).

## 6. Configuration

All model IDs and locations come from environment variables (`app/config.py`); nothing is hardcoded.

| Variable | Live value | Notes |
|---|---|---|
| `GEMINI_MODEL` / `GEMINI_LOCATION` | `gemini-3.5-flash` / `asia-southeast1` | Reasoning stages, transcription, Ask. Regional endpoint: stable latency |
| `GEMINI_FAST_MODEL` / `GEMINI_FAST_LOCATION` | `gemini-3.5-flash-lite` / `global` | Retrievers; Flash-Lite is served only from `global` |
| `EMBEDDING_MODEL` / `EMBEDDING_LOCATION` / `EMBEDDING_DIM` | `gemini-embedding-001` / `asia-southeast1` / `768` | Vectors are L2-normalised |
| `SEARCH_MAX_DISTANCE` | `0.42` | Cosine distance cut-off, from measured data (relevant ≤0.36, unrelated ≥0.46) |
| `AEGIS_API_KEY` | Secret Manager `aegis-api-key` | Required on transcribe, clear_alert, ask, device updates |
| `PUBSUB_TOPIC`, `LEGACY_BRIEF_INLINE`, `PIPELINE_AGENTS_ENABLED` | topic id, `false`, `true` | Kill switches: set the last to `false` for intake-only |

Secrets and audio are never logged. Logs carry ids, counts, latencies and status codes.

## 7. Tests and evaluation

```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
pytest -q                      # 161 tests, no network: Google clients are mocked, ADK runs on a scripted fake model (tests/fake_llm.py)
```

Against the deployed service (needs gcloud credentials; uses the API key from Secret Manager; cleans up after itself):

```bash
export PYTHONPATH=. GOOGLE_CLOUD_PROJECT=ai-builder-cup-2026-509818 GEMINI_MODEL=gemini-3.5-flash GEMINI_FAST_MODEL=gemini-3.5-flash-lite \
  GEMINI_LOCATION=asia-southeast1 GEMINI_FAST_LOCATION=global EMBEDDING_MODEL=gemini-embedding-001 EMBEDDING_LOCATION=asia-southeast1 EMBEDDING_DIM=768
python -m eval.run_eval  --url https://baton-api-545013329202.asia-southeast1.run.app [--reseed]
python -m eval.load_test --url https://baton-api-545013329202.asia-southeast1.run.app          # 20 syncs in ~1 minute
python -m scripts.live_guardrail_check                                                             # real-model guardrail proof
```

`eval/golden.json` holds 12 questions with expected sources (English, Tamil, Malay; procedures, a superseding bulletin, history),
2 off-topic questions that must be declined, and 3 handover scenarios with expected verdicts. Seeded demo handovers age out of the
72-hour history window: run `--reseed` (or `python -m scripts.seed_handovers --cleanup` then without `--cleanup`) before a demo.

### Measured results (final build, live service)

| Measure | Result |
|---|---|
| Retrieval: expected source in top 6 | 12/12 |
| Answer cites an expected source | 12/12 |
| Citation validity (chunk exists, source and title match) | 12/12 |
| Off-topic questions declined cleanly (no citations, no verdicts) | 2/2 |
| Rule-verdict preservation in briefs | 3/3 (100%) |
| Ask latency | median 6.4 s, p90 11.5 s, max 14.0 s |
| Pipeline latency (single runs) | median 11.9 s; under load median 7.9 to 8.5 s, p90 12.9 to 13.8 s, max 22.9 to 32.4 s |
| Load: 20 syncs in a minute | 20/20 HTTP 200 (median 0.28 s); 20/20 runs finished; 0 duplicates; 0 lost; 0 dead letters; 0 error logs. A second run: same. In one of two runs, one run used the fallback brief because a retriever exceeded its 25 s budget (cause not identified) |

## 8. Deploy and roll back

```bash
backend/scripts/deploy.sh canary     # build, deploy baton-api at 0% traffic, tagged "canary"
backend/scripts/deploy.sh agents     # deploy baton-agents from the same image as the latest baton-api revision
gcloud run services update-traffic baton-api --region asia-southeast1 --to-revisions <revision>=100   # promote BY NAME
```

Roll back by sending traffic to the previous revision. `scripts/setup_pubsub.sh` recreates the topics, subscriptions, service accounts
and IAM; `scripts/create_indexes.sh` recreates the Firestore indexes. Both are safe to read before running: they show every resource.

## 9. Known limitations

- **The plant feed is simulated** (`app/plant_data.py`), not live telemetry, and the dashboard says so.
- **Rule R3 never fires** on the simulated feed: `ESDV-301` has status `BYPASS` but R3 matches `BYPASSED`. Fixing it would make
  every sync CRITICAL because the bypass is permanent in the feed. Rules R1, R2 and R4 are covered by the scenarios.
- **R4 (expired permit) is always open** in the simulated feed, so it appears in every brief and in every in-scope answer.
- **Open conflicts are unit-wide**, not per asset, because stored conflicts carry no asset field.
- **The appended "Open conflicts…" line is English** even in Tamil or Malay answers.
- **Name scrubbing is best effort.** Names inferred from the operator id and "by <Name>" patterns are removed from stored text; other names in free text may remain.
- **Language detection** is script based: Malay is not told apart from English.
- A redelivered message that arrives while a run is still in progress is acknowledged and skipped; if that instance were killed, the pipeline brief for that handover would be missing (the sync response still carried the verdicts).
- Model latency has an occasional tail (single stages up to about 20 s); time budgets turn it into a deterministic fallback, never a missing verdict.
- No verified pricing for the Gemini 3.5 models was available. Per pipeline run: about 11 to 15k input and 1 to 2k output tokens; per Ask: about 3 to 7k input tokens.
- The Android app does not yet read the device-updates endpoint.
- The dashboard stream takes about 2 s per refresh (it queries Cloud Logging, cached for 5 s), so it updates every few seconds, not every 2 s.
- `app/templates/dashboard.html` is an old unused copy of the dashboard; the live page is `app/static/dashboard.html`.
- `clear_alert` still sets the dashboard event's `has_critical_conflict` flag to false so the banner can be dismissed; the conflict itself stays ACKNOWLEDGED (open), but that flag no longer says so.

## 10. Control Room dashboard (`app/static/dashboard.html`)

One self-contained page served by `baton-api` at `/dashboard` (no build step, no Tailwind or icon CDN; icons are an inline sprite from
lucide-static, ISC). Light theme only, with all colors, radii and shadows defined once as CSS variables at the top of the file.

| Screen | Shows |
|---|---|
| Overview | Incident banner, four KPIs, AI executive brief, plant feed, recent events |
| Living Architecture | Seven components with computed connectors, state colors, and an inspector (select a node or press Enter on it) |
| Telemetry | Sensor cards with filters, and work permits (a simulated feed: no per-sensor timestamps or history, so no trends are drawn) |
| Audit Trail | Searchable events, incidents, batch syncs, persistence and revisions, with expandable JSON |
| Agent Trace | Per-run timeline (agents, tool calls, retrieved records, rule verdicts, guardrails, per-step latency) and Ask the logs |
| Debug Console | Endpoint health and request telemetry measured from real traffic |

Behavior worth knowing:
- **Every value is derived from the API.** There is no sample data fallback; empty, loading, error, disconnected and stale states are shown.
  Connection state comes from the poll (green only if the last poll succeeded within 7 s).
- **Packets move only for real events.** A new event in the stream animates the sync path; once the supervisor key is entered, each recorded
  agent step of the followed run animates once (retrieval, rules, model calls, guardrails, saves). Nothing runs on a timer. Selecting an old run
  paints its final state without replaying it. With `prefers-reduced-motion`, wires highlight briefly instead of moving.
- **Supervisor key.** Kept in `sessionStorage` for the tab. It unlocks Agent Trace, Ask the logs and Acknowledge. The stream stays readable without it.
- **Acknowledge never resolves anything.** It calls `clear_alert`, which records ACKNOWLEDGED. The banner then reads "Acknowledged · still open",
  the KPI keeps counting the incident, and nothing says resolved, cleared or transfer released. There is no resolve action because the system
  has no verified way to resolve a conflict.
- **Demo actions** (actions menu) send real syncs from device `dashboard-demo`; they create real records and agent runs.
- Accessibility: keyboard-reachable nodes and menus, focus moved into dialogs and restored, Escape closes them, status never relies on color
  alone (every chip has an icon and a word), text contrast at least 4.5:1, layout verified at 390, 820 and 1440 px with no horizontal overflow.

The page was verified in headless Chromium against the deployed service: unlock, trace, citation modal, Ask, incident drawer, keyboard
selection (25 checks); idle topology then a real sync, packets, stage progress and the finished trace (9); the Acknowledge flow with a wrong
and a right key (9). The scripts are not in the repo (they need cloud credentials and a browser).

## 11. The Flutter app as a website (`aegis_flow/`)

One codebase builds Android and the browser version, so a change to the app reaches both. The website is its **own Cloud Run
service, `baton-app`** (static files behind nginx). It is separate from `baton-api`, which serves the API and the supervisor
Control Room at `/dashboard`. Both read and write the same backend data, so a note submitted in the app appears in the dashboard.

| Service | What | Deploy |
|---|---|---|
| `baton-api` | API + `/dashboard` | `backend/scripts/deploy.sh canary`, then `promote` |
| `baton-agents` | Pub/Sub worker (agents) | `backend/scripts/deploy.sh agents` |
| `baton-app` | The Baton website | `aegis_flow/scripts/deploy_web.sh` (builds and deploys; static, no canary needed) |

One-time setup for the website: `backend/scripts/setup_web.sh` (creates the demo key secret).

What differs on the web (all behind `lib/core/platform/platform_support.dart` and `kIsWeb` guards):
- **Reading notes:** there is no on-device Gemma in a browser, so the app asks `POST /api/v1/extract` (fast model, same prompt and schema;
  the app validates the answer with the same code). Phones without Gemma installed use it too, whenever online mode is on.
- **Voice:** the browser records webm/opus, uploaded as bytes to `/api/transcribe` (the server detects the format).
- **Key:** the page ships with `AEGIS_DEMO_KEY`, which opens the app endpoints only. Acknowledging an alert and reading agent
  traces need the supervisor key (`AEGIS_API_KEY`). Never build a public web app or APK with the supervisor key.
- **Cross-site calls:** the site and the API are different origins; `baton-api` allows them through CORS (the key travels in the `X-Aegis-Key` header).
- **Load time:** built with `--no-web-resources-cdn` (everything comes from `baton-app`, no third-party CDN), nginx gzip-compresses
  it (about a third of the raw size), and files are served with `Cache-Control: no-cache` plus `--pwa-strategy=none`, so a redeploy reaches visitors on their next load.
- **Device ids:** web visitors register as `web-<id>`, Android phones as `android-<id>`.

## 12. Query mode: answers from the documents, on the spot (`app/agents/query.py`)

For a worker with a doubt, or working under a permit. It is deliberately not an agent loop, so it is fast: the **documents come back first**
(`POST /api/v1/search`, about 0.8 s, vector search only), then **one model call** writes the answer (`POST /api/v1/query`, about 3 to 4 s on the live documents).

| Endpoint (app key) | Returns |
|---|---|
| `GET /api/v1/permits` | The active permits (from the simulated permit register): id, type, title, status, expired |
| `POST /api/v1/search` `{query, permit_id?}` | The matching documents, grouped, each with its best section and a snippet |
| `POST /api/v1/query` `{question, unit, asset_tag?, permit_id?, language?}` | `answer`, `steps` (ordered), `cautions`, `follow_ups`, `citations` (with snippets), `rule_verdicts`, `permit`, `permit_alert`, `confidence_note`, `fallback`, `latency_ms` |
| `GET /api/v1/docs` / `GET /api/v1/docs/{chunk_id}` | The searchable documents / one section in full, so a worker can read the exact wording |

How it stays trustworthy (same guardrails as Ask, applied to every string in the answer, steps and cautions):
- Retrieval, open conflicts and plant readings are fetched by code in parallel; the model sees only those sources and is told to say "no matching record" rather than guess.
- **Code supplies the safety facts:** `rule_verdicts` are the unit's open conflicts, quoted unchanged (the app shows them in their own strip); an **expired permit** adds a `permit_alert` regardless of what the model wrote.
- No claim that work is safe or clear while a conflict is open (a violation withholds the answer and shows the retrieved records instead); citations must have been retrieved; raw chunk ids are stripped.
- A selected permit steers the search (its title and a per-type topic list, `PERMIT_TOPICS`) and is part of the prompt, so "what exactly do I need to do?" is answered for that job.
- A model failure, a timeout (14 s) or bad JSON (retried once) falls back to the retrieved records. Runs are traced like Ask runs (`ask-` ids), so they appear in the dashboard's Agent Trace.

The assistant can only answer from what is ingested: add documents with `scripts/ingest_sops.py` (the corpus bucket, `corpus/*.md`). The demo corpus is 8 documents.
