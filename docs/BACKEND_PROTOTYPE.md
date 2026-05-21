# Backend Prototype (v0.1)

> Status: **DRAFT prototype**
> 작성일: 2026-05-21
> 근거 문서: `COMMUNICATION_PROTOCOL.md` v0.1

본 문서는 라즈베리파이 엣지 디바이스와 중앙 서버 간 통신 규약(`COMMUNICATION_PROTOCOL.md`)
을 실제로 동작하는 최소 구현으로 옮긴 **백엔드 프로토타입**을 설명합니다.

이번 단계의 목적은 다음과 같습니다.

- 규약의 각 엔드포인트가 실제로 호출 가능한지 확인
- 정적 대시보드(`server/static_dashboard/`)가 장차 붙을 수 있는 동일 origin 의 더미 API 제공
- 엣지 측 송신 코드를 위한 참고 구현 제공

> 본 단계에서는 **AI 추론, OCR, 모델 학습/배포, 영속 저장소, 실서비스용 보안**
> 은 다루지 않습니다. README.md §"현재 단계에서 구현하지 않는 것" 항목을 그대로 유지합니다.

---

## 1. 구성 요소

| 위치 | 역할 |
| --- | --- |
| `server/api/` | FastAPI 기반 중앙 서버 (인메모리 저장소) |
| `edge-device/agent/` | 엣지 디바이스용 송신 클라이언트 (`requests`) |

### 1.1 서버 (`server/api/`)

| 파일 | 역할 |
| --- | --- |
| `main.py` | FastAPI 앱, 라우트, 에러 래퍼, CORS |
| `models.py` | 프로토콜 §4 의 Pydantic 모델 |
| `storage.py` | 인메모리 저장소 + 디바이스 레지스트리 |
| `auth.py` | `X-Device-Api-Key` 검증 |
| `requirements.txt` | 의존성 (fastapi, uvicorn, python-multipart) |
| `README.md` | 실행/점검 가이드 |

시드 디바이스 1대가 사전 등록되어 있습니다:

| device_id | api_key | location |
| --- | --- | --- |
| `rpi-001` | `dev-key-rpi-001` | 정문 CCTV |

### 1.2 엣지 송신 에이전트 (`edge-device/agent/`)

| 파일 | 역할 |
| --- | --- |
| `config.py` | 환경변수 기반 설정 (`CCTV_SERVER_URL` / `CCTV_DEVICE_ID` / `CCTV_API_KEY`) |
| `client.py` | `EdgeClient` — heartbeat / detections / event / snapshot 래퍼, `ProtocolError` 정의 |
| `demo.py` | 각 엔드포인트를 1회씩 호출하는 스모크 테스트 스크립트 |
| `requirements.txt` | 의존성 (requests) |
| `README.md` | 실행/사용 가이드 |

> `edge-device/` 디렉터리 이름에 하이픈이 있어 `python -m ...` 호출이 어렵습니다.
> `demo.py` 는 `sys.path` 를 보정하여 `agent` 를 패키지로 임포트합니다.

---

## 2. 프로토콜 매핑

`COMMUNICATION_PROTOCOL.md` §3 의 엔드포인트는 모두 구현되어 있습니다.

| Method | Path | 서버 핸들러 | 엣지 메서드 |
| --- | --- | --- | --- |
| POST | `/api/devices/{id}/heartbeat` | `main.post_heartbeat` | `EdgeClient.heartbeat()` |
| POST | `/api/devices/{id}/detections` | `main.post_detections` | `EdgeClient.detections()` |
| POST | `/api/devices/{id}/events` | `main.post_event` | `EdgeClient.event()` |
| POST | `/api/devices/{id}/snapshots` | `main.post_snapshot` | `EdgeClient.snapshot()` |
| GET  | `/api/devices` | `main.get_devices` | — |
| GET  | `/api/devices/{id}` | `main.get_device` | — |
| GET  | `/api/devices/{id}/detections` | `main.get_detections` | — |
| GET  | `/api/devices/{id}/events` | `main.get_events` | — |
| GET  | `/api/snapshots/{id}` | `main.get_snapshot` | — |

