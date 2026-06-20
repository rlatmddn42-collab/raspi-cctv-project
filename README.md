# raspi-cctv-project

> Environment-Adaptive Pollution Monitoring and Visual Sensorization System
> Using Existing CCTV Infrastructure (Capstone)

기존 CCTV 인프라를 재활용하여 환경 적응형 오염 모니터링 및 시각 센서화를
수행하는 캡스톤 프로젝트입니다.

이 저장소는 현재 **두 갈래의 작업**을 함께 담고 있습니다.

1. **엣지/서버/대시보드 시스템 측** (`edge-device/`, `server/`, `docs/`,
   `COMMUNICATION_PROTOCOL.md`) — 구조·UI·통신 규약·더미 백엔드 프로토타입.
2. **오프라인 영상 분석 프로토타입 파이프라인** (`test modul/`) — 고정형 CCTV
   영상에서 지속적 변화(잠재적 오염물)를 검출하고 사람이 검수할 수 있는 후보
   증거를 패키징하는 3개 모듈.

> 이 두 갈래는 아직 **서로 통합되어 있지 않습니다.** `test modul/` 의 프로토타입은
> 알고리즘 검증용 오프라인 파이프라인이며, 라즈베리파이 엣지 실시간 배포나
> 서버/대시보드와 아직 연결되지 않았습니다.

---

## ⚠️ 작업을 시작하기 전에 (필독)

