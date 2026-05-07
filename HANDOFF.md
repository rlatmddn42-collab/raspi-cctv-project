# Handoff Document

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

Currently there is **one active workstream** with two UI sub-deliverables and
a documentation deliverable. Listed below as a single workstream because they
share scope and constraints.

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

Docs:
  - docs/UI_ROLE_SEPARATION.md  : edge vs. server responsibilities, rationale.
  - README.md                   : top-level overview and run instructions.
  - HANDOFF.md                  : full handoff (this is its summary block).

Out of scope right now (do NOT implement yet): full AI inference system,
backend API, YOLO training, real OCR, model distribution endpoint, maps,
multi-CCTV management on the edge UI.

Repo state at handoff: only commit is fc169ed "initial commit"; the new
layout above is uncommitted in the working tree. Old ui-prototype/,
ARCHITECTURE.md, and prompt.txt are deleted from the working tree but still
present in HEAD.

Immediate next step: commit the new layout, then validate both index.html
files render correctly. After that, begin replacing edge placeholders with
real device data feeds before touching the server backend.

Hard constraints: Korean UI text, no framework on the edge UI, edge UI must
not become a dashboard, do not start backend/AI/OCR work until the structural
phase is approved.
```
