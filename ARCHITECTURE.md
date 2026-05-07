# Environment-Adaptive Pollution Monitoring System
## System Architecture Design — Raspberry Pi 4B Edge + Central Server

> Capstone project: reuse existing fixed-view CCTV infrastructure to detect persistent pollution (litter, cigarette butts, accumulated waste) and visually sensorize local micro-environment (temperature/humidity) via OCR.

---

## 1. Layered Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  L5  Extension Layer                                                │
│      Coral USB / Jetson / Fire&Smoke / Multi-CCTV Fusion            │
├─────────────────────────────────────────────────────────────────────┤
│  L4  User Monitoring Layer                                          │
│      Web Dashboard (GIS map, charts, events, snapshots, reports)    │
├─────────────────────────────────────────────────────────────────────┤
│  L3  Central Service Layer                                          │
│      REST/WebSocket API · DB · Training Server · Model Registry     │
├─────────────────────────────────────────────────────────────────────┤
│  L2  Edge AI Processing Layer  (Raspberry Pi 4B 4GB · 64-bit Lite)  │
│      RTSP Ingest · Inference · Background Model · OCR · Scoring     │
├─────────────────────────────────────────────────────────────────────┤
│  L1  Field Device Layer                                             │
│      Existing CCTV (RTSP) · Digital Thermo-Hygrometer (visual)      │
└─────────────────────────────────────────────────────────────────────┘
```

### Layer responsibilities

| Layer | Role | Where it runs |
|------|------|---------------|
| L1 Field Device | Provide raw video and a visual environmental readout in-frame | On-site hardware |
| L2 Edge AI | Real-time inference, environment-state learning, OCR, local scoring | Raspberry Pi 4B |
| L3 Central Service | Persistence, training, REST/WS API, alerting | Cloud / on-prem server |
| L4 User Monitoring | Operator-facing dashboard | Browser |
| L5 Extension | Optional accelerators and additional modalities | Plug-in modules |

---

## 2. Module Breakdown per Layer

### L1 — Field Device Layer
- **CCTV Stream Source** — fixed-view IP camera (RTSP `rtsp://user:pass@ip:554/...`)
- **Visual Sensor Tile** — small digital thermo-hygrometer placed inside the camera FOV at a fixed location

### L2 — Edge AI Processing Layer (Raspberry Pi 4B)
- `stream/rtsp_reader.py` — GStreamer/FFmpeg pull, frame queue, drop-on-overflow
- `stream/frame_sampler.py` — temporal subsampling (e.g., 1 fps for inference)
- `inference/detector.py` — ONNX Runtime / TFLite YOLO-nano detector
- `inference/preprocess.py` — resize, normalize, letterbox
- `env_state/background_model.py` — MOG2 / static reference learning of "normal" scene
- `env_state/persistence_tracker.py` — per-cell occupancy duration, accumulation map
- `ocr/roi_extractor.py` — fixed ROI crop for sensor tile
- `ocr/preprocessor.py` — grayscale → adaptive threshold → morphology
- `ocr/engine.py` — Tesseract / PaddleOCR-lite / 7-seg template matcher
- `ocr/validator.py` — regex + plausibility bounds + temporal smoothing
- `scoring/pollution_score.py` — weighted score from count, density, duration, env factors
- `events/event_builder.py` — construct event payloads with snapshot and metadata
- `comm/uploader.py` — HTTPS POST + retry/backoff queue (SQLite-backed)
- `comm/heartbeat.py` — periodic device health
- `service/main.py` — orchestrator, runs as systemd unit

### L3 — Central Service Layer
- `api/` — FastAPI REST + WebSocket
  - `cameras`, `events`, `snapshots`, `scores`, `ocr`, `health`
- `auth/` — JWT-based operator auth
- `db/` — PostgreSQL (TimescaleDB extension for time-series)
- `storage/` — object storage for snapshot images (S3-compatible / MinIO)
- `training/` — model fine-tuning pipeline (PyTorch)
- `model_registry/` — versioned `.onnx` / `.tflite` artifacts + manifest
- `notifier/` — threshold-based alert dispatch (email/webhook)

### L4 — User Monitoring Layer
- React (or Vue) SPA
- GIS map (Leaflet + OpenStreetMap or Naver/Kakao Map)
- Time-series charts (Recharts / Chart.js)
- Live event feed via WebSocket
- Snapshot viewer

