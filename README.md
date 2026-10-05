# Baton: The Shift-Handover Guardian

**Baton** is an AI-powered shift-handover guardian built to eliminate process-safety accidents in continuous manufacturing and industrial environments. This repository contains the MVP architecture developed for the **AI Builder Cup 2026**.

## 🛡️ Core Philosophy
*"Rules decide, Gemini reads and explains, people accept."*

Baton prevents accidents by catching conflicting states (like an active hot-work permit next to an open gas line) during shift handovers. It does this by combining **deterministic safety rules** with **Gemini AI** to parse unstructured logs, permits, and multilingual voice notes.

## 🚀 Architecture overview

- **Backend (`/backend`)**: FastAPI (Python 3.12)
- **AI Agent Engine**: Gemini 3.5 & 3.8 Flash via `google-genai` SDK
- **Safety Engine**: Deterministic Python rules evaluating live plant state against NLP-extracted facts.
- **Deployment Pipeline**: `cloudbuild.yaml` configured for Google Cloud Run continuous deployment.

## 🚀 Features & Implementation Status

| Feature | Component / Service | Status | Description |
| :--- | :--- | :---: | :--- |
| **Speech-to-Text Transcription** | Google Cloud Speech-to-Text V2 (`chirp_3`) | ✅ Completed | Synchronous speech recognition using Chirp 3 in multi-region `us` with auto-decoding and audio duration calculation. |
| **Language Auto-Detection** | Speech-to-Text V2 / Gemini Fallback | ✅ Completed | Automatic source language detection (`languages=auto`) or explicit language code fallback (e.g. `ta-IN`, `en-US`). |
| **Speech Adaptation** | STT V2 Phrase Sets & Prompt Context | ✅ Completed | Equipment/asset tags (`asset_hints` e.g. `P-201B`) passed as phrase adaptation sets with automatic fallback. |
| **Gemini STT Fallback Engine** | Vertex AI Gemini (`gemini-2.5-flash`) | ✅ Completed | Optional transcription engine fallback toggleable via `TRANSCRIBE_ENGINE=gemini`. |
| **Cross-Lingual Translation** | Vertex AI Gemini (`gemini-2.5-flash`) | ✅ Completed | Translates non-English transcripts (e.g. Tamil) to English while strictly preserving asset and equipment identifiers intact. |
| **Authentication & Security** | FastAPI Security Header | ✅ Completed | Guarded by `X-Aegis-Key` header matching `AEGIS_API_KEY`. |
| **In-Memory Rate Limiting** | FastAPI Middleware / Route Guard | ✅ Completed | Token bucket rate-limiting at 30 requests/minute per client IP. |
| **Payload Size Guard** | Request Stream Validation | ✅ Completed | Enforces a strict 10MB maximum file size, returning `413 Payload Too Large`. |
| **Cloud Run Deployment** | GCP Cloud Run (`asia-southeast1`) | ✅ Completed | Fully deployed and serving live traffic with dedicated IAM Service Account (`baton-api`). |
| **CI/CD Pipeline** | Google Cloud Build (`cloudbuild.yaml`) | ✅ Completed | Automated container build and deployment to Artifact Registry and Cloud Run. |
| **Unit Test Coverage** | Pytest Test Suite (`tests/test_transcribe.py`) | ✅ Completed | 9/9 passing tests with mocked Google Cloud and Vertex AI clients. |
| **Sandglass Document Grounding** | Cloud Run (`/sandglass`) | ✅ Completed | Document search (BM25 + Vertex AI embeddings) + Gemma/Gemini citation answers. |

---

## 🎙️ Speech Transcription API (`/api/transcribe`)

### Live Endpoint
* **Base URL**: `https://baton-api-545013329202.asia-southeast1.run.app`
* **Path**: `POST /api/transcribe`
* **Auth Header**: `X-Aegis-Key: <AEGIS_API_KEY>`

### Request Parameters (`multipart/form-data`)
| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `audio` | File | Yes | Audio recording (`.wav`, `.m4a`, `.mp3`, max 10MB). |
| `client_request_id` | String | No | Client-supplied tracing identifier. |
| `languages` | String | No | Comma-separated BCP-47 language codes or `auto` (default). |
| `asset_hints` | String | No | Comma-separated equipment tags (e.g., `P-201B, TK-104`). |

### Response Schema (`200 OK`)
```json
{
  "request_id": "flutter-client-01",
  "text": "Pump P201B is vibrating heavily and the seal looks wet.",
  "language": "en",
  "english_text": null,
  "engine": "chirp3",
  "model": "chirp_3",
  "audio_seconds": 1.62,
  "latency_ms": 3558,
  "no_speech": false
}
```

### Measured Latency (Live Cloud Run)
| Test Audio File | Duration | Detected Language | Cloud Run Latency | Transcription Output |
| :--- | :---: | :---: | :---: | :--- |
| **[Baton-Test-English.m4a](file:///Users/kesevan/Desktop/AIbuilder/Ethernauts/baton-mvp/backend/Baton-Test-English.m4a)** | 1.62s | `en` | **~3.55s** | *"Pump P201B is vibrating heavily and the seal looks wet."* |
| **[Baton-Test-Tamil.m4a](file:///Users/kesevan/Desktop/AIbuilder/Ethernauts/baton-mvp/backend/Baton-Test-Tamil.m4a)** | 1.88s | `en` / `ta-IN` | **~3.97s** | *"pump P201B"* |

---

## 💻 Local Development

1. **Set up the virtual environment**:
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure environment**:
   ```bash
   cp .env.example .env
   ```

3. **Run the Backend locally**:
   ```bash
   uvicorn app.main:app --reload --port 8080
   ```

4. **Run Unit Tests**:
   ```bash
   PYTHONPATH=. pytest tests/test_transcribe.py
   ```

---

## ☁️ Google Cloud Deployment

Deploy directly using `gcloud` or through Cloud Build:
```bash
gcloud run deploy baton-api \
  --source ./backend \
  --region asia-southeast1 \
  --platform managed \
  --allow-unauthenticated \
  --service-account baton-api@ai-builder-cup-2026-509818.iam.gserviceaccount.com \
  --set-env-vars GOOGLE_CLOUD_PROJECT=ai-builder-cup-2026-509818,TRANSCRIBE_ENGINE=chirp3,SPEECH_LOCATION=us,GEMINI_MODEL=gemini-2.5-flash,AEGIS_API_KEY=dev-key
```

---

## 🔍 Sandglass: document-grounded answers for on-device Gemma (`/sandglass`)
A separate, self-contained Cloud Run service. The on-device Gemma model sends short questions over a constrained link. Sandglass searches the document corpus (rule-based expansion + BM25 + Vertex AI embeddings), has Gemini answer with verified citations, and returns a compact, byte-budgeted answer with a calibrated confidence.
Deploy with `PROJECT_ID=... ./sandglass/scripts/deploy.sh`. See [sandglass/README.md](sandglass/README.md).

