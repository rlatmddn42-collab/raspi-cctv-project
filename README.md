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

## 프로젝트 버전

> 아래 버전은 **프로젝트(체크포인트) 버전**입니다.
> 엣지↔서버 **통신 규약** 버전(`COMMUNICATION_PROTOCOL.md`)과는 별개이며,
> 통신 규약은 여전히 **v0.1 DRAFT** 입니다.

| 프로젝트 버전 | 내용 |
| --- | --- |
| **v0.1** | 기본 구조(엣지/서버 분리) + UI 역할 분리 + 두 정적 UI 프로토타입 + 통신 규약 v0.1 + **인메모리 더미 백엔드** |
| **v0.2** | **정적 대시보드 ↔ FastAPI 백엔드 라이브 연동.** 대시보드가 장치 목록·이벤트를 API 에서 직접 조회. 오염도·온습도 섹션은 화면에 유지되나 **미연동(미구현)** 으로 명시 표기. 저장소는 여전히 **인메모리(재시작 시 초기화)** |
| **v0.3** | **영속 저장소(SQLite) 도입.** 인메모리 dict 를 stdlib `sqlite3` 기반 저장소로 교체하여 **서버 재시작 후에도 데이터 유지.** API 응답 형태·통신 규약·엣지 에이전트는 변경 없음. DB 파일은 git 무시(`data/`). |

> v0.2/v0.3 는 대시보드 연동·영속화 마일스톤일 뿐이며, **오염도 점수 / 환경
> 온습도용 프로토콜 v0.2 가 구현되었다는 의미가 아닙니다.** 해당 데이터는 현재
> API/프로토콜에 정의되어 있지 않으며 향후 과제로 남아 있습니다. 통신 규약
> (`COMMUNICATION_PROTOCOL.md`)은 여전히 **v0.1 DRAFT** 입니다.

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
│  └─ api/                     # FastAPI 백엔드 (SQLite 영속 저장소, 더미 API) (v0.3)
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

## 백엔드 프로토타입 실행

`COMMUNICATION_PROTOCOL.md` v0.1 의 최소 구현입니다. **v0.3 부터 SQLite
영속 저장소**(stdlib `sqlite3`)를 사용하며, DB 가 비어 있을 때만 시드
디바이스 1대(`rpi-001`)를 등록합니다. DB 파일은 기본적으로 `data/cctv.db`
(git 무시)이며 `CCTV_DB_PATH` 환경변수로 변경할 수 있습니다. 자세한 설명은
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
- ~~백엔드 API 전체~~ → **최소 더미 백엔드만 구현** (v0.3, SQLite 영속 저장소)
- YOLO 학습/파인튜닝 파이프라인
- 실제 OCR 파이프라인
- 모델 다운로드/배포 엔드포인트
- 오염도 점수 / 환경 온습도 의 프로토콜 정의 (대시보드에서 "미연동" 표기)

> 정적 대시보드는 이제 실시간 CCTV 상태·이벤트를 백엔드 API 에서 직접
> 가져옵니다 (오염도·온습도는 프로토콜 미정의로 미연동). 자세한 내용은
> [docs/BACKEND_PROTOTYPE.md](docs/BACKEND_PROTOTYPE.md) §5.1 참고.

v0.1 은 **UI 역할 분리**, **두 UI 프로토타입**, **통신 규약 v0.1 더미 백엔드**
까지를 다뤘습니다. **v0.2** 는 여기에 **정적 대시보드 ↔ FastAPI 백엔드 라이브
연동**(장치 목록·이벤트 조회)을 더합니다. 통신 규약은 여전히 v0.1 DRAFT 이며,
오염도·환경 온습도는 미연동 상태로 남아 있습니다.