### L5 — Extension Layer (out of MVP)
- Coral USB EdgeTPU adapter for `inference/detector.py`
- Jetson backend variant
- Fire/smoke detector module
- Additional OCR sensor types (gauges, analog dials)
- Multi-camera correlated scoring

---

## 3. End-to-End Data Flow

```
  ┌──────────────┐    RTSP     ┌─────────────────────────────────────┐
  │ Fixed CCTV   ├────────────▶│ Raspberry Pi 4B (Edge AI)           │
  └──────────────┘             │                                      │
                               │  rtsp_reader → frame_sampler         │
                               │       │                              │
                               │       ├──▶ detector ──▶ persistence  │
                               │       │                    │         │
                               │       └──▶ roi_extractor ──┼─▶ ocr   │
                               │                            ▼         │
                               │                   pollution_score    │
                               │                            │         │
                               │                   event_builder      │
                               │                            │ HTTPS   │
                               └────────────────────────────┼─────────┘
                                                            ▼
                          ┌──────────────────────────────────────────┐
                          │ Central Server (FastAPI + Postgres)      │
                          │  ingest → validate → store → notify      │
                          └──────────────────────────────────────────┘
                                                            │ REST/WS
                                                            ▼
                          ┌──────────────────────────────────────────┐
                          │ Operator Dashboard (browser)             │
                          └──────────────────────────────────────────┘
```

Frames stay on the Pi; only events, scores, OCR readings, and selective snapshots leave the device. This keeps bandwidth low and avoids streaming privacy-sensitive raw video.

---

## 4. MVP vs Future Extension

### MVP scope (must ship)
1. RTSP ingest from one fixed camera
2. YOLO-nano pollution detection (cigarette butt, litter, generic waste)
3. Background-state learning + persistence tracking
4. Fixed-ROI OCR for temperature/humidity
5. Pollution score computation
6. HTTPS event upload + offline queue
7. Central API + Postgres + minimal dashboard
8. systemd-managed edge service

### Future / out-of-MVP
- Coral USB EdgeTPU support
- Jetson port
- Fire / smoke / hazard detection
- Multi-camera fusion
- Additional OCR gauges (analog, multi-line)
- Mobile app
- Multi-tenant support

---

## 5. Recommended Technology Stack (Pi 4B 4GB · 64-bit Lite)

| Concern | Choice | Why |
|---|---|---|
| Edge OS | Raspberry Pi OS 64-bit Lite | Headless, low RAM footprint |
| Edge language | Python 3.11 | Ecosystem fit; C-bindings where needed |
| Video ingest | GStreamer (`rtspsrc`) via OpenCV | Hardware-accelerated decode on Pi 4B |
| Inference runtime | **ONNX Runtime** (CPU EP, XNNPACK) — TFLite as fallback | Best balance of speed/portability on ARM64 |
| Detection model | **YOLOv8n** INT8 (or YOLOv5n / NanoDet) | ~5–10 MB, runs on CPU |
| Background model | OpenCV MOG2 or rolling median reference | No extra deps |
| OCR | **Tesseract 5** with `digits` config; PaddleOCR-lite if accuracy needed | Tesseract is light; Paddle better for noisy displays |
| Local cache | SQLite (WAL mode) | Single-file durable queue |
| Service mgmt | systemd | Standard on Pi OS |
| Server API | **FastAPI** + Uvicorn | Async, typed, fast |
| DB | **PostgreSQL 16** + **TimescaleDB** | Time-series scoring data |
| Object store | MinIO / S3 | Snapshots |
| Cache/queue | Redis | WebSocket fan-out, rate limits |
| Frontend | React + Vite + Leaflet + Recharts | Lightweight, mature |
| Container | Docker + docker-compose (server only) | Pi runs native (Docker on Pi adds overhead) |

---

## 6. Lightweight Inference Approach

| Item | Recommendation |
|---|---|
| Model format | ONNX (primary), TFLite (fallback) |
| Runtime | ONNX Runtime 1.17+ with XNNPACK execution provider |
| Quantization | Static INT8 (post-training) using calibration set from the deployment site |
| Input resolution | **320×320** for general scenes; **416×416** when small objects (cigarette butts) dominate |
| Expected FPS (Pi 4B CPU) | 2–5 FPS at 320×320 INT8 (single thread tuned), 4–6 FPS multi-thread |
| Frame strategy | Sample 1 inference frame per second; persistence tracker accumulates over many frames |
| Optimization | (1) INT8 quantization · (2) input downscale · (3) NMS on CPU with low max-detections (≤50) · (4) skip-frame when CPU > 80% · (5) restrict detection to a configurable polygonal region of interest · (6) optional Coral USB offload via `pycoral` |

