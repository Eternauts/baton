# Baton Sandglass

The cloud half of a **sandglass architecture**. An on-device Gemma model, with limited compute and on a slow or
intermittent link, sends a short question. This Cloud Run service does the heavy work: it searches the document
corpus, has Gemini on Vertex AI reason over the passages, verifies every claim against the source text, and
calibrates a confidence score. It then returns a small answer that fits a byte budget, which Gemma can act on.

```
  device (wide: UX)        link (narrow)                   Cloud Run (wide: compute)
 ┌──────────────┐   ~150 B question  ┌───────────────────────────────────────────────────────────┐
 │  Gemma       │ ─────────────────▶ │ 1 rules     tag canonicalisation, aliases, synonyms        │
 │  on device   │                    │ 2 retrieve  BM25 + Vertex embeddings, RRF, authority boost │
 │              │ ◀───────────────── │ 3 gate      retrieval confidence < floor → "no answer",    │
 │  decides on  │   200-1500 B       │             no Gemini call                                 │
 │  d + c       │   answer + conf    │ 4 Gemini    structured JSON, cites [S#] with verbatim quote│
 └──────────────┘   (gzip, ETag)     │ 5 verify    every quote checked against its passage        │
                                     │ 6 calibrate retrieval × grounding × model → c              │
                                     │ 7 fit       deterministic trim to the device's byte budget │
                                     └──────────────────────────┬────────────────────────────────┘
                                                                │
                                          GCS corpus + index cache · Secret Manager keys
```

**Why the confidence is meaningful.** Gemini's own estimate is only one of three inputs:

| Signal | Computed by | Meaning |
|---|---|---|
| `retrieval` | rules, no model | share of the question's terms and equipment tags found in the top passages, plus embedding similarity |
| `grounding` | string check, no model | share of Gemini's claims whose quote appears (near-)verbatim in the cited passage |
| `model` | Gemini | its probability that the answer is correct and complete |

`c = 0.45·model + 0.35·grounding + 0.20·retrieval`, capped at 0.5 when fewer than half the claims are grounded.
Claims that fail verification are never sent to the device. An answer the model invents cannot reach Gemma with
high confidence.

## API

All `/v1/*` routes require the `X-API-Key` header. Responses are gzip-compressed and carry an `ETag`. To
revalidate a repeated question, send `If-None-Match`; an unchanged answer comes back as `304` with no body.

### `POST /v1/ask`

```json
{"q": "Can hot work resume on the stripper platform?",
 "ctx": {"state": {"GD-311": "BYPASSED"}, "unit": "Unit 3"},
 "budget": 600, "lang": "en", "k": 6}
```

| field | default | |
|---|---|---|
| `q` | required | question, at most 1000 chars |
| `ctx` | none | live state the device knows (`tags`, `state`, `unit`, `note`). Gemini applies the procedures to it; it is never cited as a source |
| `budget` | 1200 | max response bytes before gzip (200-16000). Also caps answer length |
| `lang` | `en` | answer language. Quotes stay in the source language |
| `k` | 6 | passages given to Gemini (1-12) |

Compact response (the default):

```json
{"v":"352d75f7a4","d":"C","c":0.84,"g":"g","t":2140,
 "a":"No. On the stripper platform hot work stays stopped until GD-311 is back in service and tested.",
 "f":[["Bulletin 2026-07 forbids resuming while GD-311 is bypassed, even with a portable monitor.",0.88,[0]],
      ["SOP-GD-03 would allow resuming with a continuous monitor and gas watcher.",0.8,[1]]],
 "s":[["BUL-2026-07#2","Requirement",1.0],["SOP-GD-03#2","2 Compensating measures",0.82]],
 "x":"Keep hot work stopped; restore and test GD-311.",
 "w":"Bulletin 2026-07 supersedes SOP-GD-03 section 2 on the stripper platform."}
```

| key | meaning |
|---|---|
| `v` | corpus version. Drop any device-side cache when it changes |
| `d` | decision: `A` answer, `P` partial or low confidence, `N` no answer in corpus, `C` sources conflict |
| `c` | confidence in `a`, 0-1 (always 0 for `N`) |
| `a` | answer |
| `f` | facts: `[text, confidence, [source indexes]]`, all verified against the source |
| `s` | sources: `[chunk id, section, relevance]` |
| `x` | suggested next action · `w` warning or conflict note |
| `g` | generator: `g` Gemini, `e` extractive fallback (model unavailable), `n` none |
| `t` | server time in ms |

When the response is over budget, fields are trimmed in this order: extra facts, section labels, long `x`/`w`,
the last fact, the answer past 160 characters, extra sources, then `x`/`w`/`s`. `v`, `d`, `c` and `g` always
survive. `?view=full` returns the verbose result with snippets and the confidence breakdown, for debugging.

