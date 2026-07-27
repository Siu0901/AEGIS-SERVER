# AEGIS API 명세서
**자율 현장 대응형 AI 안전관제 시스템** · 팀 AIM
v2.0 · 2026-07-18

---

## 1. 공통 규약

### 1.1 통신 구간

| 구간 | 프로토콜 | 용도 |
|---|---|---|
| 엣지 → 서버 | WebSocket `/ws/edge` | 프레임 메타데이터, 이벤트 후보, 하트비트 |
| 서버 → 대시보드 | WebSocket `/ws/dashboard` | 오버레이 좌표, 이벤트 알림, 지표 갱신 |
| 대시보드 → 서버 | REST `/api/v1/...` | 조회·검색·설정·명령 |
| 서버 → ESP32 | MQTT | 경고 발동, 장치 상태 수신 |
| 서버 → 클라우드 | HTTPS (Gemini API) | 임베딩·LLM 호출 |

**Base URL**: `http://<server-host>:8000/api/v1`

### 1.2 좌표계와 단위

혼동을 막기 위해 좌표는 **두 종류만** 사용하며 필드명으로 구분한다.

| 종류 | 표기 | 정의 |
|---|---|---|
| **정규화 픽셀 좌표** | 접미사 없음, 값 0.0~1.0 | 프레임 좌상단 원점, 우측·하단이 양수. **해상도로 나눈 비율값**이므로 640p 추론 결과를 1080p 화면에 그대로 대응시킬 수 있다 |
| **지면 실좌표** | 접미사 `_m` | 캘리브레이션 기준점을 원점으로 하는 현장 평면 좌표, 단위 미터 |

- **bbox 형식**: `[x1, y1, x2, y2]` (좌상단, 우하단, 정규화)

**화면비 제약 (중요)**

정규화 좌표가 성립하려면 **메인 스트림과 서브 스트림의 화면비가 같아야 한다.**
엣지는 서브(추론용)에서 좌표를 산출하지만, 대시보드는 그 좌표를 메인(라이브 영상) 위에 그린다.
화면비가 다르면 정규화 좌표가 한쪽 축으로 눌려 박스가 어긋난다.

| 스트림 | 해상도 | 화면비 | 용도 |
|---|---|---|---|
| 메인 | 1920×1080 | 16:9 | 서버 — 라이브·녹화·클립 |
| 서브 | 640×360 | **16:9 (동일)** | 엣지 — 추론 |

카메라 설정 변경 시 두 스트림의 화면비를 반드시 함께 확인한다.
서브를 정사각(640×640)으로 설정하면 화각이 잘리거나 좌표가 어긋나므로 사용하지 않는다.
- **거리**: 미터, 소수점 둘째 자리
- **시각**: ISO 8601 UTC 밀리초 포함. 저장 UTC, 표시 KST
- **track_id**: 카메라 내에서만 유효. 전역 식별은 `cam_id`와 조합. **person과 vehicle 모두에 부여된다**

### 1.3 감지 구조 (2단계 캐스케이드)

> **제로샷/오픈보캐블러리 감지는 채택하지 않는다.** 감지 클래스는 파인튜닝된 `person`·`vehicle` 2종으로 고정이며, 객체명을 런타임에 추가하는 API는 존재하지 않는다. (기능명세서 부록 A-1)

1단계 감지 모델은 **단일 모델이며 `person`과 `vehicle`(지게차) 두 클래스만** 출력한다. 클래스별로 모델을 분리하지 않는다 — 1회 추론으로 두 클래스를 얻는 편이 연산·메모리 측면에서 유리하고, 다중클래스 학습이 클래스 간 혼동도 줄이기 때문이다. 안전모 착용 여부는 사람 bbox를 크롭해 **2단계 분류 모델**이 판정하며, 그 결과가 `helmet` 필드로 실린다. 따라서 **안전모에 대한 별도 bbox는 존재하지 않는다.**

### 1.4 오류 응답

```json
{ "error": { "code": "ZONE_NOT_FOUND", "message": "요청한 구역이 존재하지 않습니다", "detail": { "zone_id": "z-9" } } }
```

| 코드 | HTTP | 의미 |
|---|---|---|
| `VALIDATION_ERROR` | 400 | 요청 형식 오류 |
| `NOT_FOUND` | 404 | 리소스 없음 |
| `EDGE_OFFLINE` | 503 | 엣지 미연결 |
| `CLOUD_UNAVAILABLE` | 503 | 클라우드 API 실패(실시간 안전 기능은 영향 없음) |
| `QUOTA_EXCEEDED` | 429 | API 한도 초과 |

---

## 2. 엣지 → 서버 (WebSocket `/ws/edge`)

### 2.1 `frame` — 프레임 메타데이터 (매 프레임)

대시보드 오버레이용 좌표 스트림. **영상과 마스크는 포함하지 않는다.** 마스크는 엣지 내부 계산(접지점·최근접 거리·자세 판정)에만 사용하고 결과값만 전송한다.

```json
{
  "type": "frame",
  "cam_id": 1,
  "ts": "2026-08-14T05:37:02.183Z",
  "objects": [
    {
      "class": "person",
      "track_id": 3,
      "conf": 0.91,
      "bbox": [0.197, 0.364, 0.273, 0.764],
      "helmet": "off",
      "helmet_conf": 0.88,
      "helmet_checked_at": "2026-08-14T05:37:01.900Z",
      "foot_point": [0.235, 0.762],
      "foot_point_m": [4.21, 7.85],
      "foot_conf": 0.88,
      "posture": "standing",
      "height_ratio": 0.97,
      "axis_angle_deg": 8.2,
      "stillness_s": 0.4,
      "in_zone": "forklift_lane"
    },
    {
      "class": "vehicle",
      "track_id": 11,
      "conf": 0.87,
      "bbox": [0.591, 0.389, 0.838, 0.756],
      "anchor_m": [7.02, 8.90],
      "moving": true,
      "danger_radius_m": 3.0
    }
  ]
}
```

**공통 필드**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `cam_id` | int | ✔ | 카메라 번호 |
| `ts` | string | ✔ | 프레임 촬영 시각. 서버가 링버퍼에서 클립을 잘라낼 기준이므로 NTP 동기화 필수 |
| `objects[].class` | string | ✔ | **`person` 또는 `vehicle`만** 사용. `vehicle`은 지게차 중심으로 학습된 산업차량 클래스 |
| `objects[].track_id` | int | ✔ | 추적 번호. person·vehicle 모두 부여 |
| `objects[].conf` | float | ✔ | 1단계 감지 신뢰도 0~1 |
| `objects[].bbox` | float[4] | ✔ | 정규화 경계상자 |

**person 전용 필드**