규약 §5 의 에러 응답 포맷은 전역 예외 핸들러에서 강제됩니다.

```json
{ "ok": false, "error": { "code": "invalid_api_key", "message": "..." } }
```

---

## 3. 실행 방법

레포 루트에서:

```
# 서버
pip install -r server/api/requirements.txt
uvicorn server.api.main:app --port 9000

# 엣지 (다른 터미널에서)
pip install -r edge-device/agent/requirements.txt
python edge-device/agent/demo.py
```

OpenAPI 문서: `http://localhost:9000/docs`

---

## 4. 로컬 스모크 테스트 결과 (2026-05-21)

Windows + Python 3.14 환경에서 다음 호출을 모두 검증했습니다.

| 점검 항목 | 기대 | 결과 |
| --- | --- | --- |
| `POST /heartbeat` (정상 키) | `200 {ok:true, received_at}` | ✅ |
| `POST /detections` (정상 키) | `200 {ok:true, accepted:1}` | ✅ |
| `POST /events` (정상 키) | `200 {ok:true}` | ✅ |
| `POST /snapshots` (PNG 멀티파트) | `200 {snapshot_id, url}` | ✅ |
| 잘못된 API 키 | `401 invalid_api_key` | ✅ |
| 미등록 device_id | `404 device_not_found` | ✅ |
| `GET /api/devices` | `last_seen` / `status` / `location` 반영 | ✅ (`정문 CCTV` 한글 라운드트립) |
| `GET .../detections` | `class` 필드 보존 + 한글 OCR 텍스트 | ✅ (`12가3456` 라운드트립) |
| `GET .../events` | `severity`, `related_detection_id` 보존 | ✅ |

### 4.1 발견 및 수정한 이슈

스모크 테스트 중 `server/api/main.py` 에서 **인증/검증 순서 문제** 가 드러났습니다.

- 증상: 잘못된 `X-Device-Api-Key` 또는 미등록 `device_id` 로 요청하면
  규약 §5 가 정의한 `401 invalid_api_key` / `404 device_not_found` 가 아닌
  `400 bad_request` ("Field required") 가 반환됨.
- 원인: 라우트가 `body: HeartbeatIn` 을 함수 인자로 직접 받았기 때문에
  Pydantic 의 바디 검증이 라우트 함수 내부의 `require_api_key()` 호출보다
  먼저 실행됨. 빈 바디로 테스트하면 바디 검증이 먼저 실패해 인증 에러가
  덮였음.
- 수정: `authed_device` 를 `Depends(...)` 로 분리하여 의존성 해석 단계에서
  먼저 실행되도록 함. 인증이 실패하면 바디 파싱 전에 즉시 `HTTPException`
  으로 단락(short-circuit) 됨.

수정 후 위 표의 모든 항목이 통과하는 것을 확인했습니다.

---

## 5. 현재 다루지 않는 것

- 영속 저장소 (재시작 시 데이터 초기화)
- 디바이스 자동 등록(provisioning) 흐름
- 압축 전송 / 배치 업로드 최적화 / NTP
- WebSocket / MQTT
- 서버 → 엣지 명령 전송
- 실 카메라/추론 파이프라인 연동
- heartbeat 백그라운드 데몬 (systemd 서비스)
- 재전송 / 오프라인 큐
- mTLS / 인증서 회전
- 정적 대시보드의 실제 API 연동 (현재까지는 하드코딩된 더미 데이터를 그대로 사용)

---

## 6. 다음 단계 후보

- `server/static_dashboard/script.js` 가 `/api/devices` 와
  `/api/devices/{id}/detections` 를 폴링하도록 전환.
- `edge-device/agent/` 에 heartbeat 데몬 추가 (systemd 또는 단순 루프).
- 인메모리 저장소를 SQLite 로 교체.
- API 키 발급/회전 절차 문서화.
