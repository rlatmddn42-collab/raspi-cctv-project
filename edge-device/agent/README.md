# edge-device/agent — 엣지 송신 에이전트 (v0.1)

라즈베리파이(또는 개발용 Debian VM)에서 중앙 서버로 데이터를 송신하는 최소
클라이언트입니다. `COMMUNICATION_PROTOCOL.md` v0.1 에 맞춰 작성되었습니다.

> 이 단계에서는 실제 추론/OCR/카메라 연동은 포함하지 않습니다.
> 프로토콜이 실제로 동작하는지 점검하기 위한 송신 계층만 제공합니다.

---

## 구성

| 파일 | 역할 |
| --- | --- |
| `config.py` | 환경변수에서 서버 URL / 디바이스 ID / API 키 로드 |
| `client.py` | `EdgeClient` — 프로토콜 §4 의 각 엔드포인트 래핑 |
| `demo.py` | heartbeat / detections / event 1회씩 전송하는 스모크 테스트 |

## 환경 변수

| 이름 | 기본값 | 설명 |
| --- | --- | --- |
| `CCTV_SERVER_URL` | `http://localhost:9000` | 중앙 서버 베이스 URL |
| `CCTV_DEVICE_ID` | `rpi-001` | 본인 디바이스 식별자 |
| `CCTV_API_KEY` | `dev-key-rpi-001` | 서버에 등록된 API 키 |
| `CCTV_HEARTBEAT_SEC` | `30` | heartbeat 주기 (현재 미사용, 추후 데몬용) |

## 실행

```
pip install -r edge-device/agent/requirements.txt

# 서버가 떠 있는 상태에서 (server/api/README.md 참고)
python edge-device/agent/demo.py
```

> `edge-device/` 폴더명에 하이픈이 있어 표준 `python -m ...` 형태로는 임포트할
> 수 없습니다. `demo.py` 가 sys.path 를 직접 보정해 `agent` 패키지를 가져옵니다.

## 사용 예 (다른 모듈에서)

`edge-device/` 를 sys.path 에 올린 뒤 `agent` 를 패키지로 사용합니다.

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path("edge-device").resolve()))

from agent import client
from agent.config import load

c = client.EdgeClient(load())
c.heartbeat(
    system={"cpu_percent": 20.0, "mem_percent": 40.0, "temp_celsius": 50.0, "uptime_seconds": 100},
    camera={"connected": True, "fps": 15.0},
    inference={"model_version": "yolov8n-smoke-v1", "avg_latency_ms": 90},
)
```

## 에러 처리

서버가 §5 의 에러 응답을 반환하면 `client.ProtocolError` 가 발생합니다.
필드: `status` (HTTP), `code` (`invalid_api_key` 등), `message`.

## 현재 다루지 않는 것

- 실제 카메라/추론 파이프라인 연동
- heartbeat 백그라운드 데몬 (systemd 서비스 등)
- 재전송 / 오프라인 큐
- mTLS / 인증서 회전
