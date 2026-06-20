# Handoff Document

> **⚠️ STALE (2026-05-07).** This snapshot predates the `test modul/` prototype
> pipeline (normal-background / persistent-change / candidate-dataset-builder)
> and covers only the earlier UI/structural work. For the current, authoritative
> project-progress summary, read the **root [`README.md`](README.md)** —
> specifically its "현재 프로젝트 상태" (Current Project Status) and "다음 작업"
> (Next Work) sections. This file has not been updated and is kept only for
> historical context.

> Generated 2026-05-07. Snapshot of the working tree at
> `C:\Users\A\Documents\raspi-cctv-project` so that another assistant,
> developer, or future session can continue without the prior conversation.

---

## 1. Overall Context

- The workspace currently contains **one project**:
  the capstone titled **"Environment-Adaptive Pollution Monitoring and Visual
  Sensorization System Using Existing CCTV Infrastructure"** (a.k.a.
  `raspi-cctv-project`).
- No other independent projects, codebases, or unrelated experiments are
  present in this directory at the time of writing. Everything observed below
  belongs to this one project.
- Work so far has been **structural and UI-prototype-only**:
  - Reorganizing folder layout to separate edge vs. server concerns.
  - Producing two static (HTML/CSS/JS) UI prototypes.
  - Writing role-separation documentation.
- No backend, no AI inference, no OCR, no model training has been
  implemented — by intent.
- The previous session was driven by `prompt.txt` (now deleted from disk).
  The current session will be driven by `prompt2.txt` (this handoff request).

### Workspace state notes
- `git status` shows the new layout (`edge-device/`, `server/`, `docs/`,
  `.gitignore`, the new `README.md`) as **untracked or modified, not committed**.
- The repository has **only one commit** so far: `fc169ed initial commit`.
- An old `ui-prototype/` folder and an `ARCHITECTURE.md` file existed in the
  initial commit but have been **deleted from the working tree**. They have
  not yet been removed from git history (still present in `HEAD`).
- `prompt.txt` is also deleted from the working tree; only `prompt2.txt`
  remains on disk.
- A `.claude/` directory is present and untracked (assistant tooling state,
  not project source).

---

## 2. Active Workstreams

Originally there was **one workstream** (UI role separation). As of
2026-05-21 a second workstream has been added: a backend prototype that
implements `COMMUNICATION_PROTOCOL.md` end-to-end. Both workstreams are
listed below.

### Workstream: UI role separation + dual UI prototypes

- **Purpose**
  Establish a clear runtime split between (a) the Raspberry Pi / Debian edge
  device's *local debug UI* and (b) the central server's *operator dashboard*,
  and provide minimal static prototypes of each.

- **Current status**
  Prototypes and docs are written and on disk. **Nothing is committed to git
  yet.** No backend wiring exists; both UIs run on placeholder data only.

- **Already decided**
  - Edge UI lives at `edge-device/local_debug_ui/`.
  - Server dashboard lives at `server/static_dashboard/`.
  - Both UIs are **plain HTML/CSS/JS only**, no framework, no build step.
  - All UI text is in **Korean**.
  - The Raspberry Pi side gets a deliberately minimal debug UI, **not** a full
    dashboard.
  - The operator-facing dashboard belongs only on the server.
  - Debian VM is treated as a development substitute for the Raspberry Pi 4
    Model B; both run the same edge code/UI.
  - Target edge inference rate: ~3–5 FPS (documented, not implemented).

- **Already done**
  - `edge-device/local_debug_ui/{index.html, style.css, script.js, README.md}`
    with sections: 장치 상태, 서버 연결 상태, CCTV 입력 상태, 현재 프레임
    미리보기, OCR 상태, OCR 좌표, 최근 온도/습도 값, 모델 상태, 모델 버전,
    추론 상태, 최근 오염도 점수, 최근 로그.
  - `server/static_dashboard/{index.html, style.css, script.js, README.md}`
    with sections: 실시간 CCTV 상태, 오염도 현황, 온습도 정보, 이벤트 기록,
    설정. Tables: CCTV 목록, 장치별 오염도 점수, 최근 이벤트, 온/습도.
  - `docs/UI_ROLE_SEPARATION.md` — defines edge vs. server roles and rationale.
  - Top-level `README.md` — quick overview and run instructions.
  - `.gitignore` — Python/Node/model/data/log/secrets.
  - Old `ui-prototype/`, old `ARCHITECTURE.md`, and `prompt.txt` removed from
    the working tree.

