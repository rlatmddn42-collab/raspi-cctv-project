# Communication Protocol

> 엣지 디바이스(라즈베리파이) ↔ 중앙 서버 간 통신 규약
> Status: **DRAFT** (v0.1)

본 문서는 라즈베리파이 엣지 디바이스와 중앙 서버 간의 데이터 교환 방식을 정의합니다.

---

## 1. 기본 결정 사항

### 1.1 통신 방식

- **HTTP REST API** (JSON 페이로드)
- 통신 방향: 기본적으로 **엣지 → 서버** (Push 모델)
- 서버 → 엣지 방향은 현재 단계에서 다루지 않음 (추후 명령 전송 필요 시 폴링 또는 별도 채널 도입)

### 1.2 선택 이유

- 추론은 엣지에서 끝나므로 서버로는 메타데이터(작은 JSON) 위주 전송 → REST가 충분
- 디버깅 용이 (curl, 브라우저로 즉시 테스트 가능)
- 구현 단순 (FastAPI/Flask 한 파일로 시작 가능)
- 라즈베리파이당 트래픽 빈도가 낮을 것으로 예상 (실시간 푸시 불필요)

### 1.3 인증

- 디바이스마다 고유 **API Key** 발급
- HTTP 헤더로 전달: `X-Device-Api-Key: <key>`
- 현재 단계는 단순 키 기반. 추후 JWT 또는 mTLS로 확장 가능

### 1.4 데이터 포맷

- 기본: `application/json` (UTF-8)
- 이미지 첨부 시: `multipart/form-data`
- 시간은 모두 **ISO 8601 / UTC** (예: `2026-05-21T10:30:00Z`)

---

## 2. 디바이스 식별

각 엣지 디바이스는 고유 `device_id` 를 가집니다.

| 필드 | 형식 | 예시 | 비고 |
| --- | --- | --- | --- |
| `device_id` | string (slug) | `rpi-001` | URL-safe, 영문/숫자/하이픈 |
| `api_key` | string | (서버 발급) | 헤더로 전달 |

---

## 3. 엔드포인트 목록

| Method | Path | 용도 |
| --- | --- | --- |
| POST | `/api/devices/{device_id}/heartbeat` | 디바이스 생존/상태 보고 |
| POST | `/api/devices/{device_id}/detections` | 추론 결과 전송 |
| POST | `/api/devices/{device_id}/events` | 임계치 초과 등 이벤트 |
| POST | `/api/devices/{device_id}/snapshots` | (선택) 이벤트 스냅샷 업로드 |
| GET  | `/api/devices` | 등록된 디바이스 목록 (대시보드용) |
| GET  | `/api/devices/{device_id}` | 단일 디바이스 상세 |
| GET  | `/api/devices/{device_id}/detections` | 추론 결과 조회 (대시보드용) |
| GET  | `/api/devices/{device_id}/events` | 이벤트 조회 |

---

## 4. 엔드포인트 상세

### 4.1 Heartbeat

엣지 디바이스의 상태를 주기적으로 보고합니다. (권장 주기: 30~60초)

**Request**

```
POST /api/devices/{device_id}/heartbeat
X-Device-Api-Key: <key>
Content-Type: application/json
```

```json
{
  "timestamp": "2026-05-21T10:30:00Z",
  "status": "ok",
  "system": {
    "cpu_percent": 23.4,
    "mem_percent": 41.2,
    "temp_celsius": 52.1,
    "uptime_seconds": 86400
  },
  "camera": {
    "connected": true,
    "fps": 15.0
  },
  "inference": {
    "model_version": "yolov8n-smoke-v1",
    "avg_latency_ms": 87
  }
}
```

**Response**

```json
{ "ok": true, "received_at": "2026-05-21T10:30:01Z" }
```

---

### 4.2 Detection

추론 결과를 보고합니다. 한 번에 1개 프레임 또는 묶음(batch) 전송 가능.

**Request**

```
POST /api/devices/{device_id}/detections
X-Device-Api-Key: <key>
Content-Type: application/json
```

