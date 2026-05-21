# raspi-cctv-project

> Environment-Adaptive Pollution Monitoring and Visual Sensorization System
> Using Existing CCTV Infrastructure (Capstone)

기존 CCTV 인프라를 재활용하여 환경 적응형 오염 모니터링 및 시각 센서화를
수행하는 캡스톤 프로젝트입니다.

이 저장소는 **두 개의 분리된 측**을 함께 관리합니다.

- **엣지 디바이스 측 (라즈베리파이 4 Model B / 개발용 Debian VM)**
- **중앙 서버 측**

> Debian VM 은 라즈베리파이의 개발용 대체 환경입니다.
> 실제 배포 타겟은 라즈베리파이입니다.

---

## 폴더 구조

```
raspi-cctv-project/
├─ edge-device/
│  ├─ local_debug_ui/          # 라즈베리파이 로컬 디버그용 미니 UI
│  │  ├─ index.html
│  │  ├─ style.css
│  │  ├─ script.js
│  │  └─ README.md
│  └─ agent/                   # 엣지 송신 에이전트 (FastAPI 서버로 POST) (v0.1)
│     ├─ client.py
│     ├─ config.py
│     ├─ demo.py
│     ├─ requirements.txt
│     └─ README.md
│
├─ server/
│  ├─ static_dashboard/        # 중앙 서버 운영자용 메인 대시보드 (프로토타입)
│  │  ├─ index.html
│  │  ├─ style.css
│  │  ├─ script.js
│  │  └─ README.md
│  └─ api/                     # FastAPI 백엔드 (인메모리, 더미 API) (v0.1)
│     ├─ main.py
│     ├─ models.py
│     ├─ storage.py
│     ├─ auth.py
│     ├─ requirements.txt
│     └─ README.md
│
├─ docs/
│  ├─ UI_ROLE_SEPARATION.md    # 두 UI의 역할 분리 정의
│  └─ BACKEND_PROTOTYPE.md     # 백엔드 프로토타입 설명 + 프로토콜 매핑 (v0.1)
│
├─ COMMUNICATION_PROTOCOL.md   # 엣지↔서버 통신 규약 (v0.1 DRAFT)
├─ README.md
└─ .gitignore
```

---

## UI 역할 요약

| 구분 | 라즈베리파이 로컬 디버그 UI | 중앙 서버 대시보드 UI |
| --- | --- | --- |
| 위치 | `edge-device/local_debug_ui/` | `server/static_dashboard/` |
| 동작 환경 | 엣지 디바이스 (라즈베리파이/Debian VM) | 외부 중앙 서버 |
| 대상 사용자 | 설치자, 현장 디버거 | 운영자, 관리자 |
| 주요 용도 | 설치 직후 상태 점검, 디버깅 | 다수 디바이스 통합 모니터링 |
| 다루는 장치 수 | 1대 (자기 자신) | 다수 |
| 디자인 | 매우 가볍고 단순 | 일반적인 대시보드 형태 |

자세한 내용은 [docs/UI_ROLE_SEPARATION.md](docs/UI_ROLE_SEPARATION.md) 참고.

---

## 빠르게 열어 보기

두 UI 모두 정적 HTML/CSS/JS 입니다. 빌드 도구가 필요 없습니다.

### 라즈베리파이 로컬 디버그 UI
```
cd edge-device/local_debug_ui
python3 -m http.server 8080
# 브라우저에서 http://localhost:8080 접속
```

### 중앙 서버 대시보드 (프로토타입)
```
cd server/static_dashboard
python3 -m http.server 8000
# 브라우저에서 http://localhost:8000 접속
```

또는 각 폴더의 `index.html` 을 브라우저로 직접 열어도 됩니다.

---

## 백엔드 프로토타입 실행 (v0.1)

`COMMUNICATION_PROTOCOL.md` v0.1 의 최소 구현입니다. 인메모리 저장,
시드 디바이스 1대(`rpi-001`)만 제공합니다. 자세한 설명은
[docs/BACKEND_PROTOTYPE.md](docs/BACKEND_PROTOTYPE.md) 참고.

### 서버 (FastAPI, 포트 9000)
```
pip install -r server/api/requirements.txt
python -m uvicorn server.api.main:app --port 9000
# OpenAPI 문서: http://localhost:9000/docs
```

### 엣지 송신 데모 (다른 터미널에서)
```
pip install -r edge-device/agent/requirements.txt
python edge-device/agent/demo.py
```

heartbeat / detections / event 각 1회씩 전송되며, 서버는
`X-Device-Api-Key` 검증 후 §5 의 에러 응답 포맷으로 응답합니다.

---

## 현재 단계에서 구현하지 않는 것

- 전체 AI 추론 시스템
- ~~백엔드 API 전체~~ → **최소 더미 백엔드만 구현** (v0.1, 인메모리)
- YOLO 학습/파인튜닝 파이프라인
- 실제 OCR 파이프라인
- 모델 다운로드/배포 엔드포인트
- 정적 대시보드의 실제 API 연동 (현재까지는 하드코딩된 더미 데이터)

이번 단계는 **UI 역할 분리**, **두 UI 프로토타입**, 그리고
**프로토콜 v0.1 더미 백엔드** 까지를 다룹니다.
