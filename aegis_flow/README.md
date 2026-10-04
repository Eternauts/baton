# AEGIS Flow: Offline-First AI for Zero-Loss Shift Handovers in Offshore Oil & Gas

A Flutter mobile/tablet industrial application implementing a hybrid edge-cloud multi-agent system for shift handovers in hazardous offshore environments (ATEX Zone 2).

---

## The Problem Solved

* **40% of process safety accidents** occur during shift handovers (e.g., Piper Alpha, Texas City).
* Handovers represent **< 5% of daily operational time**, yet over **50% of manual handover records lack critical context**.
* Offshore rigs frequently suffer from **zero or intermittent satellite connectivity**.
* Field crews are **multilingual** (Tamil, Malay, Hindi, Mandarin, Spanish, English), leading to lost nuances in verbal communication.
* Disconnect between field observations (e.g., *“P-201B vibrating heavily, seal wet”*) and control room SCADA readings (which may still show normal sensor readings before catastrophic failure).

---

## Architecture Overview

```
                      +---------------------------------------+
                      |   RUGGEDIZED TABLET (ATEX Zone 2)     |
                      |                                       |
                      |  1. FIELD CAPTURE                     |
                      |     Voice / Text Multilingual Input   |
                      |                    │                  |
                      |                    ▼                  |
                      |     Gemma 2B INT4 (On-Device Edge)    |
                      |     Offline Structured JSON Extract   |
                      |                    │                  |
                      |                    ▼                  |
                      |     Local SQLite Buffer (Zero Loss)   |
                      +────────────────────┬──────────────────+
                                           │
                        WorkManager HTTPS  │ Sync (when online)
                                           ▼
                      +───────────────────────────────────────+
                      |       CLOUD AGENT & STORAGE LAYER     |
                      |                                       |
                      |  2. Google Cloud Storage & Cloud Run  |
                      |     System of Record & Audit Trail    |
                      |                    │                  |
                      |                    ▼                  |
                      |  3. Gemini Cloud Agent + Mock SCADA   |
                      |     Discrepancy Detection Alerts      |
                      +───────────────────────────────────────+
                                           ▲
                                           │
                      +────────────────────┴──────────────────+
                      |   INCOMING / ON-SHIFT OPERATOR        |
                      |                                       |
                      |  4. GEMMA MULTILINGUAL ASSISTANT      |
                      |     Q&A in Native Language            |
                      |     Cited SOPs & Shift Handover Logs  |
                      +---------------------------------------+
```

---

## Key Features

1. **1. Field Capture**:
   - Single-tap or hold-to-talk voice recording simulation.
   - Text input with one-tap preset test observations across multiple languages (English, Malay, Tamil).
   - On-Device Gemma 2B INT4 extraction outputting structured JSON (`tag`, `anomaly`, `severity`, `unit`, `actionRequired`).
   - Zero-loss buffering to local storage.

2. **2. Pending Records & Sync Queue**:
   - Status indicators: `Offline Queue` vs `Cloud Synced`.
   - Filter tabs: `All`, `Offline`, `Synced` (matching the architecture poster).
   - Instant "Sync Pending Records" action flushing records to Google Cloud Storage.
   - High-visibility **SCADA Discrepancy Alert Cards** (e.g., P-201B vibration high per field log, but SCADA shows normal).

3. **3. Gemma Multilingual Shift Assistant**:
   - Multilingual conversational assistant supporting English, Tamil, Malay, Hindi, Mandarin, Spanish.
   - RAG reasoning grounding responses in both **Active Shift Handover Logs** and **Standard Operating Procedures (SOPs)**.
   - Highlights critical equipment hazards and active Lockout/Tagout (LOTO) permits with cited references.

4. **4. Plant SCADA & Architecture Inspector**:
   - Live telemetry feed for equipment tags (`P-201B`, `T-310A`, `V-104`, `F-501`).
   - Interactive Online/Offline toggle to simulate satellite link dropouts and reconnects.

---

## How to Run

### Run on Windows Desktop:
```bash
flutter run -d windows
```

### Run on Web (Chrome):
```bash
flutter run -d chrome
```

### Run on Android Tablet / Device:
```bash
flutter run -d <device_id>
```

### Run Automated Tests:
```bash
flutter test
```