```json
{
  "detections": [
    {
      "timestamp": "2026-05-21T10:30:00Z",
      "frame_id": "f_20260521_103000_001",
      "objects": [
        {
          "class": "smoke",
          "confidence": 0.87,
          "bbox": [120, 80, 340, 290]
        },
        {
          "class": "vehicle",
          "confidence": 0.92,
          "bbox": [50, 200, 220, 380]
        }
      ],
      "ocr": [
        {
          "text": "12가3456",
          "confidence": 0.95,
          "bbox": [60, 320, 200, 360]
        }
      ],
      "snapshot_ref": null
    }
  ]
}
```

**필드 설명**

| 필드 | 설명 |
| --- | --- |
| `bbox` | `[x1, y1, x2, y2]` (픽셀 좌표, 좌상단 원점) |
| `confidence` | 0.0 ~ 1.0 |
| `frame_id` | 엣지에서 발급하는 고유 ID |
| `snapshot_ref` | 별도 업로드한 스냅샷이 있다면 그 ID, 없으면 `null` |

**Response**

```json
{ "ok": true, "accepted": 1 }
```

---

### 4.3 Event

특정 조건(연기 감지, 차량 정체 등) 발생 시 즉시 보고.

```
POST /api/devices/{device_id}/events
```

```json
{
  "timestamp": "2026-05-21T10:30:00Z",
  "event_type": "smoke_detected",
  "severity": "warning",
  "message": "Smoke detected with confidence 0.87",
  "related_detection_id": "f_20260521_103000_001",
  "snapshot_ref": "snap_20260521_103000.jpg"
}
```

**severity 값**: `info` | `warning` | `critical`

---

### 4.4 Snapshot (선택)

이벤트와 연관된 이미지 업로드. 모든 프레임이 아닌 **이벤트 발생 시점만**.

```
POST /api/devices/{device_id}/snapshots
X-Device-Api-Key: <key>
Content-Type: multipart/form-data
```

Form fields:
- `file`: 이미지 파일 (jpg/png)
- `metadata`: JSON 문자열
  ```json
  {
    "timestamp": "2026-05-21T10:30:00Z",
    "frame_id": "f_20260521_103000_001"
  }
  ```

**Response**

```json
{
  "ok": true,
  "snapshot_id": "snap_20260521_103000",
  "url": "/api/snapshots/snap_20260521_103000.jpg"
}
```

---

### 4.5 조회 엔드포인트 (대시보드용)

**디바이스 목록**

```
GET /api/devices
```

```json
{
  "devices": [
    {
      "device_id": "rpi-001",
      "last_seen": "2026-05-21T10:30:00Z",
      "status": "ok",
      "location": "정문 CCTV"
    }
  ]
}
```

**추론 결과 조회**

```
GET /api/devices/{device_id}/detections?since=2026-05-21T00:00:00Z&limit=100
```

쿼리 파라미터:
- `since`: ISO 8601 시각 (이후 데이터만)
- `until`: ISO 8601 시각 (선택)
- `limit`: 기본 100, 최대 1000

---

## 5. 에러 응답 포맷

모든 에러는 일관된 형식으로 반환합니다.

```json
{
  "ok": false,
  "error": {
    "code": "invalid_api_key",
    "message": "API key is missing or invalid"
  }
}
```

**주요 에러 코드**

| HTTP | code | 의미 |
| --- | --- | --- |
| 400 | `bad_request` | 페이로드 형식 오류 |
| 401 | `invalid_api_key` | 인증 실패 |
| 404 | `device_not_found` | 등록되지 않은 device_id |
| 413 | `payload_too_large` | 업로드 크기 초과 |
| 429 | `rate_limited` | 너무 잦은 요청 |
| 500 | `server_error` | 서버 내부 오류 |

---

## 6. 향후 고려 사항 (현재 범위 외)

- 서버 → 엣지 명령 전송 (모델 업데이트, 설정 변경 등)
- WebSocket 또는 MQTT 도입 (실시간성 필요 시)
- 디바이스 자동 등록(provisioning) 흐름
- 압축 전송 (gzip)
- 배치 업로드 최적화
- 시계 동기화 (NTP 권장)

---

## 7. 변경 이력

| 버전 | 일자 | 변경 내용 |
| --- | --- | --- |
| 0.1 | 2026-05-21 | 초안 작성 |
