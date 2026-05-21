# server/api — Central server (v0.1)

`COMMUNICATION_PROTOCOL.md` 의 v0.1 초안을 구현한 최소 FastAPI 서버입니다.

- 저장소: **인메모리** (재시작 시 초기화)
- 인증: 디바이스별 `X-Device-Api-Key` 헤더
- 시계: ISO 8601 / UTC

> 이 단계의 목적은 엣지 클라이언트와 정적 대시보드가 동일한 규약으로 통신할 수
> 있는 더미 백엔드를 제공하는 것입니다. DB·영속화·실서비스용 보안은 다루지 않습니다.

---

## 실행

레포 루트에서:

```
pip install -r server/api/requirements.txt
uvicorn server.api.main:app --reload --port 9000
```

- API: `http://localhost:9000`
- OpenAPI 문서: `http://localhost:9000/docs`

## 시드 디바이스

서버 시작 시 다음 디바이스가 등록되어 있습니다 (`server/api/storage.py`):

| device_id | api_key | location |
| --- | --- | --- |
| `rpi-001` | `dev-key-rpi-001` | 정문 CCTV |

추가 디바이스는 `storage.py` 의 `_devices` 딕셔너리를 편집하거나
런타임에 `storage.register_device(...)` 를 호출해 등록합니다.

## 빠른 점검 (curl)

```
curl -X POST http://localhost:9000/api/devices/rpi-001/heartbeat \
  -H "X-Device-Api-Key: dev-key-rpi-001" \
  -H "Content-Type: application/json" \
  -d '{
    "timestamp": "2026-05-21T10:30:00Z",
    "status": "ok",
    "system": {"cpu_percent": 23.4, "mem_percent": 41.2, "temp_celsius": 52.1, "uptime_seconds": 86400},
    "camera": {"connected": true, "fps": 15.0},
    "inference": {"model_version": "yolov8n-smoke-v1", "avg_latency_ms": 87}
  }'

curl http://localhost:9000/api/devices
```

잘못된 키:
```
curl -X POST http://localhost:9000/api/devices/rpi-001/heartbeat \
  -H "X-Device-Api-Key: wrong" -H "Content-Type: application/json" -d '{}'
# -> 401 { "ok": false, "error": { "code": "invalid_api_key", ... } }
```

## 파일

| 파일 | 역할 |
| --- | --- |
| `main.py` | FastAPI 앱, 라우트, 에러 래퍼, CORS |
| `models.py` | 프로토콜 §4 의 Pydantic 모델 |
| `storage.py` | 인메모리 저장소 + 디바이스 레지스트리 |
| `auth.py` | `X-Device-Api-Key` 검증 |

## 현재 다루지 않는 것

- 영속화 (SQLite/Postgres)
- 디바이스 자동 등록(provisioning) 흐름
- WebSocket / MQTT
- 서버 → 엣지 명령 전송
- 압축 / 배치 업로드 최적화 / NTP