### Other routes

| route | purpose |
|---|---|
| `POST /v1/search` | retrieval only, no Gemini call: `{"v","rc","r":[[id, section, relevance, snippet]]}`. For when the device wants raw passages |
| `GET /v1/corpus` | corpus version, document and chunk counts, whether dense retrieval is on |
| `POST /v1/admin/reindex` | `X-Admin-Key`: rebuild the index on this instance now |
| `GET /health` | liveness, no key |

### Using it from the device (Gemma side)

A suggested policy, kept on the device because it is cheap:

- `d == "A"` and `c >= 0.75`: act on `a` and show `x`.
- `d == "P"`, or `A` with lower `c`: show `a` as guidance and ask the operator to confirm.
- `d == "C"`: show `w` and escalate to the supervisor. Never auto-act.
- `d == "N"`: say the procedures do not cover it. Do not let Gemma answer from its own knowledge.
- `g == "e"`: the cloud model was unavailable. Treat the result as excerpts, not as an answer.
- On a weak link, send `budget: 300`. On a good link, send 1200 or more and use `f` for explanations.

## Deploy to Google Cloud

```bash
PROJECT_ID=my-project ./scripts/deploy.sh
```

The script is idempotent. It enables the APIs (Cloud Run, Vertex AI, Cloud Storage, Secret Manager, Cloud Build,
Artifact Registry) and creates a least-privilege service account (`aiplatform.user`, `logWriter`, object admin on
the corpus bucket only). It also creates the corpus bucket and uploads the sample corpus if the bucket is empty,
creates the device and admin keys in Secret Manager (printed once), deploys from source, and runs a smoke test.

For CI, `cloudbuild.yaml` tests, builds, pushes and rolls out a new image while keeping the env vars and secrets
that `deploy.sh` set.

**Managing documents.** Copy `.md`, `.txt`, `.json` or `.pdf` files into `gs://<bucket>/corpus/`. Optional
`key: value` front matter between `---` lines sets `title`, `type` (`SOP`, `BULLETIN`, `MANUAL`, `NOTE`, ...) and
`revision`. `corpus/rules.json` holds the deterministic rules: tag aliases, synonym groups and per-type authority
boosts. Every instance checks the corpus fingerprint at most every `BATON_REFRESH_S` seconds while it is serving
traffic. If anything changed, it rebuilds once and caches the new index in `gs://<bucket>/index/`, so other and
later instances load it without re-embedding.

## Local development

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
# with Vertex AI: gcloud auth application-default login
GOOGLE_CLOUD_PROJECT=my-project .venv/bin/uvicorn app.main:app --reload --port 8080
```

Without credentials the service still runs. Retrieval is lexical only, and `/v1/ask` returns extractive answers
marked `g: "e"`.

## Configuration

| env var | default | |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | | project for Vertex AI |
| `GOOGLE_CLOUD_LOCATION` | `global` | Gemini endpoint |
| `BATON_ANSWER_MODELS` | `gemini-3.8-flash,gemini-2.5-flash` | fallback chain, first success wins |
| `BATON_THINKING_LEVEL` | `LOW` | for Gemini 3.x |
| `BATON_EMBED_MODEL` / `_DIM` / `_LOCATION` | `text-embedding-005` / 768 / `asia-southeast1` | dense retrieval |
| `BATON_USE_EMBEDDINGS` | `true` | `false` for lexical-only retrieval |
| `BATON_CORPUS_URI` | bundled `corpus/` | folder or `gs://bucket/prefix` |
| `BATON_INDEX_URI` | none | index cache location (folder or `gs://`) |
| `BATON_REFRESH_S` | 300 | corpus change check interval, 0 disables |
| `BATON_ANSWER_THRESHOLD` | 0.65 | below this, `A` becomes `P` |
| `BATON_RETRIEVAL_FLOOR` | 0.2 | below this, Gemini is skipped and `N` returned |
| `BATON_LLM_TIMEOUT_S` | 25 | total budget across the model chain |
| `BATON_API_KEYS` / `BATON_ADMIN_KEY` | none | from Secret Manager on Cloud Run. Empty keys leave the API open (dev only) |

## Limits and next steps

- The index lives in memory on each instance. That is fine up to tens of thousands of chunks. Beyond that, move
  retrieval to Vertex AI Search or Vector Search and keep steps 1 and 3-7 unchanged.
- Confidence weights and thresholds are set by judgement, not fitted to data. Calibrate them on a labelled
  question set before relying on `c` for automatic actions.
- The response cache is per instance. Use Memorystore if hit rates matter across instances.
- API keys suit a pilot. For a fleet, issue per-device keys or put API Gateway / Apigee in front.
- The sample corpus is fictional (Kestrel Bay Demo Plant) and is not real safety guidance.