Small-object aid: SAHI tile inference is **opt-in** behind a config flag — only enable when the camera viewpoint cannot be brought closer and littering at distance is dominant. SAHI ~halves FPS, so it is not default.

---

## 7. OCR Pipeline for Fixed ROI

```
 frame ─▶ roi_crop(x,y,w,h)
           │
           ▼
       grayscale
           │
           ▼
   CLAHE contrast enhance
           │
           ▼
   adaptive threshold
           │
           ▼
   morphological open (1x1)  ← removes speckle
           │
           ▼
   resize 2× (bicubic)
           │
           ▼
   ocr_engine ──▶ raw string
           │
           ▼
   regex parser:  ^(-?\d{1,2}\.\d)C\s+(\d{1,3})%$
           │
           ▼
   plausibility filter:
       -20 ≤ T ≤ 50,  0 ≤ H ≤ 100
           │
           ▼
   temporal smoothing (median over last 5 readings)
           │
           ▼
   publish (T, H, confidence)
```

**Engine choice:**
- Default: **Tesseract** with `--psm 7 -c tessedit_char_whitelist=0123456789.%C ` for single-line digit-heavy reads (very low CPU).
- If the display is 7-segment LCD: a small **template-matching** module (one template per digit, cached) is faster and more accurate than a generic OCR.
- If LCD is glossy/back-lit and OCR fails: **PaddleOCR mobile** quantized model.

**Error correction:**
- Regex enforces format
- Out-of-range readings discarded (not smoothed)
- 5-tap median filter masks transient OCR flips (e.g., `8`↔`B`)
- If 3 consecutive failures → emit `ocr_health=degraded` event for the operator

---

## 8. Backend / Frontend / AI / Edge Task Separation

| Concern | Owner | Notes |
|---|---|---|
| Data labeling, dataset curation | AI team / server | Drives retraining quality |
| Model training, evaluation | AI team / training server | PyTorch → ONNX export |
| Model packaging, signing | AI team | Versioned manifest in registry |
| Model deployment to Pi | DevOps + Edge | Pull on heartbeat, atomic swap |
| Real-time inference | Edge | Pi 4B |
| Background-state learning | Edge | Per-camera, reset on installer command |
| Event/score upload | Edge → Backend | HTTPS + offline queue |
| Storage, time-series | Backend | Postgres+Timescale, MinIO for images |
| REST + WebSocket API | Backend | FastAPI |
| Auth, RBAC | Backend | JWT; operator vs admin |
| Dashboard UI | Frontend | React SPA |
| Map, charts | Frontend | Leaflet, Recharts |

---

## 9. Communication Design (Pi ↔ Server)

- **Transport:** HTTPS (TLS 1.3) — single outbound direction from Pi
- **Auth:** per-device API key + HMAC-signed payload; rotate via server on heartbeat
- **Endpoints (Pi → Server):**
  - `POST /api/v1/events` — pollution event (with optional snapshot multipart)
  - `POST /api/v1/scores` — periodic score (1/min)
  - `POST /api/v1/ocr` — env reading (1/min)
  - `POST /api/v1/heartbeat` — health, model version, FPS, CPU/RAM
- **Endpoints (Server → Pi pulled by Pi):**
  - `GET /api/v1/devices/{id}/config` — thresholds, ROI, schedule
  - `GET /api/v1/devices/{id}/model` — model manifest with checksum
- **Live channel (Server ↔ Dashboard):** WebSocket `/ws/live` for streaming events
- **Resilience:** outbound queue persisted in SQLite; exponential backoff; clock-skew-safe `event_uuid` for idempotency
- **Bandwidth budget:** ≤ 50 KB/min steady state without snapshots; snapshots throttled (max 1 per 5 min per camera unless severity high)

---

## 10. Database Schema (PostgreSQL + TimescaleDB)