| 필드 | 타입 | 설명 |
|---|---|---|
| `helmet` | string·생략 | **2단계 분류 결과.** `on`(착용) / `off`(미착용) **2값만 존재한다.** 크기·신뢰도 게이트를 통과하지 못하고 직전 캐시도 없으면 **필드 자체를 생략**한다(§6.3) |
| `helmet_conf` | float·생략 | 분류 신뢰도 0~1. **`helmet` 이 실린 경우에만 함께 싣는다** |
| `helmet_checked_at` | string·생략 | 분류를 실제 **채택**한 시각. `helmet` 과 함께 싣는다. 이 값이 현재 `ts`보다 과거이면 캐시 또는 게이팅 보류로 값이 갱신되지 않고 있음을 의미한다 |
| `foot_point` | float[2] | 접지점의 정규화 픽셀 좌표 (산출법 §6.1) |
| `foot_point_m` | float[2] | 접지점의 지면 실좌표(m). 거리·구역 판정 기준 |
| `foot_conf` | float | 접지점 신뢰도. 낮으면 뎁스 검증이 트리거됨 |
| `posture` | string | `standing` / `fallen` / `unknown` (산출법 §6.4) |
| `height_ratio` | float | 마스크 높이 ÷ 해당 거리 기대 높이. 낮을수록 서 있지 않은 상태 |
| `axis_angle_deg` | float | 마스크 주축과 수직축의 각도(도). 0에 가까우면 수직, 90에 가까우면 수평 |
| `stillness_s` | float | 정지 상태 지속 시간(초) |
| `in_zone` | string·null | 접지점이 포함된 구역 ID. **필드는 항상 싣고, 해당 없으면 `null`** |

**vehicle(지게차) 전용 필드**

| 필드 | 타입 | 설명 |
|---|---|---|
| `anchor_m` | float[2] | 지게차의 지면 기준점 실좌표. 지게차는 지면 주행 장비라 접점이 명확하다 |
| `moving` | bool | 최근 프레임 대비 위치 변화 여부. **이동 중이면 위험도를 상향 조정**한다 |
| `danger_radius_m` | float | 해당 클래스에 설정된 위험 반경. 지게차 기본 3.0m |

---

**필수 · 선택 규약**

위 표에서 **`·생략` 표기가 있는 필드만 선택**이며, 나머지는 모두 필수다.
`·null` 표기가 있는 필드는 **필드 자체는 항상 싣고 값만 `null`** 이 될 수 있다.
이 규약은 §2.1~§2.4 전체에 동일하게 적용된다.

---

### 2.2 `candidate` — 이벤트 후보

규칙에 걸렸을 때만 전송한다. **확정·경고 판단은 서버가 한다.**

```json
{
  "type": "candidate",
  "cam_id": 1,
  "ts": "2026-08-14T05:37:02.183Z",
  "track_id": 3,
  "violations": ["no_helmet", "zone_intrusion"],
  "zone_id": "forklift_lane",
  "bbox": [0.197, 0.364, 0.273, 0.764],
  "conf": 0.91,
  "foot_point_m": [4.21, 7.85],
  "foot_conf": 0.88,
  "helmet": "off",
  "helmet_conf": 0.88,
  "posture": "standing",
  "observed_ms": 3200,
  "nearby": [
    {
      "class": "vehicle",
      "track_id": 11,
      "dist_m": 3.2,
      "method": "mask_nearest",
      "depth_verified": true,
      "moving": true,
      "within_danger_radius": true
    }
  ]
}
```

**필드 설명**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `track_id` | int | ✔ | 위반 대상 사람의 추적 번호. 서버는 이 값으로 중복 병합과 시정 추적을 수행 |
| `violations[]` | string[] | ✔ | 동시 발생 가능. `no_helmet` / `zone_intrusion` / `proximity` / `fall` |
| `zone_id` | string·null | ✔ | 침입한 구역 ID. **필드는 항상 싣고, 해당 없으면 `null`** (§2.1 `in_zone` 과 동일 규약) |
| `foot_point_m` | float[2] | ✔ | 위반 발생 지점 실좌표 |
| `helmet` / `helmet_conf` | string / float | | 2단계 분류 결과. `no_helmet` 위반의 근거 |
| `cam_id` / `ts` | int / string | ✔ | 카메라 번호와 후보 발생 시각 |
| `bbox` / `conf` | float[4] / float | ✔ | 대상의 박스와 감지 신뢰도 |
| `foot_conf` | float | | 접지점 신뢰도. **`fall` 등 접지점이 무의미한 경우 생략 가능** |
| `posture` | string | | `fall` 위반의 근거 |
| `observed_ms` | int | ✔ | 엣지가 이 조건을 연속 관측한 시간(ms). 서버 확정 판정의 참고값 |
| `nearby[]` | array | | **주변 위험 지게차 목록** — 아래 상세 |

**`nearby[]` 상세**

해당 사람 주변에서 위험 요인이 될 수 있는 지게차 목록이다. 감지된 각 지게차와의 거리를 계산해 **스크리닝 반경(기본 5m) 안에 든 것만** 담는다. 주변에 없으면 빈 배열 `[]`.

| 필드 | 타입 | 설명 |
|---|---|---|
| `class` | string | `vehicle` |
| `track_id` | int | 지게차 추적 번호. **뎁스 캐시 키 구성에 사용** |
| `dist_m` | float | 사람과의 실제 거리(m). 포크가 뻗은 상태에서는 `mask_nearest` 방식이 정확하다 |
| `method` | string | `bbox_center`(초기 구현) / `mask_nearest`(윤곽 최근접, 정밀). 포크 끝단이 실제 접촉 위험 지점이므로 후자가 안전 판정에 정확 |
| `depth_verified` | bool | 뎁스 검증 통과 여부. `true`면 원근 착시가 아닌 실제 근접. 트리거 미충족으로 미실행 시에도 `false` |
| `moving` | bool | 지게차 이동 여부 |
| `within_danger_radius` | bool | 지게차 위험 반경(기본 3.0m) 이내인지 |

**용도**: ① `proximity` 위반 판정의 근거, ② LLM 분석 컨텍스트("이동 중인 지게차 3.2m 이내").

---

**후보를 조용히 버리지 않는다 (중요)**

서버는 수신한 `candidate` 가 스키마 검증에 실패해도 **로그 없이 폐기해서는 안 된다.**
안전 시스템에서 감지된 위반이 검증 단계에서 소리 없이 사라지는 것은 오탐보다 위험하다.

| 처리 | 내용 |
|---|---|
| 기록 | 원본 페이로드와 검증 오류를 `WARNING` 이상으로 로깅 |
| 집계 | `edge_msg_rejected_total{type, reason}` 카운터 증가 |
| 노출 | `GET /system/status` 와 대시보드 시스템 상태에 거부 건수를 표시 |

엣지 구현이 바뀌어 필드가 누락되기 시작하면 이 카운터로 즉시 드러나야 한다. (FN-SYS-06)

**재전송은 요청하지 않는다.** 서버는 NACK을 보내지 않고 일방적으로 폐기한 뒤 집계만 한다. 스키마 불일치는 일시적 장애가 아니라 **엣지 코드의 결함**이므로 재전송해도 같은 결과가 반복되며, 실시간 안전 루프에 재시도 대기를 넣으면 지연만 늘어난다. 엣지→서버 방향의 모든 메시지는 재전송 없는 단방향 전송이며, 유실은 다음 프레임으로 자연히 복구된다.

---

### 2.3 `track_lost` — 트랙 소실 통지

