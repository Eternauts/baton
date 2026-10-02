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

## 💻 Local Development

1. **Set up the virtual environment**:
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-dev.txt
   ```

2. **Run the Backend locally (Dev Mode)**:
   ```bash
   uvicorn app.main:app --reload --port 8080
   ```
   *Visit `http://localhost:8080/docs` to see the interactive API documentation.*

## ☁️ Google Cloud Deployment
This repository is configured to auto-deploy to **Google Cloud Run** using Cloud Build on every push to the `main` branch. 
See the `cloudbuild.yaml` file for the exact CI/CD pipeline steps.