```sql
-- Devices and cameras
CREATE TABLE devices (
  id            UUID PRIMARY KEY,
  name          TEXT NOT NULL,
  api_key_hash  TEXT NOT NULL,
  last_seen_at  TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE cameras (
  id            UUID PRIMARY KEY,
  device_id     UUID REFERENCES devices(id),
  name          TEXT NOT NULL,
  rtsp_url      TEXT,
  geo_lat       DOUBLE PRECISION,
  geo_lng       DOUBLE PRECISION,
  roi_polygon   JSONB,                 -- detection ROI
  ocr_roi       JSONB,                 -- {x,y,w,h}
  config        JSONB,                 -- thresholds, weights
  active_model  TEXT,
  created_at    TIMESTAMPTZ DEFAULT now()
);

-- Detections (raw, optional retention 7d)
CREATE TABLE detections (
  id            BIGSERIAL,
  camera_id     UUID,
  ts            TIMESTAMPTZ NOT NULL,
  class_label   TEXT,
  confidence    REAL,
  bbox          JSONB,
  PRIMARY KEY (ts, id)
);
SELECT create_hypertable('detections','ts');

-- Pollution score time-series
CREATE TABLE pollution_scores (
  camera_id     UUID,
  ts            TIMESTAMPTZ NOT NULL,
  score         REAL,
  count         INT,
  density       REAL,
  persistence   REAL,
  components    JSONB,                 -- breakdown
  PRIMARY KEY (camera_id, ts)
);
SELECT create_hypertable('pollution_scores','ts');

-- OCR readings
CREATE TABLE ocr_readings (
  camera_id     UUID,
  ts            TIMESTAMPTZ NOT NULL,
  temperature_c REAL,
  humidity_pct  REAL,
  ocr_conf      REAL,
  raw_text      TEXT,
  PRIMARY KEY (camera_id, ts)
);
SELECT create_hypertable('ocr_readings','ts');

-- Events (operator-facing)
CREATE TABLE events (
  id            UUID PRIMARY KEY,
  camera_id     UUID,
  ts            TIMESTAMPTZ NOT NULL,
  severity      TEXT,                  -- info | warn | critical
  type          TEXT,                  -- accumulation | new_object | ocr_fail | offline
  payload       JSONB,
  snapshot_url  TEXT,
  acked_by      UUID,
  acked_at      TIMESTAMPTZ
);

-- Snapshots metadata (binaries in object storage)
CREATE TABLE snapshots (
  id            UUID PRIMARY KEY,
  camera_id     UUID,
  ts            TIMESTAMPTZ NOT NULL,
  object_key    TEXT NOT NULL,
  width         INT, height INT,
  reason        TEXT
);

-- Model registry
CREATE TABLE models (
  version       TEXT PRIMARY KEY,
  format        TEXT,                  -- onnx | tflite
  sha256        TEXT,
  size_bytes    BIGINT,
  released_at   TIMESTAMPTZ
);
```

---

## 11. Deployment Flow

```
┌────────────┐  1. fine-tune    ┌────────────┐  2. export  ┌────────┐
│ Training   ├─────────────────▶│  PyTorch   ├────────────▶│ ONNX   │
│ Server     │                  │  weights   │             └───┬────┘
└────────────┘                                                  │ 3. quantize INT8
                                                                ▼
                                                          ┌──────────┐
                                                          │ Optimized│
                                                          │ ONNX/TFL │
                                                          └────┬─────┘
                                                               │ 4. publish to model registry (with sha256)
                                                               ▼
                                              ┌────────────────────────────┐
                                              │ Model Registry  (server)   │
                                              └─────────────┬──────────────┘
                                                            │ 5. heartbeat sees newer version
                                                            ▼
                                              ┌────────────────────────────┐
                                              │ Pi pulls + verifies sha256 │
                                              │ atomic swap symlink        │
                                              │ systemd reload service     │
                                              └────────────────────────────┘
```

systemd unit (sketch):

```ini
# /etc/systemd/system/pollutionedge.service
[Unit]
Description=Pollution Edge Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/opt/pollutionedge
ExecStart=/opt/pollutionedge/.venv/bin/python -m service.main
Restart=on-failure
RestartSec=5
LimitNOFILE=8192
Nice=5

[Install]
WantedBy=multi-user.target
```

---

## 12. Suggested Folder Structure