- **Unfinished**
  - **Git commit not yet made.** The new layout is uncommitted; the old layout
    is still in `HEAD`.
  - No backend integration in either UI.
  - No real OCR, no real inference, no training pipeline.
  - No model/ruleset distribution endpoint.
  - No tests, no CI.

- **Important constraints**
  - Korean-only UI text.
  - Lightweight / no framework on the edge UI specifically (must run on a
    small local display on a Pi 4).
  - Edge UI **must not** include map, multi-CCTV management, long-term stats,
    report generation, or full event management — those belong on the server.
  - Do **not** implement AI/OCR/training/backend yet (explicit user rule from
    `prompt.txt`).

- **Risks / uncertain points**
  - The new structure is uncommitted; an accidental clean/reset would lose it.
  - `prompt.txt` is no longer on disk, so the original spec is only preserved
    via this document and git history (it is *not* in the initial commit
    either — confirm before relying on it).
  - The two `python3 -m http.server` commands documented in the READMEs assume
    Python 3 is on PATH on both the Pi and the operator machine; not verified.
  - No layout testing on an actual small Pi display has happened.

- **Recommended next step**
  Stage and commit the new layout as a single coherent commit (e.g. "restructure
  project into edge-device/ and server/ with dual UI prototypes and role-
  separation docs"). Then validate both `index.html` files render in a browser.

---

### Workstream: Backend prototype (FastAPI server + edge sender)

Added 2026-05-21, driven by `prompt.txt` ("start writing the file according to
COMMUNICATION_PROTOCOL.md") and a follow-up smoke-test request.

- **Purpose**
  Provide a minimal but spec-conformant implementation of
  `COMMUNICATION_PROTOCOL.md` v0.1 so the static dashboard and a real edge
  client have a concrete target to talk to. **Not** a production backend.

- **Current status**
  Implementation is on disk, local smoke test passed end-to-end on
  Windows + Python 3.14. **Nothing committed to git yet.**

- **Already decided**
  - Server framework: **FastAPI** (the spec explicitly mentions FastAPI/Flask).
  - Storage: **in-memory only** for v0.1 (`server/api/storage.py`).
    Resets on restart. Seeded with one dev device (`rpi-001` /
    `dev-key-rpi-001` / `정문 CCTV`).
  - Edge client uses `requests` synchronously; a single `EdgeClient` class
    wraps heartbeat / detections / event / snapshot, and surfaces the
    §5 error envelope as `ProtocolError(status, code, message)`.
  - Auth via `X-Device-Api-Key` header, validated inside a FastAPI
    `Depends(authed_device)` so it runs **before** Pydantic body validation —
    see "Risks" below for the bug this fixed.
  - CORS opened for all origins so the static dashboard (`:8000`) can call
    the API (`:9000`) during dev.

- **Already done**
  - `server/api/{__init__.py, main.py, models.py, storage.py, auth.py,
    requirements.txt, README.md}`.
  - `edge-device/agent/{__init__.py, client.py, config.py, demo.py,
    requirements.txt, README.md}`.
  - `docs/BACKEND_PROTOTYPE.md` — full description of this workstream,
    protocol mapping, run instructions, and smoke-test result.
  - Local smoke test (2026-05-21): all four POST endpoints, all GET
    endpoints, bad-key (`401 invalid_api_key`), unknown-device
    (`404 device_not_found`), and a snapshot multipart upload round-trip
    pass. Korean strings (`정문 CCTV`, `12가3456`) round-trip intact.

- **Unfinished**
  - **Git commit not yet made** for any of the new files.
  - Static dashboard (`server/static_dashboard/script.js`) is **not yet
    wired** to the API — it still renders hardcoded arrays.
  - No persistence: every restart loses devices' last_seen, detections,
    events, snapshots.
  - No heartbeat daemon on the edge — `demo.py` only fires one message of
    each type per invocation.
  - No retry / offline queue on the edge client.
  - No tests (only the manual smoke script).

- **Important constraints (preserve)**
  - This is a **prototype**, not a production backend. Per the original
    `README.md` "현재 단계에서 구현하지 않는 것" section, no real AI/OCR/
    training/model-distribution work should happen here.
  - Server and edge code are independent halves of the same protocol; both
    must continue to refer to `COMMUNICATION_PROTOCOL.md` as the source of
    truth and update together if the spec changes.
  - Time fields are ISO 8601 UTC strings everywhere (no datetime objects on
    the wire).

- **Risks / uncertain points**
  - **Spec-conformance regression that was fixed and must not return:**
    initially `main.py` took the request body as a function parameter, which
    made Pydantic body validation fire before `require_api_key()`. Bad keys
    returned `400 bad_request` instead of `401 invalid_api_key`. Fix was to
    move auth into `Depends(authed_device)`. Any refactor of the route
    signatures must keep auth in a dependency that runs *before* body
    parsing.
  - In-memory storage means a server restart silently wipes state — easy
    to mistake for a bug while developing.
  - The seeded API key (`dev-key-rpi-001`) is a placeholder; do not deploy.
  - `edge-device/` folder name uses a hyphen, so `python -m
    edge_device.agent.demo` does NOT work; `demo.py` patches `sys.path`
    instead. Any future packaging effort needs to choose between renaming
    the folder, adding a proper `pyproject.toml`, or living with the
    `sys.path` hack.

- **Recommended next step**
  Either (a) wire `server/static_dashboard/script.js` to the live
  `GET /api/devices` and `GET .../detections` endpoints, or (b) commit the
  current prototype as a single coherent commit first, then proceed to (a).

---

## 3. Existing Files and Artifacts

Status legend: ✅ complete for current scope · 🟡 placeholder · ⚠ uncertain ·
🗑 removed from working tree.

### Project root
- `README.md` — overview, quick run instructions, link to role-separation doc. **✅**
- `.gitignore` — broad ignores for Python, Node, models, data, secrets. **✅**
- `prompt.txt` — original instruction file from the previous session. **🗑**
  (still in `HEAD`, but deleted in working tree)
- `prompt2.txt` — current instruction file driving this handoff document. **✅**
- `HANDOFF.md` — this document. **✅**
- `ARCHITECTURE.md` — old architecture doc from the initial commit. **🗑**
  (deleted in working tree, still in `HEAD`)

### `edge-device/local_debug_ui/`
- `index.html` — Korean debug UI with 12 sections of placeholder data. **✅ (placeholder data)**
- `style.css` — dark, compact, single-display-friendly stylesheet. **✅**
- `script.js` — populates DOM from a hardcoded `placeholder` object; appends
  two startup log lines. No network. **🟡 (placeholder)**
- `README.md` — Korean explanation of purpose, included/excluded items, run
  instructions. **✅**

### `server/static_dashboard/`
- `index.html` — Korean operator dashboard with 5 sections and several tables. **✅ (placeholder data)**
- `style.css` — light dashboard theme. **✅**
- `script.js` — renders four tables (CCTV, pollution, T/H, events) from
  hardcoded arrays. No network. **🟡 (placeholder)**
- `README.md` — Korean explanation of purpose and run instructions. **✅**

### `docs/`
- `UI_ROLE_SEPARATION.md` — Korean, defines edge vs. server responsibilities,
  comparison table, rationale, and what's intentionally out of scope. **✅**
- `BACKEND_PROTOTYPE.md` — Korean, describes the FastAPI server + edge
  sender prototype, protocol mapping table, run instructions, and the
  2026-05-21 smoke-test result. **✅** (added 2026-05-21)

### `server/api/` (added 2026-05-21)
- `main.py` — FastAPI app. Routes for heartbeat/detections/events/snapshots
  + GET endpoints for the dashboard. `authed_device` is a `Depends(...)`
  so auth runs **before** body validation (do not refactor that away —
  see §2 "Risks" for the bug it fixes). Global error handler enforces the
  §5 envelope. CORS open. **✅**
- `models.py` — Pydantic models for the §4 payloads. `DetectedObject.class_`
  is aliased to `class` because `class` is a Python keyword; `model_dump(
  by_alias=True)` is used when storing so the wire format is preserved. **✅**
- `storage.py` — in-memory dicts. Seeded with `rpi-001` / `dev-key-rpi-001`
  / `정문 CCTV`. **🟡 (resets on restart)**
- `auth.py` — checks device exists then compares the key. Raises
  `404 device_not_found` or `401 invalid_api_key`. **✅**
- `requirements.txt` — fastapi, uvicorn[standard], python-multipart. **✅**
- `README.md` — Korean run/curl guide. **✅**

### `edge-device/agent/` (added 2026-05-21)
- `client.py` — `EdgeClient` wrapping the four POST endpoints. Returns the
  parsed response dict, or raises `ProtocolError(status, code, message)`
  when the server returns the §5 error envelope. **✅**
- `config.py` — env-driven config (`CCTV_SERVER_URL`, `CCTV_DEVICE_ID`,
  `CCTV_API_KEY`, `CCTV_HEARTBEAT_SEC`). Defaults match the seeded server
  device. **✅**
- `demo.py` — fires one heartbeat + one detection + one event. Patches
  `sys.path` so the hyphenated `edge-device/` folder can still expose
  `agent` as an importable package. **✅**
- `requirements.txt` — requests. **✅**
- `README.md` — Korean run/usage guide. **✅**

### `ui-prototype/` (deleted)
- Old generic prototype that was the "Current Problem" identified by
  `prompt.txt`. **🗑** Replaced by the two folders above.

### `.claude/`
- Assistant tooling state. **⚠ not project source; do not commit blindly.**

### Memory store
- `C:\Users\A\.claude\projects\C--Users-A-Documents-raspi-cctv-project\memory\`
  is currently empty (no persistent memories saved). **⚠**

---

## 4. Decisions Already Made

### Confirmed (preserve)
- The project has **two separate UIs**, never merged:
  - Edge: `edge-device/local_debug_ui/`
  - Server: `server/static_dashboard/`
- Edge UI is **debug-only**, single device, lightweight, Korean.
- Server UI is the **main operator dashboard**, multi-device, Korean.
- Implementation stack for both prototypes: **plain HTML + CSS + JavaScript**,
  no framework, no bundler.
- Edge inference target: **~3–5 FPS on Raspberry Pi 4 Model B**.
- **Debian VM = development substitute** for the Pi; same edge code/UI.
- Out of scope for the current phase: full AI inference system, full backend
  API, YOLO training, real OCR, model/ruleset distribution endpoint.
- Korean is the UI language for both prototypes.

### Tentative / assumption-grade
- Section list of the edge debug UI matches `prompt.txt` exactly, but the
  exact placeholder values (e.g. 0.27 pollution score, 23.4 ℃, "v0.1.0-dev")
  are arbitrary illustrative defaults, not requirements.
- The same is true of the server dashboard's mock CCTV list, locations, and
  event log — illustrative only.
- Color scheme (dark for edge, light for server) was a stylistic choice not
  explicitly requested.
- `python3 -m http.server` is suggested as the dev launcher; not formally
  required.

### Style decisions
- Comments in code kept minimal.
- READMEs written in Korean, top-level `README.md` mixes Korean body with an
  English title line, matching the project name.
- Both UIs use a `*-table` / `cards` / `panel` class vocabulary; consistent
  but not extracted into a shared stylesheet.

---

## 5. Remaining TODOs

### Immediate next actions
1. **Commit** the new layout. Suggested message:
   `restructure: split into edge-device/ and server/ with dual UI prototypes`.
   Stage `edge-device/`, `server/`, `docs/`, `.gitignore`, modified `README.md`,
   and the deletions of `ui-prototype/`, `ARCHITECTURE.md`, `prompt.txt`.
   Decide separately whether to commit `prompt2.txt` and `HANDOFF.md`.
2. Decide whether `.claude/` should be added to `.gitignore` (recommended) or
   remain only locally.
3. Open both `index.html` files in a browser (or the dev `http.server`) and
   visually verify Korean rendering and layout.

### Medium-term tasks
- On the edge side: replace `script.js` placeholders with real data feeds:
  - `/dev/video0` capture status
  - CPU temp / uptime via `vcgencmd` or `psutil`
  - OCR ROI configuration loader
  - Latest inference result reader
  - Server connectivity ping
- On the server side: introduce a real backend (FastAPI or similar) and have
  `static_dashboard/script.js` pull from JSON endpoints instead of hardcoded
  arrays.
- Decide on a packaging path for the edge code (systemd service? Docker?).

### Later improvements
- YOLO training / fine-tuning pipeline on the server.
- Model export and distribution endpoint.
- OCR pipeline (Tesseract or a learned model) for the temp/humidity ROIs.
- Multi-device authentication between edge and server.
- Long-term storage and report generation on the server side.
- Map view, multi-CCTV management, statistics — **server side only**.

### Things to avoid for now (explicit)
- Do not add map, multi-CCTV management, stats, reports, or full event
  management to the **edge** UI.
- Do not start YOLO training, real OCR, or backend wiring until the structural
  and prototype phase is signed off.
- Do not introduce a frontend framework (React, Vue, etc.) into the edge UI
  unless the constraint is explicitly relaxed.
- Do not mix English UI strings into the prototypes.

---

## 6. Constraints and Preferences

### Technical
- Prototype UIs are static HTML/CSS/JS, no framework, no build step.
- No backend or network calls in the current prototypes.
- Repo is on Windows host (`win32`, PowerShell available); deployment targets
  are Linux (Debian VM and Raspberry Pi OS). Avoid Windows-only paths in code.

### Hardware / software assumptions
- Edge target: **Raspberry Pi 4 Model B**, USB CCTV input, small local display.
- Edge dev surrogate: **Debian VM**.
- Inference target rate: **~3–5 FPS** on the Pi (not yet implemented).
- Server: external machine, capacity for YOLO training/fine-tuning.

### UI / UX
- All UI text **Korean**.
- Edge UI must be readable on a small local display.
- Edge UI restricted to per-device debug info; not a dashboard.
- Server UI is the operator's main view; multi-device aggregation lives there.

### Language / writing style
- Prototype UIs and READMEs in Korean.
- Top-level docs (`README.md`, `UI_ROLE_SEPARATION.md`, `HANDOFF.md`) mix a
  Korean body with English headings/titles where natural.
- Code comments are sparse and only where the *why* is non-obvious.

### Performance
- Edge UI must stay lightweight; do not add heavy assets, large images, or
  animation that could compete with the inference workload.

### User preferences observed
- Wants the structural split between edge and server preserved at all costs.
- Prefers explicit, written role definitions (hence `UI_ROLE_SEPARATION.md`).
- Prefers placeholder-first prototypes before backend wiring.
- Drives sessions via `prompt*.txt` files in the repo root.

---

## 7. Open Questions

- Should the new layout be committed as **one** commit or split into
  per-folder commits? Not yet decided.
- Should the server dashboard eventually be served by the same backend that
  ingests inference results, or as a separately deployed static site? Not yet
  decided.
- What is the **actual hardware** for the central server (on-prem GPU box?
  cloud VM? lab workstation?). Currently unknown.
- Which OCR approach is intended (rule-based with Tesseract vs. a learned
  small model)? `prompt.txt` only said "OCR" generically.
- Authentication / device identity model between edge and server: **not
  specified**.
- Is `.claude/` expected to be in version control? Recommendation: ignore it,
  but confirm.
- Naming: device IDs in placeholder data are `raspi-edge-0N`. Confirm the real
  ID scheme before any code reads/writes them.
- Pollution score scale (`0.0`–`1.0` was used in placeholders) — what is the
  real scale and grading thresholds?

---

## 8. Continuation Summary

> Paste this block into a future AI session to bootstrap context.

```
Project: raspi-cctv-project (capstone) — "Environment-Adaptive Pollution
Monitoring and Visual Sensorization System Using Existing CCTV Infrastructure".

Hardware model: Raspberry Pi 4 Model B at the edge (USB CCTV in, ~3–5 FPS
local inference, OCR for temp/humidity ROIs, results sent to a central
server). A Debian VM is the dev substitute for the Pi. The central server
handles training, storage, and the operator dashboard.

Two separate UIs, never merged:
  - edge-device/local_debug_ui/   : Korean, lightweight, single-device debug
    only. Sections: 장치 상태, 서버 연결, CCTV 입력, 프레임 미리보기, OCR
    상태/좌표, 최근 온/습도, 모델 상태/버전, 추론 상태, 최근 오염도, 최근 로그.
  - server/static_dashboard/      : Korean, operator dashboard. Sections:
    실시간 CCTV 상태, 오염도 현황, 온습도 정보, 이벤트 기록, 설정.
Both are static HTML/CSS/JS with placeholder data; no framework, no backend.

Backend prototype (added 2026-05-21, also uncommitted):
  - server/api/                 : FastAPI server implementing
    COMMUNICATION_PROTOCOL.md v0.1. In-memory storage. Seeded device
    rpi-001 / dev-key-rpi-001 / "정문 CCTV". Auth via Depends(authed_device)
    that MUST run before body validation (do not collapse back into a route
    parameter — that re-introduces the 400-instead-of-401 bug that was
    fixed on 2026-05-21).
  - edge-device/agent/          : `requests`-based EdgeClient with
    heartbeat/detections/event/snapshot wrappers; ProtocolError surfaces
    the §5 error envelope. demo.py is a one-shot smoke test.
  Local smoke test on 2026-05-21 passed end-to-end (all POST/GET, bad-key
  → 401, unknown device → 404, snapshot multipart upload, Korean strings
  round-trip).

Docs:
  - docs/UI_ROLE_SEPARATION.md  : edge vs. server responsibilities, rationale.
  - docs/BACKEND_PROTOTYPE.md   : FastAPI server + edge sender prototype,
                                  protocol mapping, run steps, smoke result.
  - COMMUNICATION_PROTOCOL.md   : v0.1 DRAFT — source of truth for the wire
                                  format. Server and edge must update with it.
  - README.md                   : top-level overview and run instructions.
  - HANDOFF.md                  : full handoff (this is its summary block).

Out of scope right now (do NOT implement yet): full AI inference system,
YOLO training, real OCR, model distribution endpoint, maps, multi-CCTV
management on the edge UI. The backend prototype is explicitly a stub —
no persistence, no real auth, no production hardening.

Repo state at handoff: only commit is fc169ed "initial commit"; the new
layout above AND the backend prototype are uncommitted in the working tree.
Old ui-prototype/, ARCHITECTURE.md, and an earlier prompt.txt are deleted
from the working tree but still present in HEAD.

Immediate next step options:
  (a) commit the current working tree as one or two coherent commits
      (UI restructure + backend prototype), then
  (b) wire server/static_dashboard/script.js to GET /api/devices and
      GET /api/devices/{id}/detections instead of its hardcoded arrays.

Hard constraints: Korean UI text, no framework on the edge UI, edge UI must
not become a dashboard, do not start backend/AI/OCR work until the structural
phase is approved.
```