**새 작업을 시작하기 전에 이 README 의 [현재 프로젝트 상태](#현재-프로젝트-상태)
와 [다음 작업](#다음-작업) 섹션을 먼저 읽으세요. 그리고 어떤 작업이 미완료라고
가정하기 전에 실제 저장소 상태(파일·출력·Git)를 직접 확인하세요.**

> 이 README 가 코드보다 더 신뢰할 수 있다는 뜻은 **아닙니다.** 문서와 실제
> 코드/파일이 충돌하면 **항상 실제 코드와 출력 파일이 기준**입니다. 이전 완료
> 보고서(completion report)만으로 상태를 판단하지 마세요.

작업 재개 시 권장 순서:

1. 이 루트 README 를 읽는다.
2. 변경하려는 모듈의 README 를 읽는다.
3. 실제 파일과 현재 Git 상태를 확인한다 (`git status`, 출력 폴더 내용).
4. 문서화된 [다음 작업](#다음-작업) 지점부터 이어서 진행한다.
5. 의미 있는 단계를 마치면 이 루트 README 의 상태·검증 내용을 갱신한다.

자세한 절차는 [개발 재개 절차](#개발-재개-절차)를 참고하세요.

---

## 프로젝트 개요

### 목표

고정 시점(fixed-view) CCTV 영상을 이용해 **장면에 지속적으로 남는 환경 변화**를
식별하는 것이 목표입니다. 대상 예시:

- 담배꽁초 (cigarette butts)
- 버려진 종이 (discarded paper)
- 컵 (cups)
- 기타 소형 쓰레기 (small litter)
- 더 넓은 범위의 오염 누적 (pollution accumulation)

> **모든 지속적 변화가 쓰레기라고 가정하지 않습니다.** 현재 프로토타입은 먼저
> "지속적인 시각적 변화"를 검출하고, 그 후보를 **사람 검수와 향후 모델 학습용**
> 으로 패키징할 뿐입니다. 자동 쓰레기 분류(AI classification)는 **존재하지
> 않습니다.**

### 더 큰 의도된 아키텍처 (장기 목표)

```
고정 CCTV / 녹화 영상
→ 엣지 측 전처리 및 추론
→ 서버 측 저장·학습·최적화·배포
→ 대시보드 및 오염 상태 리포팅
```

현재 `test modul/` 의 3개 모듈은 위 그림의 **알고리즘 검증 단계**에 해당하며,
최종 라즈베리파이 배포본이 아닙니다.

---

## 현재 3-모듈 프로토타입 파이프라인

`test modul/` (폴더명에 공백 포함, 철자 그대로 유지) 아래의 **독립 실행형
(standalone) 프로토타입 3개**가 순차적으로 연결됩니다.

```
녹화된 고정 시점 CCTV 영상
        ↓
[모듈 1] Normal Background Prototype  (normal-background-prototype/)
        ↓
reference_background.jpg
        ↓
[모듈 2] Persistent Change Prototype  (persistent-change-prototype/)
        ↓
persistent_change_events.json
        ↓
[모듈 3] Candidate Dataset Builder    (candidate-dataset-builder/)
        ↓
후보 폴더 + comparison panel + clip + review.html
```

| 모듈 | 폴더 | 역할 |
| --- | --- | --- |
| 1 | `test modul/normal-background-prototype/` | 정상 기준 배경 이미지 생성 |
| 2 | `test modul/persistent-change-prototype/` | 기준 배경과 비교하여 움직임·노이즈를 억제하며 지속적 정지 변화 검출 |
| 3 | `test modul/candidate-dataset-builder/` | 지속 변화 이벤트에서 검수용 증거 패키지 추출 |

---

## 모듈 1 — Normal Background Prototype

**폴더:** `test modul/normal-background-prototype/`
(메인 스크립트 `background_builder.py`)

### 목적
- 고정 시점 영상에서 대표적인 **정상 배경 이미지**를 만든다.
- 시간축 집계(**per-pixel temporal median**)를 사용해 일시적으로 지나가는
  사람·이동 물체를 약화시킨다. (소수 프레임에만 보이는 물체는 중앙값에서 밀려남)

### 입력 / 출력
- **입력:** 정상 상태의 고정 시점 CCTV 영상 1개 (`input/`)
- **출력:**
  - `output/reference_background.jpg` — 생성된 기준 배경
  - `output/reference_metadata.json` — 해상도·샘플링·프레임 수·메모리 추정·타임스탬프 등

### 실행 명령 (모듈 README 기준)
```bash
python3 background_builder.py --input input/normal_video.mp4 --output output --interval 2 --max-frames 300
```

### 주요 가정 / 한계
- **고정 카메라**, 동일한 장면·시점을 전제로 한다.
- 기준 영상은 정상 장면을 대표해야 한다.
- 조명·날씨·계절·카메라 위치가 크게 다르면 정확도가 떨어진다.
- 영상 내 **대부분의 시간 동안 같은 자리에 머문 물체**는 배경에 남을 수 있다.
- 카메라 흔들림 보정·주야 분류·다중 배경은 없음(설계상 제외).

### 상태
구현 완료 · 실행 성공 · 기준 배경 **육안 확인** 완료 · 모듈 2 의 입력으로 사용됨.

---

## 모듈 2 — Persistent Change Prototype

**폴더:** `test modul/persistent-change-prototype/`
(메인 스크립트 `persistent_change_detector.py`)

### 목적
고정된 정상 기준 배경과 테스트 영상을 비교하여, **작고 공간적으로 안정적이며
오래 지속되는 변화**를 후보로 만든다. 이때 움직이는 사람·차량·그림자, 일시적
움직임, 짧게 깜빡이는 픽셀 노이즈를 억제하고, 일시적 가림(occlusion) 동안에도
추적 후보를 유지한다.

> 이 모듈은 **"지속적인 시각적 변화"만 검출**합니다. 객체가 쓰레기인지 등의
> **의미(semantic) 분류는 하지 않습니다.** YOLO·OCR 없음.

### 주요 단계
1. 고정 기준 차분 마스크 (fixed-reference difference mask)
2. 프레임 간 움직임 마스크 (frame-to-frame motion mask)
3. 인접 움직임 조각의 병합·패딩 (한 사람의 머리/몸통/다리/그림자 조각을 하나로)
4. 동적 움직임 제외 (dynamic-motion exclusion)
5. 움직임 쿨다운 (motion cooldown)
6. **시간적 일관성 필터링 (temporal consistency filtering)**
7. 컨투어 및 면적 필터링
8. 공간 안정성 추적 (spatial-stability tracking)
9. 지속 시간 확정 (persistent-duration confirmation)
10. 가림 일시정지 및 복구 (occlusion pause & recovery)

### 4가지 필터의 구분 (중요)
| 필터 | 거르는 대상 |
| --- | --- |
| `--threshold` | 기준 배경 대비 **약한 픽셀 차이** |
| `--min-area` / `--max-area` | **물체 영역 크기** (너무 작거나 큰 것) |
| 시간적 일관성 필터 | **짧게 나타났다 사라지는** 노이즈 |
| `--persistence-seconds` | **장기간 정지** 확정 (오래 머물러야 지속 후보) |

> **`--min-area` 를 "주된 노이즈 필터"로 설명하면 안 됩니다.** 담배꽁초는 처리
> 해상도에서 몇 픽셀에 불과할 수 있어, 노이즈 제거는 `--min-area` 상향이 아니라
> **시간적 일관성 필터**가 담당합니다.

### 시간적 일관성 필터
- 정지 후보 마스크(움직임·쿨다운 제외 후)를 **최근 N 프레임 히스토리**에 저장.
- 픽셀별 등장 횟수가 `--temporal-min-hits` 이상일 때만 유지.
  `temporal_filtered = (sum(recent_masks) >= required_hits) AND 현재_정지_마스크`
- `--temporal-tolerance-kernel`(투표용에만 살짝 dilate)로 1–2px 흔들림 허용.
- **투표 전 마스크** = `stationary_candidate_mask.mp4`,
  **투표 후 마스크** = `temporal_filtered_mask.mp4` (컨투어 추출에 사용).
- global scene-change / broad-motion 으로 억제된 프레임은 히스토리에 추가하지
  않아, 한 프레임이 과거 증거를 지우지 못함.

### 움직임 가림(occlusion) 동작
- 움직임이 기존 추적 후보 위를 지나가도 **트랙을 삭제하지 않음.**
- 정지 누적 시간을 **일시정지(preserve)** — `stationary_duration` 을 초기화하지 않음.
- 트랙 ID 와 히스토리를 유지.
- 움직임이 사라지면 **이전 ID 를 재사용**하도록 복구 매칭 시도
  (`--occlusion-recovery-distance`).
- 비지속 후보와 지속 후보에 **서로 다른 유예 시간** 적용
  (`--motion-occlusion-grace-seconds` vs `--persistent-occlusion-grace-seconds`).

### 출력 파일
| 파일 | 의미 |
| --- | --- |
| `output/persistent_change_result.mp4` | 주석(annotated) 결과 영상 |
| `output/persistent_change_events.json` | 지속 후보 이벤트 + 설정 + 요약 카운트 |
| `output/change_mask.mp4` | 기준 차분 마스크 (`--save-mask-video`) |
| `output/motion_mask.mp4` | 현재 움직임 (흰색=움직임) (`--save-motion-mask-video`) |
| `output/stationary_candidate_mask.mp4` | **시간 투표 전** 정지 후보 마스크 (`--save-stationary-mask-video`) |
| `output/temporal_filtered_mask.mp4` | **시간 투표 후** 마스크, 컨투어 추출에 사용 (`--save-temporal-mask-video`) |

### 현재 실험적 튜닝 값 (E05_024)

> **현재 실험용 튜닝 값이며, 범용 프로덕션 기본값이 아닙니다.**
> 이 값들은 소스 코드의 argparse 기본값과 다릅니다. 코드 기본값은 변경하지
> 않았습니다(문서화 전용).

| 파라미터 | 값 | | 파라미터 | 값 |
| --- | --- | --- | --- | --- |
| `--processing-fps` | 3 | | `--motion-merge-distance` | 10 |
| `--width` | 960 | | `--motion-box-padding` | 2 |
| `--threshold` | 52 | | `--motion-cooldown-seconds` | 2 |
| `--min-area` | 3 | | `--global-motion-ratio` | 0.35 |
| `--max-area` | 5000 | | `--motion-occlusion-overlap-ratio` | 0.3 |
| `--persistence-seconds` | 15 | | `--motion-occlusion-grace-seconds` | 5 |
| `--motion-threshold` | 36 | | `--persistent-occlusion-grace-seconds` | 10 |
| `--motion-open-kernel` | 3 | | `--occlusion-recovery-distance` | 30 |
| `--motion-close-kernel` | 3 | | `--track-protection-padding` | 5 |
| `--motion-dilate-kernel` | 5 | | `--temporal-window-frames` | 9 |
| `--motion-dilate-iterations` | 1 | | `--temporal-min-hits` | 6 |
| `--motion-min-area` | 450 | | `--temporal-tolerance-kernel` | 3 |

> **참고(실제 파일과의 차이):** 저장소에 현재 포함된
> `persistent_change_events.json` 의 `configuration` 블록은 위 표와 거의
> 동일하나 `min_area` 가 **2** 로 기록되어 있습니다(위 표는 3). 재현 시에는
> 항상 events JSON 의 `configuration` 블록을 기준으로 확인하세요.

### E05_024 PowerShell 실행 명령
```powershell
cd "C:\Users\A\Documents\raspi-cctv-project\test modul\persistent-change-prototype"

python persistent_change_detector.py `
  --input "..\normal-background-prototype\input\E05_024.mp4" `
  --reference "..\normal-background-prototype\output\reference_background.jpg" `
  --output "output" `
  --processing-fps 3 --width 960 `
  --threshold 52 --min-area 3 --max-area 5000 --persistence-seconds 15 `
  --motion-threshold 36 --motion-open-kernel 3 --motion-close-kernel 3 `
  --motion-dilate-kernel 5 --motion-dilate-iterations 1 --motion-min-area 450 `
  --motion-merge-distance 10 --motion-box-padding 2 --motion-cooldown-seconds 2 `
  --global-motion-ratio 0.35 `
  --motion-occlusion-overlap-ratio 0.3 --motion-occlusion-grace-seconds 5 `
  --persistent-occlusion-grace-seconds 10 --occlusion-recovery-distance 30 `
  --track-protection-padding 5 `
  --temporal-window-frames 9 --temporal-min-hits 6 --temporal-tolerance-kernel 3 `
  --save-mask-video --save-motion-mask-video `
  --save-stationary-mask-video --save-temporal-mask-video `
  --show-motion-regions
```

### 검증 근거 (확인된 사실만)
- 문법(`py_compile`)·`--help` 검증 완료.
- **합성(synthetic) 시간 노이즈 테스트**: 작은 정지 물체는 유지하고 짧게
  깜빡이는 노이즈는 제거됨을 확인 (마스크 픽셀 약 93.5% 감소).
- **움직임 조각 억제**: 군중 클립에서 사람 조각 후보가 크게 감소함을 마스크로 확인.
- **가림 생존**: 합성 테스트에서 사람이 작은 정지 물체 위를 지나가는 동안에도
  **동일 트랙 ID 가 유지**되고 정지 시간이 보존·재개됨을 주석 영상으로 확인.
- 실제 CCTV 클립이 처리됨.
- **실제 담배꽁초 검출 성능은 아직 검증되지 않음** (다양한 실제 영상에서의
  의미적 정확도 미검증).

> 정리: 이 검출기는 **지속적 시각 변화**를 찾습니다. 쓰레기 클래스(semantic)를
> 분류하지 않습니다.

---

## 모듈 3 — Candidate Dataset Builder

**폴더:** `test modul/candidate-dataset-builder/`
(메인 스크립트 `candidate_dataset_builder.py`)

### 목적
`persistent_change_events.json` 을 소비하여, 선택된 각 후보마다 **시각 증거를
추출**하고 사람이 라벨링할 수 있게 한다. 향후 데이터셋 익스포터/모델 학습
파이프라인용 재료를 준비한다.

> **업데이트(schema 2.0):** 사람 검수 파일에 더해, 후보별 **깨끗한 모델 입력**
> (`model_input/`: `reference/current/difference/mask` + `paired_*` + 컨텍스트
> 스케일, 텍스트·박스 없음)과 **학습 매니페스트**(`training_manifest.json/csv`,
> `usable_for_training` 포함)를 내보낸다. **구조적 의미(semantic) 라벨**과
> **샘플 품질(sample_quality) 라벨**을 분리하고, 신뢰도·메모, 카메라/소스
> 그룹 메타데이터(데이터 누수 방지용 `group_key`), 선택적 배경 네거티브 생성,
> 레거시 라벨 마이그레이션을 지원한다. **분류기를 학습하지 않으며, 교차 카메라
> 일반화를 입증하지 않는다.** 학습 이미지로 `comparison_panel.jpg` 를 쓰면 안
> 되고, `model_input/` 만 사용해야 한다.

### 필수 입력
- 원본 소스 영상 (`--video`)
- `persistent_change_events.json` (`--events`)
- `reference_background.jpg` (`--reference`)

### 좌표 스케일링
- 지속 변화 이벤트는 **처리 해상도(예: 960×540)** 좌표일 수 있다.
- 원본 영상은 **1920×1080** 일 수 있다.
- 이벤트 bbox 는 잘라내기 전에 **소스 영상 좌표로 스케일**된다
  (`source_x = event_x × source_w / event_w`).
- 기준 이미지는 비교 출력용으로만 리사이즈되며 **원본 파일을 덮어쓰지 않는다.**

### 후보별 출력 (각 `candidates/candidate_XXXX/`)
- `reference_context.jpg`, `before_context.jpg`, `first_seen_context.jpg`,
  `persistent_context.jpg`, `last_seen_context.jpg` — 동일 context 사각형
- `persistent_crop.jpg` — 원본 해상도 크롭
- `persistent_crop_nearest.png` — **nearest 확대** (실제 소스 픽셀 확인용)
- `persistent_crop_smooth.png` — **smooth(Lanczos) 확대** (보기용, 보간 시각화)
- `difference_context.jpg` — (지속 프레임 − 기준) 차분 시각화
- `comparison_panel.jpg` — 3×2 라벨 패널
- `candidate_clip.mp4` — 지속 시점 주변 짧은 클립
- `metadata.json`

> **확대 이미지는 소스에 없는 디테일을 만들어내지 않습니다.** nearest 는 실제
> 픽셀 확인용, smooth 는 보간 시각화일 뿐입니다.

### 전역 출력 (`output/`)
- `manifest.json`
- `manifest.csv` — **UTF-8 with BOM** (한글 Windows Excel 호환)
- `extraction_summary.json`
- `review.html`
- `candidates/` (후보 폴더들)

### 정적 검수 워크플로
1. `review.html` 을 브라우저로 **직접** 연다 (웹서버·인터넷 불필요).
2. 각 후보를 확인한다.
3. 라벨 중 하나를 지정한다
   (`litter`, `cigarette_butt`, `other_litter`, `not_litter`, `uncertain`, `unreviewed`).
4. 메모(notes)를 추가한다.
5. **Download review results** 로 `review_results.json` 을 내려받는다.
6. `--review-results` + `--update-labels-only` 로 다시 불러온다.
7. 이미지/클립을 재추출하지 않고 metadata·manifest 만 갱신한다.

> 정적 HTML 은 로컬 JSON 을 자동 저장할 수 없습니다. 이 페이지는 라벨을
> **자동 저장하지 않으며**, 반드시 Download 버튼을 사용해야 합니다.

이 모듈은: 쓰레기 자동 분류 안 함 · YOLO 학습 안 함 · 검출기 이벤트 변경 안 함 ·
**오직 사람 검수용 증거 패키징만** 수행.

### 검증 사실
- **단위 테스트 22개 통과** (`python -m unittest discover -s tests`).
- 실제 event JSON 구조를 직접 점검함.
- 16개 이벤트 발견 → **16개 후보 추출 → 0개 스킵** (보고된 실행 기준).
- 좌표 정렬(작은/큰/가림 후보 패널)을 육안 확인함.

> **현재 데이터 정합성(실측):** 저장소의 `persistent_change_events.json` 과
> `candidate-dataset-builder/output/` 은 **둘 다 E05_024** 기준으로 일치합니다
> (events 의 `source_video_path` = E05_024, 후보 metadata 의 `source_video`
> = E05_024, 16개 후보). 즉 현재 출력은 E05_024 의 검출 결과를 패키징한 것입니다.
> (이전 일부 완료 보고서에는 E05_003 으로 기록되어 있으나, 실제 파일 기준으로는
> E05_024 입니다 — 아래 [데이터 일관성](#검증된-테스트-영상과-데이터-일관성) 참고.)

### PowerShell 실행 명령
추출:
```powershell
cd "C:\Users\A\Documents\raspi-cctv-project\test modul\candidate-dataset-builder"

python candidate_dataset_builder.py `
  --video "..\normal-background-prototype\input\E05_024.mp4" `
  --events "..\persistent-change-prototype\output\persistent_change_events.json" `
  --reference "..\normal-background-prototype\output\reference_background.jpg" `
  --output "output" `
  --context-padding 80 --minimum-context-size 160 `
  --crop-padding 12 --crop-upscale 12 `
  --before-seconds 2 --clip-before-seconds 3 --clip-after-seconds 5 `
  --verbose
```
검수 결과 반영:
```powershell
python candidate_dataset_builder.py `
  --events "..\persistent-change-prototype\output\persistent_change_events.json" `
  --output "output" `
  --review-results "output\review_results.json" `
  --update-labels-only
```

---

## 현재 프로젝트 상태

> 완료를 과장하지 마세요. 아래는 **2026-06-20 기준 실측 상태**입니다.

| 항목 | 상태 |
| --- | --- |
| 정상 기준 배경 생성 (모듈 1) | **Completed prototype** |
| 지속 시각 변화 검출 (모듈 2) | **Completed prototype** |
| 움직임 영역 억제 | **Completed prototype, tested on real footage** |
| 시간적 깜빡임 노이즈 필터링 | **Completed prototype, synthetic & real-video tests performed** |
| 움직임 가림 후보 생존 | **Completed prototype, synthetic ID-continuity validation performed** |
| 후보 증거 추출 (모듈 3) | **Completed prototype** |
| 모델 입력 export (clean reference/current/difference/mask, paired) | **Completed prototype** |
| 구조적 semantic 라벨 + sample_quality 라벨 + training manifest | **Completed prototype** |
| 카메라/소스 그룹 메타데이터 (데이터 누수 방지용) | **Completed prototype** |
| 정적 사람 검수 페이지 (review.html, schema 2.0) | **Completed prototype** |
| 실제 담배꽁초 검출 품질 | **Not yet sufficiently validated** |
| 사람이 라벨링한 데이터셋 | **Not yet built** |
| YOLO 포맷 데이터셋 export | **Not implemented** |
| YOLO 학습 | **Not implemented** |
| 서버 측 자동 학습/배포 통합 | **Not integrated with these prototypes** |
| 라즈베리파이 실시간 배포 | **Not integrated** |
| 대시보드 오염 점수 통합 | **Not integrated with the new prototype pipeline** |
| 엣지/서버/대시보드 시스템 (별도 갈래) | v0.3 프로토타입 (아래 [기존 시스템](#기존-시스템-엣지서버대시보드--통신-규약) 참고) |

---

## 검증된 테스트 영상과 데이터 일관성

**`persistent_change_events.json` 은 그것을 생성한 정확한 영상·처리 해상도·기준
배경·파라미터에 묶여 있습니다.** 따라서:

- 한 영상(E05_003)의 events 를 다른 영상(E05_024)에 좌표·타임스탬프가 호환되는
  것처럼 사용하면 **안 됩니다.**
- 영상마다 지속 변화 검출기를 **개별 실행**하세요.
- 영상별 출력을 별도 디렉터리에 저장하세요.
- candidate-dataset-builder 에는 **서로 짝이 맞는** 영상·events JSON·기준 배경을
  넘기세요.

> **현재 실측:** 지금 저장소의 events JSON 과 후보 빌더 출력은 **모두 E05_024**
> 로 일치합니다. (E05_003 과 E05_024 는 호환되지 않으며, 서로 섞어 쓰면 안 됩니다.)

### 권장(향후) 출력 레이아웃 — *아직 미적용, 권장 컨벤션*
```
persistent-change-prototype/output/E05_003/
persistent-change-prototype/output/E05_024/

candidate-dataset-builder/output/E05_003/
candidate-dataset-builder/output/E05_024/
```
> 기존 파일을 자동으로 재배치하지는 않습니다. 위는 향후 권장 규칙입니다.

---

## 알려진 한계

### 구현상의 한계 (설계/동작)
- **고정 카메라**를 전제로 함. 다른 시점·크게 다른 조건에서 만든 기준 배경은
  거짓 변화를 만들 수 있음.
- **의미(semantic) 분류 없음** — 쓰레기/그림자/얼룩을 구분하지 않음.
- 확대 이미지는 소스에 없는 정보를 만들지 않음 (smooth 는 보간일 뿐).
- 이벤트에 프레임별 bbox 히스토리가 없어, 후보 클립은 **고정 bbox** 를 그릴 수 있음.
- 매우 느리거나 **멈춘 사람**은 프레임 차분 기반 움직임 검출을 벗어날 수 있음.
- 공격적인 움직임 마스크가 근처 실제 쓰레기를 일시적으로 가릴 수 있음.
- 가림 복구가 근처의 **다른 물체**를 옛 트랙에 잘못 연결할 수 있음.

### 미검증 성능 (별도로 구분)
- 실제 작은 담배꽁초는 처리 해상도에서 **몇 픽셀**에 불과할 수 있음.
- **지속적·구조적 노이즈**(예: 항상 렌더되는 타임스탬프)는 시간 투표를 통과할 수 있음.
- 현재 튜닝은 **장면 특화(scene-specific)** 이며 범용 기본값이 아님.
- **E05_024 담배꽁초 성능은 아직 명시적 육안 검증이 필요함.**
- 엣지/서버/대시보드와의 전체 통합은 아직 완료되지 않음.

---

## 다음 작업

> 즉시 다음 단계는 단순히 "YOLO 학습"이 아닙니다.

1. 여러 **짝이 맞는** 영상에 대해 지속 변화 검출기를 **개별 출력 폴더**로 실행.
2. 각 영상에 대해 후보 증거를 생성.
3. `review.html` 에서 후보를 검수.
4. 일관되게 라벨링: `cigarette_butt`, `other_litter`, `not_litter`, `uncertain`.
5. `review_results.json` 를 `--review-results` 로 반영.
6. 검출기 품질 측정:
   - 실제 쓰레기 후보 수
   - 유형별 오탐(false positive)
   - 놓친(보이는데 미검출) 담배꽁초
   - 거리·물체 픽셀 크기의 영향
7. 충분한 라벨 예시를 수집.
8. **데이터셋 익스포터 / 어노테이션 준비 모듈**을 만든다.
9. 몇 픽셀짜리 물체에 YOLO 가 적합한지 판단한다.
10. 그 다음에야 학습·배포 파이프라인을 만든다.

> 검출기 bbox 가 부정확하면, 후보 분류만으로는 정확한 YOLO bbox 라벨을 만들 수
> 없습니다. 따라서 다음 모듈은 다음을 지원해야 할 수 있습니다:
> 수동 bbox 보정 · 이미지 단위 분류 라벨 · 네거티브 예시 export ·
> train/validation 분할 · **소스 영상 단위 중복/누수 방지**.

> 정확한 다음 모듈은 **사람 검수 결과를 확인한 뒤** 결정하세요.

---

## 개발 재개 절차

향후 개발자/AI 에이전트는 다음을 따르세요:

1. 이 루트 README 를 읽는다.
2. [현재 프로젝트 상태](#현재-프로젝트-상태) 표를 확인한다.
3. 변경할 모듈의 README 를 읽는다.
4. 실제 소스 파일과 CLI `--help` 를 확인한다.
5. `git status` 와 최근 커밋을 확인한다.
6. **어떤 영상이 어떤 events JSON 을 생성했는지** 확인한다.
7. 다른 영상의 출력을 확인 없이 덮어쓰지 않는다.
8. 요청된 변경만 수행한다.
9. 적절한 경우 문법 검증·테스트·실제 샘플 실행을 수행한다.
10. 다음을 갱신한다: 모듈 README · 루트 [현재 프로젝트 상태] · 검증 근거 ·
    알려진 한계 · 다음 작업.
11. **라벨링된 실제 영상 근거 없이 의미적 쓰레기 검출 성공을 주장하지 않는다.**

> 완료 보고서(completion report)만으로는 충분하지 않습니다. **실제 파일과
> 출력을 직접 확인**해야 합니다.

---

## 저장소 구조

```
raspi-cctv-project/
├─ test modul/                       # 오프라인 영상 분석 프로토타입 (엣지/서버 미통합)
│  ├─ normal-background-prototype/   # [모듈 1] 정상 배경 생성
│  ├─ persistent-change-prototype/   # [모듈 2] 지속 변화 검출
│  └─ candidate-dataset-builder/     # [모듈 3] 후보 증거 추출 + review.html
│
├─ edge-device/                      # 엣지(라즈베리파이/Debian VM) 측
│  ├─ local_debug_ui/                # 라즈베리파이 로컬 디버그용 미니 UI
│  └─ agent/                         # 엣지 송신 에이전트 (FastAPI 서버로 POST) (v0.1)
│
├─ server/                          # 중앙 서버 측
│  ├─ static_dashboard/              # 운영자용 메인 대시보드 (프로토타입)
│  └─ api/                           # FastAPI 백엔드 (SQLite 영속 저장소, 더미 API) (v0.3)
│
├─ docs/
│  ├─ UI_ROLE_SEPARATION.md          # 두 UI의 역할 분리 정의
│  └─ BACKEND_PROTOTYPE.md           # 백엔드 프로토타입 설명 + 프로토콜 매핑 (v0.1)
│
├─ COMMUNICATION_PROTOCOL.md         # 엣지↔서버 통신 규약 (v0.1 DRAFT)
├─ HANDOFF.md                        # 과거 핸드오프 스냅샷 (2026-05-07, UI/구조 한정 — 구버전)
├─ README.md                         # (이 문서) 프로젝트 진행 상태 권위 문서
└─ .gitignore
```

> `test modul/` 의 3개 폴더는 **오프라인 검증 모듈**이며, 아직 엣지/서버 실행에
> 통합되지 않았습니다. `edge-device/`·`server/`·`docs/` 는 별도 갈래(시스템
> 프로토타입)입니다.

---

## 기존 시스템 (엣지/서버/대시보드 + 통신 규약)

> 이 절은 `test modul/` 프로토타입과 **분리된** 시스템 측 작업입니다. 아래 내용은
> 기존 문서에서 유지된 것으로, 프로토타입 파이프라인과 아직 연결되지 않았습니다.

### 프로젝트 버전

> 아래 버전은 **프로젝트(체크포인트) 버전**입니다. 엣지↔서버 **통신 규약**
> 버전(`COMMUNICATION_PROTOCOL.md`)과는 별개이며, 통신 규약은 여전히
> **v0.1 DRAFT** 입니다.

| 프로젝트 버전 | 내용 |
| --- | --- |
| **v0.1** | 기본 구조(엣지/서버 분리) + UI 역할 분리 + 두 정적 UI 프로토타입 + 통신 규약 v0.1 + **인메모리 더미 백엔드** |
| **v0.2** | **정적 대시보드 ↔ FastAPI 백엔드 라이브 연동.** 대시보드가 장치 목록·이벤트를 API 에서 직접 조회. 오염도·온습도 섹션은 화면에 유지되나 **미연동(미구현)** 으로 명시 표기. 저장소는 여전히 **인메모리(재시작 시 초기화)** |
| **v0.3** | **영속 저장소(SQLite) 도입.** 인메모리 dict 를 stdlib `sqlite3` 기반 저장소로 교체하여 **서버 재시작 후에도 데이터 유지.** API 응답 형태·통신 규약·엣지 에이전트는 변경 없음. DB 파일은 git 무시(`data/`). |

> v0.2/v0.3 는 대시보드 연동·영속화 마일스톤일 뿐이며, **오염도 점수 / 환경
> 온습도용 프로토콜 v0.2 가 구현되었다는 의미가 아닙니다.** 해당 데이터는 현재
> API/프로토콜에 정의되어 있지 않으며 향후 과제로 남아 있습니다. 통신 규약
> (`COMMUNICATION_PROTOCOL.md`)은 여전히 **v0.1 DRAFT** 입니다.

### UI 역할 요약

| 구분 | 라즈베리파이 로컬 디버그 UI | 중앙 서버 대시보드 UI |
| --- | --- | --- |
| 위치 | `edge-device/local_debug_ui/` | `server/static_dashboard/` |
| 동작 환경 | 엣지 디바이스 (라즈베리파이/Debian VM) | 외부 중앙 서버 |
| 대상 사용자 | 설치자, 현장 디버거 | 운영자, 관리자 |
| 주요 용도 | 설치 직후 상태 점검, 디버깅 | 다수 디바이스 통합 모니터링 |
| 다루는 장치 수 | 1대 (자기 자신) | 다수 |
| 디자인 | 매우 가볍고 단순 | 일반적인 대시보드 형태 |

자세한 내용은 [docs/UI_ROLE_SEPARATION.md](docs/UI_ROLE_SEPARATION.md) 참고.

### 빠르게 열어 보기 (정적 UI)

두 UI 모두 정적 HTML/CSS/JS 입니다. 빌드 도구가 필요 없습니다.

```
# 라즈베리파이 로컬 디버그 UI
cd edge-device/local_debug_ui
python3 -m http.server 8080      # http://localhost:8080

# 중앙 서버 대시보드 (프로토타입)
cd server/static_dashboard
python3 -m http.server 8000      # http://localhost:8000
```
또는 각 폴더의 `index.html` 을 브라우저로 직접 열어도 됩니다.

### 백엔드 프로토타입 실행

`COMMUNICATION_PROTOCOL.md` v0.1 의 최소 구현입니다. **v0.3 부터 SQLite 영속
저장소**(stdlib `sqlite3`)를 사용하며, DB 가 비어 있을 때만 시드 디바이스
1대(`rpi-001`)를 등록합니다. DB 파일은 기본적으로 `data/cctv.db`(git 무시)이며
`CCTV_DB_PATH` 환경변수로 변경할 수 있습니다. 자세한 설명은
[docs/BACKEND_PROTOTYPE.md](docs/BACKEND_PROTOTYPE.md) 참고.

```
# 서버 (FastAPI, 포트 9000)
pip install -r server/api/requirements.txt
python -m uvicorn server.api.main:app --port 9000      # http://localhost:9000/docs

# 엣지 송신 데모 (다른 터미널)
pip install -r edge-device/agent/requirements.txt
python edge-device/agent/demo.py
```
heartbeat / detections / event 각 1회씩 전송되며, 서버는 `X-Device-Api-Key`
검증 후 §5 의 에러 응답 포맷으로 응답합니다.

### 시스템 측에서 현재 구현하지 않는 것

- 전체 AI 추론 시스템
- ~~백엔드 API 전체~~ → **최소 더미 백엔드만 구현** (v0.3, SQLite 영속 저장소)
- YOLO 학습/파인튜닝 파이프라인
- 실제 OCR 파이프라인
- 모델 다운로드/배포 엔드포인트
- 오염도 점수 / 환경 온습도 의 프로토콜 정의 (대시보드에서 "미연동" 표기)

> 정적 대시보드는 실시간 CCTV 상태·이벤트를 백엔드 API 에서 직접 가져옵니다
> (오염도·온습도는 프로토콜 미정의로 미연동). 자세한 내용은
> [docs/BACKEND_PROTOTYPE.md](docs/BACKEND_PROTOTYPE.md) §5.1 참고.