```
raspi-cctv-project/
├── ARCHITECTURE.md
├── README.md
├── ui-prototype/                  # static layout-only UI (Korean)
│   ├── index.html
│   ├── style.css
│   └── script.js
│
├── edge/                          # runs on Raspberry Pi 4B
│   ├── service/
│   │   └── main.py
│   ├── stream/
│   │   ├── rtsp_reader.py
│   │   └── frame_sampler.py
│   ├── inference/
│   │   ├── detector.py
│   │   └── preprocess.py
│   ├── env_state/
│   │   ├── background_model.py
│   │   └── persistence_tracker.py
│   ├── ocr/
│   │   ├── roi_extractor.py
│   │   ├── preprocessor.py
│   │   ├── engine.py
│   │   └── validator.py
│   ├── scoring/
│   │   └── pollution_score.py
│   ├── events/
│   │   └── event_builder.py
│   ├── comm/
│   │   ├── uploader.py
│   │   └── heartbeat.py
│   ├── config/
│   │   └── device.yaml
│   ├── models/                    # downloaded ONNX/TFLite (gitignored)
│   ├── deploy/
│   │   ├── pollutionedge.service
│   │   └── install.sh
│   └── pyproject.toml
│
├── server/                        # central service
│   ├── api/
│   │   ├── main.py
│   │   ├── routes/
│   │   │   ├── events.py
│   │   │   ├── scores.py
│   │   │   ├── ocr.py
│   │   │   ├── devices.py
│   │   │   └── ws.py
│   │   └── auth/
│   ├── db/
│   │   ├── models.py
│   │   └── migrations/
│   ├── storage/
│   ├── notifier/
│   ├── docker-compose.yml
│   └── pyproject.toml
│
├── training/                      # AI training pipeline
│   ├── datasets/                  # gitignored
│   ├── configs/
│   ├── train.py
│   ├── export_onnx.py
│   ├── quantize.py
│   └── eval.py
│
├── frontend/                      # operator dashboard (later)
│   └── (React app)
│
└── scripts/
    ├── deploy_to_pi.sh
    └── pull_model.sh
```

---

## 13. Risks and Limitations

| Risk | Impact | Mitigation |
|---|---|---|
| Pi 4B CPU saturation under multi-camera | Frame drops, latency | Single-camera per Pi at MVP; document as constraint; offer Coral USB upgrade path |
| Small-object detection (cigarette butts at distance) | Low recall | Higher input res (416), site-specific fine-tune, optional SAHI flag, recommend camera-position guideline |
| Lighting/weather variance | False positives, OCR drift | Per-time-of-day background model, day/night mode switch, periodic recalibration |
| OCR misreads (glare, condensation) | Bad env data | Regex + bounds + 5-tap median; emit degraded health when 3 fails in a row |
| Camera angle drift (wind, maintenance) | Background invalidated, ROI off | Reference-image SSIM check on heartbeat; auto-flag `view_changed` event; require operator re-baseline |
| Network outage | Lost events | SQLite-backed durable queue with idempotent `event_uuid` |
| Model regression after update | Worse detections in field | Shadow-mode A/B for 24h before promotion; rollback by symlink |
| Privacy concerns from raw video | Compliance risk | Never upload raw streams; only metadata + throttled snapshots; on-device blurring of human faces optional |
| Storage growth | Disk pressure | Timescale retention policy (raw detections 7d, scores 1y, snapshots 30d) |

---

## 14. Development Roadmap

| Phase | Duration | Goal | Exit criteria |
|---|---|---|---|
| **0. Prototype** | 2 wk | RTSP read + YOLOv8n inference + naive count on Pi | 2 FPS sustained, console output |
| **1. MVP — Edge** | 3 wk | Background model, persistence tracker, OCR pipeline, pollution score, SQLite queue | Score plotted locally; OCR within ±1°C / ±3% of reference |
| **2. MVP — Server + UI** | 3 wk | FastAPI ingest, Postgres, basic dashboard (the Korean prototype fleshed out) | End-to-end event from camera to dashboard |
| **3. Field Test** | 2 wk | Deploy to 1–2 real CCTV sites for 2 weeks | False-positive rate < 10%, uptime > 95% |
| **4. Optimization** | 2 wk | INT8 quantization, frame-skip tuning, OCR robustness, retention policies | 4+ FPS at 320, OCR fail rate < 2%/day |
| **5. Demo / Presentation** | 1 wk | Polish dashboard, prepare narrative, recorded demo | Live demo with seeded data + recorded edge feed |

---

## Appendix A — Pollution Score (reference formula)

```
score = w_c·norm(count)
      + w_d·norm(area_density)
      + w_p·norm(mean_persistence_minutes)
      + w_a·norm(accumulation_24h)
      + w_e·env_modifier(T, H)        # e.g., damp + warm → faster decay weight
```

All weights configurable per camera in `cameras.config`. Score is normalized to [0, 100] and bucketed: 0–20 양호 / 21–50 주의 / 51–80 경고 / 81–100 심각.