추적 중이던 대상이 관측되지 않게 되었을 때 전송한다. 서버는 해당 트랙에 진행 중인 이벤트를 `lost` 상태로 전이하고 재결합 대기에 넣는다.

```json
{
  "type": "track_lost",
  "cam_id": 1,
  "track_id": 3,
  "class": "person",
  "last_ts": "2026-08-14T05:37:09.410Z",
  "last_foot_point_m": [4.55, 7.90],
  "last_helmet": "off",
  "reason": "occluded"
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `last_ts` | string | 마지막으로 관측된 시각. 재결합 시간 창 `Δt` 산출 기준 |
| `last_foot_point_m` | float[2] | 마지막 지면 실좌표. **재결합 반경 판정의 기준점** |
| `last_helmet` | string·생략 | 소실 직전 분류 결과 |
| `reason` | string | `occluded`(가림) / `out_of_view`(화면 이탈) / `low_conf`(신뢰도 저하) — 진단용 |

※ ByteTrack 자체 트랙 버퍼로 복구되는 짧은 단절은 이 메시지를 발생시키지 않는다. 엣지가 최종적으로 트랙을 포기한 시점에만 전송한다.

---

### 2.4 `heartbeat` — 상태 보고 (5초 주기)

```json
{
  "type": "heartbeat", "ts": "2026-08-14T05:37:05.000Z",
  "cameras": [
    {"cam_id": 1, "sub_state": "ok", "fps": 8.2},
    {"cam_id": 2, "sub_state": "ok", "fps": 8.0}
  ],
  "gpu_util": 0.41, "mem_used_mb": 3820,
  "cls_calls_per_min": 96,
  "cls_cache_hit_rate": 0.87,
  "depth_calls_per_min": 14
}
```

| 필드 | 설명 |
|---|---|
| `cameras[]` | 카메라별 상태 배열. **`cam_id` 는 int** 이며 §2.1 `cam_id` 와 같은 값이다 |
| `cameras[].sub_state` | 엣지가 보는 **서브 스트림** 상태: `ok` / `reconnecting` / `down` |
| `cameras[].fps` | 해당 카메라의 실제 처리 프레임 수. 8 미만 지속 시 대시보드 경고 |
| `gpu_util` / `mem_used_mb` | GPU 사용률과 메모리 사용량 |
| `cls_calls_per_min` | 2단계 분류 호출 횟수 |
| `cls_cache_hit_rate` | 분류 캐시 적중률. 낮으면 캐시 유효기간 조정 필요 |
| `depth_calls_per_min` | 뎁스 호출 빈도. 과다하면 회색지대 밴드 재조정 필요 |

---

## 3. 서버 → ESP32 (MQTT)

**토픽**: `aegis/alert` (서버 발행 → ESP32 구독)

```json
{
  "event_id": "EV-20260814-0231",
  "type": "no_helmet",
  "level": 2,
  "zone_id": "forklift_lane",
  "duration_s": 5,
  "repeat": false
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `type` | string | 위반 유형. ESP32는 이 값으로 점멸 패턴 결정 |
| `level` | int | 위험 등급. 1=주의(부저 없음), 2=경고, **3=긴급(연속 부저) — `fall`은 항상 3** |
| `duration_s` | int | 경광등·부저 지속 시간 |
| `repeat` | bool | 재경고 여부. `true`면 패턴을 달리해 상습 상황 구분 |

**토픽**: `aegis/device/status` (ESP32 발행 → 서버 구독)

```json
{ "device": "esp32-01", "online": true, "uptime_s": 84210, "last_alert": "2026-08-14T05:37:03Z" }
```

---

## 4. REST API

### 4.1 이벤트

#### `GET /events`

**쿼리 파라미터**: `from`, `to`, `cam_id`, `type`, `status`, `zone_id`, `limit`, `cursor`

```json
{
  "items": [
    {
      "event_id": "EV-20260814-0231",
      "cam_id": 1, "track_id": 3,
      "violation_type": "no_helmet",
      "zone_id": "forklift_lane",
      "status": "alerted",
      "detected_at": "2026-08-14T05:37:02.183Z",
      "confirmed_at": "2026-08-14T05:37:03.005Z",
      "alerted_at": "2026-08-14T05:37:03.010Z",
      "resolved_at": null,
      "resolution_sec": null,
      "alert_count": 1,
      "min_distance_m": 3.2,
      "posture": "standing",
      "repeat_count_7d": 4,
      "thumbnail_url": "/media/kf/EV-20260814-0231_0.jpg"
    }
  ],
  "next_cursor": "eyJ0cyI6..."
}
```

| 필드 | 설명 |
|---|---|
| `violation_type` | `no_helmet` / `zone_intrusion` / `proximity` / `fall` |
| `status` | 상태머신 값 (기능명세서 §4.2) |
| `detected_at` / `confirmed_at` / `alerted_at` | 최초 후보 관측 · 확정 · 경고 발동 시각 |
| `resolution_sec` | `alerted_at`→`resolved_at` 소요 초. **시정률 지표의 원천** |
| `posture` | 확정 시점 자세. `fall` 이벤트의 근거 |
| `repeat_count_7d` | 동일 트랙·구역의 최근 7일 유사 이벤트 수 |

#### `GET /events/{event_id}`

목록 필드에 다음이 추가된다.

```json
{
  "clip_url": "/media/clips/EV-20260814-0231.mp4",
  "keyframe_urls": ["/media/kf/..._0.jpg", "/media/kf/..._1.jpg"],
  "helmet_conf": 0.88,
  "stillness_s": 0.4,
  "height_ratio": 0.97,
  "depth_verified": true,
  "nearby_snapshot": [
    {"class":"vehicle","track_id":11,"dist_m":3.2,"depth_verified":true,"moving":true,"within_danger_radius":true}
  ],
  "llm_analysis": "3번 작업자가 이동 중인 지게차 3.2m 이내에서 ...",
  "regulation_refs": [{"code":"산업안전보건기준에 관한 규칙 제32조","title":"보호구의 지급 등"}],
  "similar_incidents": [{"title":"2024 지게차 후진 부딪힘 사망사고","source":"KOSHA","similarity":0.84}],
  "timeline": [
    {"at":"2026-08-14T05:37:02.183Z","state":"candidate"},
    {"at":"2026-08-14T05:37:02.983Z","state":"active"},
    {"at":"2026-08-14T05:37:03.010Z","state":"alerted"}
  ]
}
```

| 필드 | 설명 |
|---|---|
| `nearby_snapshot` | 확정 시점의 주변 지게차 상태 스냅샷 |
| `llm_analysis` | 클라우드 분석 결과. 미생성 시 `null`(실시간 기능과 무관) |
| `regulation_refs` | **사전 매핑 테이블**로 연결된 조항(LLM 생성 아님) |
| `similar_incidents` | 임베딩 유사도로 매칭된 과거 사례 |

#### `PATCH /events/{event_id}`

```json
{ "is_false_positive": true, "note": "허리 굽혀 작업 중이었으나 쓰러짐으로 오탐" }
```
또는 `{ "force_resolve": true }` — 시스템이 놓친 시정을 수동 종결. **`fall` 이벤트는 관리자 확인으로 종결하는 것이 기본 절차**다.

#### `GET /events/{event_id}/clip` — 클립 스트리밍 (video/mp4)

---

### 4.2 지표

#### `GET /metrics/summary`

```json
{
  "period": "today",
  "correction_rate": 0.87,
  "undetermined_rate": 0.05,
  "total_violations": 23,
  "resolved": 20,
  "unresolved": 2,
  "undetermined": 1,
  "avg_resolution_sec": 41,
  "fall_events": 0,
  "anomaly_flags": 1
}
```

| 필드 | 산출 |
|---|---|
| `correction_rate` | `resolved / (resolved + unresolved)`. **`fall`과 `expired`는 제외** |
| `undetermined` | 재결합 실패로 종결된 `expired` 건수. **시정률 분모·분자 모두에서 제외** |
| `undetermined_rate` | `expired / (resolved + unresolved + expired)`. 시정률과 **항상 병기**한다 |
| `fall_events` | 쓰러짐 이벤트 수. 별도 집계 |
| `avg_resolution_sec` | `resolution_sec` 평균 |

#### `GET /metrics/timeseries?metric=..&bucket=..&from=..&to=..`

`metric`: `violations` / `correction_rate` / `avg_resolution_sec` / `undetermined_rate`
`bucket`: `hour` / `day` / `week`

```json
{ "metric":"correction_rate","bucket":"day",
  "points":[ {"t":"2026-08-12","value":0.81,"n":18},
             {"t":"2026-08-13","value":0.87,"n":23} ] }
```

| 필드 | 설명 |
|---|---|
| `points[].t` | 버킷 시작 시각 |
| `points[].value` | 지표값. 비율 지표는 0~1, 건수 지표는 정수 |
| `points[].n` | 해당 버킷의 모집단 크기. 표본이 작을 때 비율을 신뢰하지 않기 위해 함께 제공한다 |

#### `GET /metrics/distribution?by=..&from=..&to=..`

`by`: `violation_type` / `zone` / `camera` / `hour_of_day`

```json
{ "by":"violation_type",
  "buckets":[ {"key":"no_helmet","label":"안전모 미착용","count":13,"ratio":0.57},
              {"key":"zone_intrusion","label":"금지구역 침입","count":7,"ratio":0.30} ] }
```

`by=hour_of_day` 는 0~23 을 `key` 로 사용하며 시간대 히트맵의 데이터원이 된다.

#### `GET /metrics/repeat?days=7&limit=10`

```json
{ "days":7,
  "items":[ {"subject":"zone","key":"forklift_lane","label":"지게차 통행로",
             "violation_type":"no_helmet","count":9,"last_at":"2026-08-14T05:37:03Z"} ] }
```

| 필드 | 설명 |
|---|---|
| `subject` | 집계 대상: `zone` / `camera` / `track` |
| `count` | 기간 내 반복 횟수 |

※ 작업자 개인 단위 누적은 하지 않는다. `track` 은 세션 내 추적 번호일 뿐 신원이 아니다.

---

### 4.3 영상 검색

#### `POST /search/scenes`

```json
{ "query": "지난주 지게차 근처에서 안전모 안 쓴 장면", "top_k": 12,
  "filters": { "from":"2026-08-05","to":"2026-08-12","cam_id":null } }
```

```json
{
  "mode": "hybrid",
  "items": [
    { "event_id":"EV-20260813-0187","similarity":0.94,
      "title":"안전모 미착용 · 지게차 근처","cam_id":1,
      "occurred_at":"2026-08-13T06:22:11Z",
      "thumbnail_url":"/media/kf/...jpg","clip_url":"/media/clips/...mp4" }
  ]
}
```

| 필드 | 설명 |
|---|---|
| `mode` | `sql` / `vector` / `hybrid`. 서버가 질의를 분석해 자동 선택 |
| `similarity` | 질의 임베딩과 키프레임 임베딩의 코사인 유사도 |

---

### 4.4 챗봇 · 보고서

#### `POST /assistant/chat`

```json
{ "session_id":"s-2026-0814-01", "message":"이번 주 금지구역 위반 통계 보여줘" }
```

```json
{
  "route": "sql",
  "answer": "8월 금지구역 위반 61건, 평균 시정 33초입니다. 지게차 통행로가 72%로 최다입니다.",
  "attachments": [],
  "sources": [{"type":"query","detail":"events where type=zone_intrusion"}]
}
```

| 필드 | 설명 |
|---|---|
| `route` | `sql`(통계) / `vector`(장면 검색) / `vision`(현재 화면 브리핑) |
| `attachments[]` | 답변에 딸린 첨부. 아래 형태 |

**`attachments[]` 원소**

```json
{ "kind":"clip","event_id":"EV-20260814-0231",
  "clip_url":"/media/clips/EV-20260814-0231.mp4",
  "thumbnail_url":"/media/keyframes/EV-20260814-0231_0.jpg",
  "label":"안전모 미착용 · 카메라 1 · 8/13 15:22" }
```

| `kind` | 추가 필드 |
|---|---|
| `clip` | `event_id`, `clip_url`, `thumbnail_url`, `label` |
| `image` | `image_url`, `label` |
| `table` | `columns[]`, `rows[][]`, `label` — SQL 집계 결과 표시용 |
| `event_ref` | `event_id`, `label` — 상세 화면으로 이동하는 링크 |

모든 첨부는 **URL 규약**을 따른다. 서버 파일 경로를 싣지 않는다.
| `sources[]` | 근거 |

#### `POST /assistant/briefing`
```json
{ "cam_ids": [1,2] }
```
```json
{ "summary":"카메라 2대 정상 가동 중. 카메라 1에 안전모 미착용 위반 1건 진행 중(경고 방송됨), 카메라 2는 이상 없음.",
  "captured_at":"2026-08-14T05:40:00Z" }
```

#### `POST /reports/weekly`
```json
{ "from":"2026-08-08", "to":"2026-08-14" }
```
```json
{ "report_id":"RP-20260814-01","status":"generating","estimated_sec":20 }
```

---

### 4.5 설정

#### `POST /cameras/{cam_id}/calibration`

```json
{
  "points": [
    { "px": [0.21,0.83], "m": [0.0, 0.0] },
    { "px": [0.68,0.80], "m": [5.0, 0.0] },
    { "px": [0.75,0.55], "m": [5.0, 5.0] },
    { "px": [0.28,0.57], "m": [0.0, 5.0] }
  ],
  "reference_person": { "px_height": 0.42, "at_m": [2.5, 3.0] }
}
```

| 필드 | 설명 |
|---|---|
| `points[].px` | 화면에서 클릭한 지점(정규화 좌표) |
| `points[].m` | 그 지점의 실제 지면 좌표(m). 줄자 실측. 첫 점을 원점(0,0)으로 권장 |
| `reference_person` | **높이 비율 기준 보정용(선택).** 특정 위치에 선 사람의 화면상 높이를 1회 입력하면 거리별 기대 높이 곡선을 보정할 수 있다. 미입력 시 카메라 기하로 추정 |

**응답**

```json
{ "homography": [[..],[..],[..]], "reprojection_error_m": 0.11, "ref_height_calibrated": true }
```

#### `GET /zones` / `POST /zones`

```json
{ "zone_id":"forklift_lane","cam_id":1,"name":"지게차 통행로",
  "polygon_m": [[1.2,2.0],[6.4,2.0],[6.4,7.5],[1.2,7.5]],
  "buffer_m": 0.4, "active": true }
```

| 필드 | 설명 |
|---|---|
| `polygon_m` | **지면 실좌표 기준** 꼭짓점 배열. 화면에서 그린 픽셀 좌표를 서버가 호모그래피로 변환해 저장 |
| `buffer_m` | 경계 여유. 호모그래피 오차 흡수 및 사전 경고용 |

#### `GET /vehicle-classes` / `PATCH /vehicle-classes/{name}`

```json
{ "class_name": "vehicle", "danger_radius_m": 3.0, "active": true }
```

클래스별 위험 반경. **지게차 기본값 3.0m**(제조현장 실내 통행 기준)이며, 통로 폭과 운용 속도에 따라 조정한다. 근접 경고 임계값(`proximity_threshold_m`)과 함께 2단계로 동작한다 — 위험 반경은 장비를 따라다니는 동적 영역, 근접 임계값은 즉시 경고 기준이다.

#### `GET /policies` / `PATCH /policies`

```json
{
  "confirm_duration_s": 3,
  "resolve_duration_s": 10,
  "cooldown_s": 30,
  "resolve_window_s": 300,
  "track_lost_grace_s": 15,
  "reassoc_window_s": 10,
  "reassoc_max_speed_ms": 1.5,
  "reassoc_radius_cap_m": 5.0,
  "proximity_threshold_m": 2.0,
  "vehicle_danger_radius_m": 3.0,
  "depth_band_m": [2.0, 3.5],
  "depth_cache_ms": 500,
  "screening_radius_m": 5.0,
  "min_confidence": 0.55,
  "cls_cache_ms": 1000,
  "cls_min_crop_px": 64,
  "cls_min_conf": 0.60,
  "clip_pre_roll_s": 10,
  "clip_post_roll_s": 10,
  "overlay_buffer_ms": 300,
  "overlay_stale_ms": 1000,
  "fall_height_ratio_max": 0.5,
  "fall_axis_angle_min_deg": 55.0,
  "fall_stillness_s": 5.0,
  "anomaly_sample_interval_min": 5
}
```

| 필드 | 설명 |
|---|---|
| `confirm_duration_s` | 후보 → 확정 지속 조건 |
| `resolve_duration_s` | 위반 소멸 → 해소 판정 지속 조건 |
| `cooldown_s` | 재경고 최소 간격 |
| `resolve_window_s` | 이 시간 내 해소된 건만 시정률 분자에 포함 (기본 300초) |
| `track_lost_grace_s` | 트랙 소실 후 `expired` 종결까지의 유예 (기본 15초) |
| `reassoc_window_s` | 재결합을 시도하는 최대 경과 시간 |
| `reassoc_max_speed_ms` | 재결합 반경 산출용 최대 보행속도(m/s). **반경 = 이 값 × Δt** |
| `reassoc_radius_cap_m` | 재결합 반경 상한 |
| `proximity_threshold_m` | 근접 위반 판정 거리(즉시 경고 기준) |
| `vehicle_danger_radius_m` | 지게차를 중심으로 따라다니는 동적 위험 영역 반경. 기본 3.0m |
| `depth_band_m` | 뎁스 검증 회색지대 |
| `depth_cache_ms` | 동일 객체 쌍 뎁스 결과 재사용 시간 |
| `screening_radius_m` | `nearby`에 포함할 최대 거리 |
| `cls_cache_ms` | **분류 결과 캐시 유효기간.** 클수록 GPU 부담 감소, 반응 지연 증가 |
| `cls_min_crop_px` | **최소 크롭 높이.** 미달 시 분류 결과를 채택하지 않는다 |
| `cls_min_conf` | **최소 분류 신뢰도.** 미달 시 결과를 채택하지 않는다 |
| `clip_pre_roll_s` / `clip_post_roll_s` | 이벤트 클립의 사전·사후 구간(초) |
| `overlay_buffer_ms` | 대시보드 오버레이 지연 버퍼. 영상–좌표 시간 정합용 |
| `overlay_stale_ms` | 이 시간 이상 좌표 갱신이 없으면 박스를 흐리게 표시 |
| `fall_height_ratio_max` | 높이 비율이 이 값 이하이면 쓰러짐 조건 ① 충족 |
| `fall_axis_angle_min_deg` | 주축 각도가 이 값 이상이면 조건 ② 충족 |
| `fall_stillness_s` | 정지 지속이 이 값 이상이면 조건 ③ 충족 |
| `anomaly_sample_interval_min` | 정상 풀 샘플링 주기(분). 기본 5 |

#### `POST /alerts/manual` / `POST /alerts/mute`

```json
{ "cam_id":1, "sound":"custom_notice", "level":2 }
{ "cam_id":1, "minutes":15, "reason":"정비 작업" }
```

---

### 4.6 시스템

#### `GET /system/status`

```json
{
  "edge": { "online": true, "gpu_util":0.41,
            "cls_cache_hit_rate":0.87, "depth_calls_per_min":14,
            "msg_rejected_total":0 },
  "cameras": [{"cam_id":1,"main_state":"ok","sub_state":"ok","fps":8.2},
              {"cam_id":2,"main_state":"ok","sub_state":"ok","fps":8.0}],
  "mcu": { "online": true, "last_seen":"2026-08-14T05:39:58Z" },
  "cloud": { "available": true, "quota_used": 0.62 },
  "storage": { "retention_days":7, "free_gb":512 },
  "time_sync": { "edge_offset_ms": 12 }
}
```

| 필드 | 설명 |
|---|---|
| `cameras[].main_state` | **서버가 보는 메인 스트림**(1080p, 라이브·녹화용) 상태 |
| `cameras[].sub_state` | **엣지가 보는 서브 스트림**(640×360, 추론용) 상태. `heartbeat` 값을 그대로 전달 |
| `cameras[].fps` | 엣지의 실제 처리 fps |

**상태 값이 두 종류인 이유**

메인과 서브는 **서로 다른 스트림**이고 관측 주체도 다르다. 메인이 끊겨도 추론은 계속되고, 서브가 끊겨도 녹화는 계속된다. 하나로 합치면 어느 쪽이 죽었는지 구분할 수 없으므로 분리해서 노출한다.

| 열거형 | 값 | 적용 대상 |
|---|---|---|
| `StreamState` | `ok` / `reconnecting` / `down` | 카메라 스트림 (`main_state`, `sub_state`, §5.3 `component == "camera"` 인 경우의 `state`) |
| `ComponentState` | `ok` / `degraded` / `down` | 시스템 구성요소 (§5.3 `system.state`, **`component != "camera"` 인 경우**) |

스트림에는 `degraded` 가, API에는 `reconnecting` 이 의미가 없으므로 두 열거형을 통합하지 않는다.
| `edge.msg_rejected_total` | 스키마 검증에 실패해 거부된 엣지 메시지 누적 건수 (FN-SYS-06). 0이 아니면 대시보드에 경고를 띄운다 |
| `cloud.quota_used` | 무료 한도 사용률. 초과 시 분석 기능만 중단되고 안전 기능은 무관 |
| `time_sync.edge_offset_ms` | 엣지-서버 시각 차이. 크면 클립 추출 구간이 어긋남 |

---

## 5. 서버 → 대시보드 (WebSocket `/ws/dashboard`)

| `type` | 내용 |
|---|---|
| `overlay` | 엣지 `frame`을 서버가 이벤트 상태로 보강한 오버레이 데이터 |
| `event_created` | 신규 확정 이벤트 |
| `event_updated` | 상태 변경(경고·해소·재경고·소실·종결) |
| `metric` | 지표 갱신 |
| `anomaly` | 이상 탐지 플래그 |
| `system` | 구성요소 상태 변화 |

**구조 규약**

모든 대시보드 메시지는 **평면(flat)** 구조다. `type` 과 나머지 필드가 같은 깊이에 온다.
중첩은 다음 두 경우에만 허용한다.

| 허용 | 예 |
|---|---|
| 배열 원소 | `objects[]`, `nearby[]` |
| **REST 리소스를 그대로 전달하는 단일 객체** | `zone_updated.zone` (§5.4) |

두 번째 예외를 둔 이유는 클라이언트가 `GET /zones` 응답과 **같은 형태**로 캐시를 갱신할 수 있게 하기 위함이다. 이 경우 외에 새로운 중첩을 추가하지 않는다.

**경로 규약**

클라이언트로 내려가는 모든 파일 참조는 **URL**이다(`*_url`, `*_urls`).
서버 파일시스템 경로(`clip_path`, `keyframe_paths`)를 그대로 실어보내지 않는다.

---

### 5.1 `overlay`

`frame`(§2.1)을 그대로 전달하지 않는다. 서버가 **진행 중인 이벤트 상태와 근접 거리를
합쳐서** 내려보낸다. 클라이언트가 위반 여부를 스스로 추론하지 않게 하기 위함이며,
FN-UI-02 표시 규칙(위반자 적색·근접 거리선·거리 라벨)을 채우려면 이 정보가 필요하다.

```json
{
  "type": "overlay",
  "cam_id": 1,
  "ts": "2026-08-14T05:37:12.480Z",
  "objects": [
    {
      "class": "person",
      "track_id": 3,
      "bbox": [0.197, 0.364, 0.273, 0.764],
      "foot_point": [0.235, 0.762],
      "in_zone": "forklift_lane",
      "helmet": "off",
      "posture": "standing",
      "violations": ["no_helmet", "proximity"],
      "event_ids": ["EV-20260814-0231", "EV-20260814-0232"],
      "alert_state": "alerted",
      "nearby": [
        { "track_id": 11, "class": "vehicle", "dist_m": 3.2,
          "anchor": [0.714, 0.754], "in_danger_zone": false }
      ]
    },
    {
      "class": "vehicle",
      "track_id": 11,
      "bbox": [0.591, 0.389, 0.838, 0.756],
      "anchor": [0.714, 0.754],
      "moving": true,
      "danger_radius_m": 3.0,
      "violations": [],
      "event_ids": [],
      "alert_state": null,
      "nearby": []
    }
  ]
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `ts` | string | **원본 프레임 시각.** 시간 정합의 기준이며 반드시 포함한다 |
| `objects[].bbox` | float[4] | **`[x1, y1, x2, y2]`** 좌상단·우하단 정규화 좌표(§1.2). `[x, y, w, h]` 가 아니다 |
| `objects[].violations` | string[] | 현재 이 트랙에 걸려 있는 위반 유형. 없으면 빈 배열. **박스 색을 결정한다** |
| `objects[].event_ids` | string[] | 대응하는 진행 중 이벤트 ID. 클릭 시 상세로 이동 |
| `objects[].alert_state` | string·null | `active` / `alerted` / `re_alerted` / `lost` 중 하나. 없으면 `null` |
| `objects[].nearby[].dist_m` | float | 사람↔차량 지면 거리. **거리선 라벨(예: 3.2 m)의 원천** |
| `objects[].nearby[].anchor` | float[2] | 상대 차량의 정규화 접지 좌표. 거리선의 반대편 끝점 |
| `objects[].nearby[].in_danger_zone` | bool | 위험 반경 이내 여부 |

`objects[]` 의 좌표·자세·분류 필드는 §2.1 과 동일한 의미와 규약을 따른다.

**금지구역 폴리곤은 이 메시지에 싣지 않는다.** 매 프레임 변하지 않으므로
`GET /zones` 로 한 번 조회해 캐시하고, `zone_updated` 수신 시 갱신한다.

---

### 5.2 `event_created` / `event_updated`

```json
{ "type":"event_created","event_id":"EV-20260814-0231","cam_id":1,
  "violation_type":"no_helmet","track_id":3,"zone_id":"forklift_lane",
  "status":"alerted","confirmed_at":"2026-08-14T05:37:03Z",
  "alerted_at":"2026-08-14T05:37:03Z","severity":2,
  "keyframe_url":"/media/keyframes/EV-20260814-0231_0.jpg" }
```

```json
{ "type":"event_updated","event_id":"EV-20260814-0231",
  "status":"resolved","resolved_at":"2026-08-14T05:37:40Z","resolution_sec":37 }
```

`event_updated` 는 변경된 필드만 싣는다. `event_id` 와 `status` 는 항상 포함한다.

**전이별 동반 필드**

| 전이 | 함께 싣는 필드 |
|---|---|
| → `alerted` | `alerted_at`, `alert_count`, `severity` |
| → `re_alerted` | `alerted_at`(최근), `alert_count` |
| → `lost` | `lost_at` |
| `lost` → 복귀 | `track_id`(갱신된 값), `reassoc_count` |
| → `resolved` | `resolved_at`, `resolution_sec` |
| → `expired` | `expired_at` |
| 클립 준비 완료 | `clip_status`, `clip_url` |
| 수동 정정 | `is_false_positive`, `note` |

**`severity`**: `1`(주의) / `2`(경고) / `3`(긴급). §3 `AlertCommand.level` 과 동일한 척도이며 같은 값을 쓴다.

**필드명 규약**: 위반 유형 필드는 REST(§4.1)와 동일하게 `violation_type` 을 쓴다.

---

### 5.3 `metric` / `anomaly` / `system`

```json
{ "type":"metric","period":"today","correction_rate":0.87,
  "undetermined_rate":0.05,"total_violations":23,"resolved":20,
  "unresolved":2,"undetermined":1,"avg_resolution_sec":41,
  "fall_events":0,"anomaly_flags":1 }
```

```json
{ "type":"anomaly","anomaly_id":91,"cam_id":1,"score":0.71,
  "detected_at":"2026-08-14T02:14:00Z",
  "note":"평소와 다른 상황","keyframe_url":"/media/keyframes/anom_91.jpg" }
```

```json
{ "type":"system","component":"cloud_api","state":"degraded",
  "detail":"쿼터 62%","at":"2026-08-14T05:30:00Z" }
```

```json
{ "type":"system","component":"camera","cam_id":2,"stream":"main",
  "state":"reconnecting","detail":"RTSP 재연결 시도 2회",
  "at":"2026-08-14T05:31:12Z" }
```

`system` 은 **변화한 구성요소 하나만** 보낸다. 전체 스냅샷이 필요하면
`GET /system/status` 를 사용한다.

**`component` 에 따라 `state` 의 값 집합과 필수 필드가 달라진다.**

| `component` | 대상 | 추가 필수 필드 | `state` 값 집합 |
|---|---|---|---|
| `camera` | 카메라 **스트림** | `cam_id`, `stream` | `StreamState` |
| `edge` | Jetson 추론 프로세스 | — | `ComponentState` |
| `mcu` | ESP32 경고 장치 | — | `ComponentState` |
| `cloud_api` | Gemini API | — | `ComponentState` |
| `storage` | 영상 저장소 | — | `ComponentState` |
| `db` | PostgreSQL | — | `ComponentState` |

| 열거형 | 값 | 의미 |
|---|---|---|
| `StreamState` | `ok` / `reconnecting` / `down` | 연결이 있거나, 재시도 중이거나, 끊김 |
| `ComponentState` | `ok` / `degraded` / `down` | 정상이거나, 동작하나 성능·한도 저하이거나, 사용 불가 |

**`camera` 만 다른 이유**: 카메라는 구성요소가 아니라 **스트림 두 개**(메인 1080p / 서브 640×360)를 가진 대상이다. 둘은 독립적으로 끊기므로 어느 쪽이 바뀌었는지를 `stream` 필드로 지정한다. 그리고 스트림에는 "동작하나 성능 저하"라는 중간 상태가 없고 대신 "재연결 중"이 있으므로 값 집합이 다르다.

| `stream` | 대상 | 관측 주체 |
|---|---|---|
| `main` | 1920×1080, 라이브·녹화·클립 | 서버 |
| `sub` | 640×360, 추론 | 엣지 (`heartbeat` 경유) |

이 메시지를 받으면 대시보드는 캐시된 `GET /system/status` 의 해당 카메라
`main_state` 또는 `sub_state` 를 갱신한다.

**검증 규칙**: `component == "camera"` 이면 `cam_id` 와 `stream` 이 필수이고 `state` 는 `StreamState` 로 좁힌다. 그 외 `component` 에서는 `cam_id` 와 `stream` 을 싣지 않으며 `state` 는 `ComponentState` 다. 두 열거형을 합집합으로 열어두지 않는다.

---

### 5.4 `zone_updated`

금지구역 폴리곤은 `overlay` 에 매 프레임 싣지 않는다(§5.1). 대시보드는
`GET /zones` 로 한 번 조회해 캐시하고, 설정 화면에서 구역이 변경되면
이 메시지를 받아 캐시를 갱신한다.

```json
{ "type":"zone_updated","cam_id":1,"action":"upsert",
  "zone": { "zone_id":"forklift_lane","name":"지게차 통행로",
            "polygon_m":[[3.0,6.0],[9.0,6.0],[9.0,11.0],[3.0,11.0]],
            "buffer_m":0.3,"active":true } }
```

| 필드 | 설명 |
|---|---|
| `action` | `upsert` / `delete` |
| `zone` | 구역 리소스. `GET /zones` 응답 원소와 동일한 형태 |

**`action` 별 필수 필드**

| `action` | `zone` 에 필요한 필드 |
|---|---|
| `upsert` | `zone_id`, `name`, `polygon_m`, `buffer_m`, `active` **전부 필수** |
| `delete` | `zone_id` 만 |

`upsert` 인데 `polygon_m` 이 없으면 대시보드 캐시가 손상되므로 **수신 측에서 거부**한다.

캘리브레이션(호모그래피)이 변경된 경우에도 지면 좌표계가 바뀌므로
해당 카메라의 모든 구역에 대해 `upsert` 를 순차 발행한다.

**오버레이 시간 정합 (중요)**

라이브 영상(1080p 메인 스트림 → 서버 재스트리밍)과 오버레이 좌표(640p 서브 스트림 → 엣지 → 서버 → WebSocket)는 **경로가 달라 지연도 다르다.** 도착 즉시 그리면 박스가 사람보다 앞서 움직인다. NTP 동기화는 "같은 시계를 본다"는 보장일 뿐 도착 시점을 맞춰주지 않는다.

따라서 클라이언트는 `overlay`를 즉시 렌더링하지 않고 다음과 같이 처리한다.

1. 수신한 `overlay`를 `ts` 키로 지연 버퍼에 적재
2. 현재 재생 중인 영상 프레임의 표시 시각 `t_video`를 구한다
3. 버퍼에서 `ts ≈ t_video`인 항목을 꺼내 렌더링. 정확히 일치하는 프레임이 없으면 앞뒤 두 프레임을 선형 보간
4. `overlay_buffer_ms`(기본 300ms)만큼 영상 재생을 지연시켜 좌표가 항상 먼저 도착하도록 여유를 둔다
5. `overlay_stale_ms`(기본 1000ms) 이상 갱신이 없으면 박스를 흐리게 처리

정합 오차 목표는 **±100ms**이며, 시연 시 화면 품질에 직결되는 항목이다.

---

## 6. 부록 · 주요 필드 산출 방법

### 6.1 `foot_point` (접지점)

**마스크 기반 (정밀)**
1. 사람 마스크 픽셀 중 **y좌표 하위 8% 구간** 추출 → 발 근처 픽셀 띠
2. 그 띠의 **x 중앙값** → 두 발 사이 중심 (다리를 벌려도 안정적)
3. 정규화 좌표로 변환

**bbox 기반 (초기 구현)**: bbox 하단 중앙 `[(x1+x2)/2, y2]`. 단순하나 다리를 벌리거나 팔을 뻗으면 오차 발생.

**`foot_conf` 저하 요인**: 발 영역 가림, 그림자 혼입, 픽셀 수 부족(원거리). 임계 미만이면 뎁스 검증 트리거 C 발동.

### 6.2 `foot_point_m` (지면 실좌표)

접지점 픽셀에 카메라별 호모그래피 H를 적용한다.

```
[X', Y', W] = H · [u, v, 1]ᵀ
실좌표 = (X'/W, Y'/W)   ← 단위 m
```

H는 캘리브레이션 시 지면 4점의 (픽셀, 실측 미터) 쌍으로 1회 계산되어 저장된다. **카메라를 움직이면 재캘리브레이션이 필요하다.**

### 6.3 `helmet` (2단계 분류 결과)

1. 1단계에서 얻은 `person` bbox를 패딩 확장해 크롭
2. **크롭 높이가 `cls_min_crop_px` 미만이면 추론을 생략**한다
3. 224×224로 리사이즈해 분류 모델 입력. 여러 사람은 **배치로 묶어 1회 추론**
4. **게이팅**: 결과 신뢰도가 `cls_min_conf` 미만이면 그 결과를 채택하지 않는다
5. 채택된 결과를 `track_id`별로 캐싱하고 `cls_cache_ms` 동안 재사용. `helmet_checked_at`은 실제 채택 시각을 유지

**`unknown`을 두지 않는 이유**: 분류 모델의 클래스는 `on`/`off` 2종뿐이다. 제3의 클래스를 학습시키려면 "판정 불가"의 경계를 사람이 라벨로 정의해야 하는데 그 기준이 주관적이라 데이터 품질이 떨어진다. 대신 **모델은 항상 둘 중 하나로 답하고, 그 답을 채택할지는 엣지가 크기·신뢰도 규칙으로 결정**한다.

| 상황 | `frame` 메시지 처리 | 서버 처리 |
|---|---|---|
| 게이트 통과 | `helmet` 갱신, `helmet_checked_at` 갱신 | 정상 판정 |
| 미통과 · 캐시 있음 | 직전 `helmet` 유지, `helmet_checked_at`은 **갱신하지 않음** | 값이 오래됐음을 인지하고 타이머 **동결** |
| 미통과 · 캐시 없음 | `helmet` 필드 **생략** | `no_helmet` 후보 생성하지 않음 |

**타이머 동결 원칙**: 게이팅 보류 구간에서 확정 타이머(3초)와 해소 타이머(10초)는 **초기화하지 않고 멈춘다**. 작업자가 잠시 카메라에서 멀어졌다는 이유로 판정이 처음부터 다시 시작되면 조건이 영원히 충족되지 않는다.

**캐싱 근거**: 안전모 착용 상태는 초 단위로 변하지 않으므로 매 프레임 분류는 불필요하다. 8fps 기준 캐시 1초면 분류 호출이 약 1/8로 감소한다.

### 6.4 `posture` (자세 · 쓰러짐 판정)

세 지표를 **모두** 충족해야 `fallen`으로 판정한다.

| 지표 | 산출 |
|---|---|
| `height_ratio` | 마스크 화면 높이 ÷ `foot_point_m` 거리에서의 기대 높이. 캘리브레이션 시 `reference_person`을 입력했으면 그 값으로, 없으면 카메라 기하로 기대 높이를 추정 |
| `axis_angle_deg` | 마스크 픽셀 좌표에 PCA를 적용해 주축을 구하고, 화면 수직축과의 각도를 계산 |
| `stillness_s` | 마스크 중심 이동량과 마스크 형태 변화량이 모두 임계 이하인 상태의 지속 시간 |

**뎁스 보강**: 세 조건 충족 시 뎁스를 1회 실행해 마스크 영역의 **깊이 분산**을 확인한다. 서 있는 사람은 카메라로부터 거의 같은 거리에 있어 분산이 작고, 지면에 누운 사람은 깊이가 지면을 따라 퍼져 분산이 크다.

**호모그래피 오용 주의**: 사람 마스크 전체를 지면으로 투영해 크기를 재는 방식은 사용하지 않는다. 지면 평면 가정 때문에 **서 있는 사람의 상반신이 지면상 먼 지점으로 투영되어** 누운 사람보다 오히려 길게 나오는 역전 현상이 발생한다. 호모그래피는 접지점 거리 산출에만 사용한다.

**오탐 억제**: 쭈그려 앉기·허리 굽혀 작업은 `height_ratio`와 `axis_angle_deg`를 통과할 수 있으나, 상체·팔 움직임이 지속되므로 `stillness_s` 조건에서 걸러진다.

### 6.5 `nearby[].dist_m`

| 방식 | 계산 |
|---|---|
| `bbox_center` | 사람 접지점과 지게차 앵커점의 실좌표 간 유클리드 거리 |
| `mask_nearest` | 두 마스크 윤곽점을 각각 실좌표로 변환한 뒤 최소 거리 산출. **포크가 전방으로 뻗은 지게차**처럼 비정형 형상에서 정확 |

### 6.6 `depth_verified`

뎁스 1프레임을 실행해 사람 영역과 지게차 영역의 **상대 깊이 분포를 비교**한 결과다.
- 두 영역 깊이가 유사 → 실제 근접 → `true`
- 깊이가 뚜렷이 분리 → 원근 착시 → `false`(근접 위반 기각)
- 트리거 미충족으로 미실행한 경우도 `false`

**캐시 키**: `(cam_id, 사람 track_id, 지게차 track_id)`. 이 조합을 만들기 위해 **지게차에도 track_id를 부여**한다. 어느 한쪽이 지면 좌표로 임계 이상 이동하면 캐시를 즉시 무효화한다.

**주의**: 단안 뎁스는 절대 거리가 부정확하므로 **거리 수치는 호모그래피 값을 사용**하고, 뎁스는 앞뒤 분리와 깊이 분산 판별에만 사용한다.

### 6.7 `correction_rate` (방송 후 시정률)

```
correction_rate    = resolved / (resolved + unresolved)
undetermined_rate  = expired  / (resolved + unresolved + expired)
```

| 이벤트 종결 상태 | 시정률 분자 | 시정률 분모 | 비고 |
|---|---|---|---|
| `resolved` (`resolve_window_s` 내) | ○ | ○ | 시정 성공 |
| `resolved` (창 초과) | ✕ | ○ | 늦은 시정 |
| `alerted` / `re_alerted` 미해소 | ✕ | ○ | 미시정 |
| **`expired`** (재결합 실패) | ✕ | **✕** | **판정 불가** — 별도 집계 |
| `is_false_positive = true` | ✕ | ✕ | 전량 제외 |
| `fall` | ✕ | ✕ | 자력 시정 불가 유형, 별도 카운트 |

**`expired`를 분모에서도 빼는 이유**: 추적이 끊긴 이벤트는 **시정하지 않은 것이 아니라 시정 여부를 관측하지 못한 것**이다. 미시정으로 계산하면 시스템 성능이 부당하게 낮아지고, 시정으로 계산하면 지표가 부풀려져 근거를 댈 수 없다. 모집단에서 제외하되 그 비율을 함께 공개하는 것이 통계적으로 정확하며, 외부 검증이 가능한 형태가 된다.

**표기 규칙**: 지표를 단독으로 제시하지 않는다. 항상 `방송 후 시정률 87% (판정 불가 5%)` 형태로 병기한다.

**부가 의미**: `undetermined_rate`는 추적 품질의 대리 지표이므로 카메라 화각·설치 위치의 적절성을 진단하는 값으로도 사용한다.

### 6.8 `anomaly_score`

현재 프레임 임베딩과 해당 시간대 정상 풀의 **k-최근접 평균 코사인 거리**를 0~1로 정규화한 값. 임계 초과 시 이상 플래그가 생성되며 **경고 방송은 발동하지 않는다**. 샘플링 주기는 `anomaly_sample_interval_min`(기본 5분)이며, 서버가 자체 1080p 스트림에서 캡처하므로 엣지 추론 예산과 무관하다.

---

*팀 AIM · 2026-07-18*