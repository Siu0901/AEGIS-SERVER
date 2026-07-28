# AEGIS 진척표 · FN-ID 내비게이션

`docs/AEGIS_기능명세서.md` §4의 모든 기능(57개)을 코드 위치·마일스톤과 함께 묶은 표다.
**작업을 마칠 때마다 해당 행의 상태를 갱신한다.**

| 표기 | 뜻 |
|---|---|
| ⬜ | 미착수 |
| 🟡 | 진행 중 |
| ✅ | 완료 (`uv run tasks.py verify` 통과 + 테스트 존재) |
| 보류 | P2 — 여유 시 구현. 일정 부족 시 조정 |

---

## 마일스톤 로드맵

| M | 이름 | 내용 |
|---|---|---|
| **M0** | 뼈대와 계약 | contracts · Clock · DB 스키마 · 리포지토리 프로토콜 · 시뮬레이터 뼈대 · deploy · 툴체인 |
| **M1** | 인프라와 통로 | 스트리밍·녹화 · DB 리포지토리 구현 · `/ws/edge`·`/ws/dashboard` · 시스템 상태 |
| **M2** | 이벤트 상태머신 | 후보 병합 · 확정 · 해소 · 쿨다운 · 소실 유예 · sim 시나리오 |
| **M3** | 경고와 기록 | 음성 방송 · 경광등(MQTT) · 클립/키프레임 예약 추출 · 저장 관리 |
| **M4** | 재결합과 지표 | 재결합 · 반복 위반 · 시정률/판정 불가율 · 수동 정정 |
| **M5** | 관제 화면 P0 | 개요 · 실시간 관제(오버레이 정합) · 이벤트 · `uv run tasks.py types` |
| **M6** | 설정과 비전 로직 | 캘리브레이션 · 구역 편집 · 음원 매핑 · 정책 · `packages/vision` 순수 계산 |
| **M7** | 지능 기능 | 임베딩 · 장면 검색 · LLM 분석 · 규정 매핑 · 챗봇 · 브리핑 |
| **M8** | 분석·보고서 | 분석 화면 · 이상 탐지 · 유사 사례 · 주간 보고서 (P2 다수) |
| **M9** | 엣지 실물 이식 | 시뮬레이터를 실물 Jetson 러너로 교체 |

**엣지 기능(FN-DET)의 읽는 법**: 이 레포의 범위는 서버·프론트이고 엣지는 시뮬레이터로
대체한다. 따라서 FN-DET는 두 갈래로 진행된다 — 순수 계산 로직은 `packages/vision` 에서
**M6**에 구현되고, 실물 추론·디코딩은 **M9**에 `edge/` 로 이식된다. 그 사이 서버가 보는
입력은 `sim/edge_sim` 이 만든다(**M2**).

---

## 4.1 감지 (FN-DET) · 12건

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-DET-01 | 영상 수신 및 하드웨어 디코딩 (NVDEC · 서브 640×360 15fps) | P0 | EDGE | 기능 §4.1 · API §1.2 | M9 (sim: M2) | `edge/capture.py` · `edge/config.yaml` · `sim/edge_sim/` | ⬜ |
| FN-DET-02 | 1단계 객체 감지 (person·vehicle 단일 모델 · 640×384 rect) | P0 | EDGE | 기능 §4.1 · §5 | M9 | `edge/detect.py` · `edge/config.yaml` | ⬜ |
| FN-DET-03 | 객체 추적 및 트랙 ID 부여 (ByteTrack) | P0 | EDGE | 기능 §4.1 | M9 | `edge/track.py` | ⬜ |
| FN-DET-04 | 2단계 안전모 분류 (크롭 기반 · 게이팅) | P0 | EDGE | 기능 §4.1 | M9 | `edge/classify.py` | ⬜ |
| FN-DET-05 | 분류 결과 캐싱 (`cls_cache_ms`) | P0 | EDGE | 기능 §4.1 | M9 | `edge/classify.py` | ⬜ |
| FN-DET-06 | 접지점 산출 및 실좌표 변환 | P0 | EDGE | 기능 §4.1 · API §6.1·6.2 | M6 (로직) / M9 (엣지) | `packages/vision/foot_point.py` · `homography.py` | ⬜ |
| FN-DET-07 | 금지구역 침입 판정 (히스테리시스) | P0 | EDGE | 기능 §4.1 | M6 / M9 | `packages/vision/zones.py` | ⬜ |
| FN-DET-08 | 지게차 근접 판정 | P1 | EDGE | 기능 §4.1 | M6 / M9 | `packages/vision/distance.py` | ⬜ |
| FN-DET-09 | 마스크 기반 최근접 거리 | P1 | EDGE | 기능 §4.1 · API §6.5 | M6 / M9 | `packages/vision/distance.py` | ⬜ |
| FN-DET-10 | 쓰러짐 판정 (3조건 동시 충족) | P1 | EDGE | 기능 §4.1 · API §6.4 | M6 / M9 | `packages/vision/posture.py` | ⬜ |
| FN-DET-11 | 뎁스 온디맨드 검증 | P1 | EDGE | 기능 §4.1 · API §6.6 | M9 | `edge/depth.py` | ⬜ |
| FN-DET-12 | 이벤트 후보 생성 및 전송 | P0 | EDGE | 기능 §4.1 · API §2.2 | M2 (sim) / M9 | `sim/edge_sim/` · `edge/rules.py` | ⬜ |

> **주의** — 안전모에는 별도 bbox가 없다. 1단계는 `person`/`vehicle` 2클래스뿐이고
> 안전모는 사람 크롭을 2단계 분류가 판정한다. `helmet` 값은 `on`/`off` 둘뿐이며
> 판정 불가는 **필드 생략**으로 표현한다(`unknown` 클래스 없음).

---

## 4.2 이벤트 처리 (FN-EVT) · 7건

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-EVT-01 | 후보 수신 및 중복 병합 | P0 | SRV | 기능 §4.2 | M2 | `server/app/ws_edge.py` · `server/domain/event_machine.py` | ⬜ |
| FN-EVT-02 | 이벤트 확정 판정 (`confirm_duration_s`) | P0 | SRV | 기능 §4.2 | M2 | `server/domain/event_machine.py` | ⬜ |
| FN-EVT-03 | 해소(시정) 판정 (`resolve_duration_s`) | P0 | SRV | 기능 §4.2 | M2 | `server/domain/event_machine.py` | ⬜ |
| FN-EVT-04 | 쿨다운 및 재경고 (`cooldown_s`) | P0 | SRV | 기능 §4.2 | M2 | `server/domain/event_machine.py` | ⬜ |
| FN-EVT-05 | 이벤트 수동 정정 (오탐·강제 종결) | P1 | SRV/WEB | 기능 §4.2 · API §4.1 | M4 | `server/app/routes/events.py` · `front/src/pages/EventsPage.tsx` | ⬜ |
| FN-EVT-06 | 반복 위반 집계 (최근 7일) | P1 | SRV | 기능 §4.2 | M4 | `server/domain/metrics.py` | ⬜ |
| FN-EVT-07 | 트랙 소실 유예 및 재결합 | P0(유예) / P1(재결합) | SRV | 기능 §4.2 · API §2.3 | M2 (유예) / M4 (재결합) | `server/domain/reassociation.py` | ⬜ |

> **FN-EVT-07 ④ 보조 시그니처(색상 히스토그램)는 P2 — 보류.**
> 단, 안전모 착용 여부는 게이트 조건으로 쓰지 않는다(판정 대상이므로 순환 논리).
>
> **재결합은 이벤트를 살리는 처리이지 시정을 인정하는 처리가 아니다.**
> 재결합 후 위반이 사라져 보여도 해소 타이머를 0부터 다시 채운다.

---

## 4.3 경고 (FN-ALM) · 5건

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-ALM-01 | 경고 발동 (사전 녹음 음성 방송) | P0 | SRV | 기능 §4.3 | M3 | `server/infra/audio/` · `assets/` | ⬜ |
| FN-ALM-02 | 경광등 · 부저 제어 (MQTT) | P0 | SRV/MCU | 기능 §4.3 · API §3 | M3 | `server/infra/mqtt/` · `sim/mcu_sim/` | ⬜ |
| FN-ALM-03 | 긴급 알림 (쓰러짐 · 관리자 확인) | P1 | SRV/WEB | 기능 §4.3 | M3 | `server/app/ws_dashboard.py` · `front/src/pages/LivePage.tsx` | ⬜ |
| FN-ALM-04 | 수동 방송 송출 | P1 | WEB/SRV | 기능 §4.3 · API §4.5 | M3 | `server/app/routes/alerts.py` | ⬜ |
| FN-ALM-05 | 경고 일시중지 (정비 작업 등) | P1 | WEB/SRV | 기능 §4.3 · API §4.5 | M3 | `server/app/routes/alerts.py` | ⬜ |

> **경고 방송은 TTS가 아니다.** 위반 유형별 사전 녹음 wav를 재생한다(생성 지연 제거).
> 확정 → 방송 시작 **1초 이내**가 요구사항이다.
> **이상 탐지(FN-AI-04)는 경고 방송을 발동하지 않는다.**

---

## 4.4 기록 · 영상 (FN-REC) · 5건

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-REC-01 | 라이브 재스트리밍 (1080p 메인) | P0 | SRV | 기능 §4.4 | M1 | `server/infra/stream/` · `deploy/mediamtx.yml` · `front/src/live/` | ✅ |
| FN-REC-02 | 7일 링버퍼 녹화 | P0 | REC | 기능 §4.4 · API §4.7 | M1 | `recorder/capture.py` · `recorder/retention.py` | ✅ |
| FN-REC-03 | 이벤트 클립 · 키프레임 추출 | P0 | REC/SRV | 기능 §4.4 · API §4.7 | M1 (REC API) / M3 (예약 실행) | `recorder/clips.py` · `server/infra/clip/` | 🟡 |
| FN-REC-04 | 이벤트 DB 저장 | P0 | SRV | 기능 §4.4 · §6 | M1 | `server/infra/db/repository.py` | ⬜ |
| FN-REC-05 | 저장 용량 관리 | P1 | REC | 기능 §4.4 | M1 | `recorder/retention.py` | ✅ |

> **녹화는 서버가 아니라 REC 컴포넌트(`recorder/`)가 한다** (기능명세서 §4.4 「녹화 컴포넌트(REC) 분리」).
> 운용 시 7일 원본은 엣지 NVMe SSD 에 있고, 서버는 파일 경로가 아니라 **HTTP API(§4.7)로만**
> 접근한다. 개발 중 같은 기계에서 돌더라도 이 규칙을 지킨다 — M9 에 옮길 때 고치는 값이
> `RECORDER_BASE` 하나여야 하기 때문이다.
>
> **FN-REC-03 이 🟡 인 이유**: `POST /clips` · `GET /keyframe`(추출 API)는 M1 에서 동작하지만,
> `confirmed_at + clip_post_roll_s + margin` 예약 실행과 `clip_status` 관리는 이벤트
> 상태머신이 있어야 하므로 M3 이다.

> **클립은 확정 즉시 추출하지 않는다.** 확정 순간에는 사후 구간이 아직 녹화되지 않았다.
> `confirmed_at + clip_post_roll_s + margin(2초)` 시점에 예약 실행하고, 그동안
> `clip_status = pending` 으로 노출한다. 키프레임만 즉시 추출한다.
> 서버 재시작 시 `pending` 잡은 DB에서 복구해 재실행한다.

---

## 4.5 지능 기능 (FN-AI) · 10건

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-AI-01 | 이벤트 키프레임 임베딩 (halfvec 3072) | P1 | SRV/CLD | 기능 §4.5 | M7 | `server/ai/embedding.py` | ⬜ |
| FN-AI-02 | 자연어 장면 검색 (하이브리드) | P1 | SRV/CLD | 기능 §4.5 · API §4.3 | M7 | `server/ai/search.py` · `server/app/routes/search.py` | ⬜ |
| FN-AI-03 | 반복 위반 시각적 클러스터링 | P2 | SRV | 기능 §4.5 | M8 | `server/ai/cluster.py` | 보류 |
| FN-AI-04 | 정상 풀 축적 및 이상 탐지 | P2 | SRV/CLD | 기능 §4.5 · API §6.8 | M8 | `server/ai/anomaly.py` | 보류 |
| FN-AI-05 | LLM 심층 분석 생성 (LangGraph) | P1 | SRV/CLD | 기능 §4.5 | M7 | `server/ai/graph.py` | ⬜ |
| FN-AI-06 | 규정 매핑 (사전 구축 테이블) | P1 | SRV | 기능 §4.5 | M7 | `server/ai/regulations.py` · `assets/` | ⬜ |
| FN-AI-07 | 유사 사고사례 매칭 | P2 | SRV/CLD | 기능 §4.5 | M8 | `server/ai/incidents.py` · `assets/` | 보류 |
| FN-AI-08 | 챗봇 질의 라우팅 (sql·vector·vision) | P1 | SRV/CLD | 기능 §4.5 · API §4.4 | M7 | `server/ai/graph.py` | ⬜ |
| FN-AI-09 | 실시간 현장 브리핑 | P1 | SRV/CLD | 기능 §4.5 · API §4.4 | M7 | `server/ai/briefing.py` | ⬜ |
| FN-AI-10 | 주간 보고서 생성 | P2 | SRV/CLD | 기능 §4.5 · API §4.4 | M8 | `server/ai/report.py` | 보류 |

> **클라우드가 죽어도 안전 기능은 무영향이어야 한다**(FN-SYS-03).
> 규정 조항은 **LLM이 생성하지 않는다** — 사전 매핑 테이블로 결정적으로 연결한다.

---

## 4.6 관제 화면 (FN-UI) · 7건

| FN-ID | 화면 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-UI-01 | 개요 — 핵심 지표 · 추세 · 분포 · 최근 이벤트 · 시스템 상태 | P0 | WEB | 기능 §4.6 | M5 | `front/src/pages/OverviewPage.tsx` | ⬜ |
| FN-UI-02 | 실시간 관제 — 2채널 라이브 + 오버레이 · 수동 방송 | P0 | WEB | 기능 §4.6 · API §5 | M1 (라이브·상태) / M2 (오버레이) / M3 (수동 방송) | `front/src/pages/LivePage.tsx` · `front/src/live/` | 🟡 |
| FN-UI-03 | 이벤트 — 목록·필터 + 상세(클립·LLM·규정·타임라인) | P0 | WEB | 기능 §4.6 · API §4.1 | M5 | `front/src/pages/EventsPage.tsx` | ⬜ |
| FN-UI-04 | 영상 검색 — 자연어 질의 · 유사도순 결과 | P1 | WEB | 기능 §4.6 · API §4.3 | M7 | `front/src/pages/SearchPage.tsx` | ⬜ |
| FN-UI-05 | 분석 · 보고서 — 시정률 추이 · 반복 순위 · 히트맵 · 이상 탐지 | P1 | WEB | 기능 §4.6 · API §4.2 | M8 | `front/src/pages/AnalysisPage.tsx` | ⬜ |
| FN-UI-06 | 챗봇 — 통계·검색·브리핑 질의 | P1 | WEB | 기능 §4.6 · API §4.4 | M7 | `front/src/pages/AssistantPage.tsx` | ⬜ |
| FN-UI-07 | 설정 — 구역 그리기 · 캘리브레이션 · 음원 · 임계값 · 시스템 | P1 | WEB | 기능 §4.6 · API §4.5 | M6 | `front/src/pages/SettingsPage.tsx` | ⬜ |

> **오버레이는 도착 즉시 그리지 않는다.** `ts` 기준 지연 버퍼(`overlay_buffer_ms`, 기본 300ms)에
> 담았다가 재생 중인 프레임 시각에 맞춰 그린다. 정합 오차 목표 **±100ms**.
> `overlay_stale_ms`(기본 1000ms) 초과 시 박스를 흐리게 표시한다.
>
> **설정 화면에 「위험요소 등록 · 자연어」 패널은 없다** (부록 A-1 미채택).
> 시안의 건설현장 용어(굴착기·굴착 구역)는 전부 제조현장 용어로 바꾼다 (부록 B).

---

## 4.7 설정 (FN-CFG) · 5건

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-CFG-01 | 카메라 캘리브레이션 (지면 4점 → 호모그래피) | P0 | SRV/WEB | 기능 §4.7 · API §4.5 | M6 | `packages/vision/homography.py` · `server/app/routes/cameras.py` | ⬜ |
| FN-CFG-02 | 금지구역 편집 (폴리곤 → 지면 좌표) | P0 | SRV/WEB | 기능 §4.7 · API §4.5 | M6 | `server/app/routes/zones.py` · `front/src/pages/SettingsPage.tsx` | ⬜ |
| FN-CFG-03 | 경고 음원 매핑 | P0 | SRV/WEB | 기능 §4.7 | M6 | `server/app/routes/alerts.py` · `assets/` | ⬜ |
| FN-CFG-04 | 임계값 정책 관리 | P1 | SRV/WEB | 기능 §4.7 · API §4.5 | M6 | `server/app/routes/policies.py` | ⬜ |
| FN-CFG-05 | 위험 반경 설정 (클래스별) | P1 | SRV/WEB | 기능 §4.7 · API §4.5 | M6 | `server/app/routes/vehicle_classes.py` | ⬜ |

---

## 4.8 시스템 (FN-SYS) · 6건

명세서 §4.8 표는 `01 · 02 · 03 · 05 · 06 · 04` 순서로 적혀 있다. 여기서는 ID 순으로 정렬했다.

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-SYS-01 | 구성요소 상태 감시 (엣지·카메라·MCU·클라우드·저장소) | P0 | SRV | 기능 §4.8 · API §4.6 | M1 (카메라·저장소) / M2~ (엣지·MCU·클라우드) | `server/app/routes/system.py` · `server/infra/stream/watcher.py` | 🟡 |
| FN-SYS-02 | 시각 동기화 (NTP · 클립 정합의 전제) | P0 | SRV/EDGE | 기능 §4.8 | M1 (서버) / M2 (엣지 오프셋) | `server/infra/timesync.py` · `edge/` | 🟡 |
| FN-SYS-03 | 클라우드 장애 격리 | P1 | SRV | 기능 §4.8 | M7 | `server/ai/adapter.py` | ⬜ |
| FN-SYS-04 | 지표 집계 (시정률 · 평균 시정 시간 · 판정 불가율 · 분포) | P0 | SRV | 기능 §4.8 · API §4.2·§6.7 | M4 | `server/domain/metrics.py` | ⬜ |
| FN-SYS-05 | 판정 불가 집계 (`expired` 별도 집계) | P0 | SRV | 기능 §4.8 · API §6.7 | M4 | `server/domain/metrics.py` | ⬜ |
| FN-SYS-06 | 엣지 메시지 거부 집계 (로깅 · 카운터 · 노출) | P0 | SRV | 기능 §4.8 · API §2.2 | M1 | `server/app/ws_edge.py` · `server/app/routes/system.py` | ⬜ |

> **FN-SYS-06 — 후보를 조용히 버리지 않는다.** 스키마 검증에 실패한 엣지 메시지를
> 로그 없이 폐기하면 안 된다. 감지된 위반이 검증 단계에서 소리 없이 사라지는 것은
> 오탐보다 위험하다. 원본 페이로드와 검증 오류를 `WARNING` 이상으로 남기고,
> `edge_msg_rejected_total{type, reason}` 을 올리고, `GET /system/status` 와 대시보드
> 시스템 상태에 건수를 노출한다. 엣지 구현이 바뀌어 필드가 누락되기 시작하면
> 이 값이 오르는 것으로 즉시 드러나야 한다.

> `expired` 는 **시정률 분모·분자 모두에서 제외**하고 `undetermined_rate` 로 따로 집계한다.
> 두 숫자는 **항상 병기**한다 — `방송 후 시정률 87% (판정 불가 5%)`.
> `fall` 과 `is_false_positive` 도 시정률에서 전량 제외한다.

---

## M0 산출물 (계약·뼈대)

FN-ID가 붙지 않는 기반 작업이다. 전부 완료되었고 `uv run tasks.py verify` 가 통과한다.

| 항목 | 위치 | 근거 | 상태 |
|---|---|---|---|
| 계약 스키마 (§2~§5.4 전량) | `packages/contracts/src/aegis_contracts/` | API명세서 전 절 | ✅ |
| 명세서 예시 JSON 회귀 테스트 | `packages/contracts/tests/test_spec_examples.py` | API §2·§3·§4.5·§5 | ✅ |
| `Clock` 프로토콜 · FakeClock | `packages/vision/src/aegis_vision/clock.py` | CLAUDE.md 절대규칙 1 | ✅ |
| DB 스키마 (7테이블) · 마이그레이션 `0001`·`0002` | `server/infra/db/` | 기능명세서 §6 | ✅ |
| 정책값 시드 | `scripts/seed_policies.py` | API §4.5 | ✅ |
| 리포지토리 프로토콜 | `server/domain/repository.py` | — | ✅ |
| 개발 스택 (postgres·redis·mosquitto·mediamtx) | `docker-compose.yml` · `deploy/` | — | ✅ |
| 카메라 규격 · 화면비 검증 | `deploy/mediamtx.yml` · `deploy/fake_cams.py` | API §1.2 · 기능 FN-DET-01 | ✅ |
| 엣지 설정 (모델 경로 · `imgsz [384,640]`) | `edge/config.yaml` | 기능 §5 · 절대규칙 6 | ✅ |
| 가짜 엣지 · 가짜 MCU | `sim/` | API §2·§3 | ✅ |
| 검증 파이프라인 | `tasks.py` · `.claude/settings.json` (Stop 훅) | — | ✅ |
| 프론트 라우팅·레이아웃 뼈대 | `front/` | 기능 §4.6 · 부록 B | ✅ |

---

## M1 산출물 (인프라와 통로)

| 항목 | 위치 | 근거 | 상태 |
|---|---|---|---|
| 환경변수 단일 원본 (compose·서버·REC·프론트가 같은 `.env`) | `.env.example` · `docker-compose.yml` · `front/vite.config.ts` | 절대규칙 6 | ✅ |
| mediamtx — RTSP 수신 · WHEP · LL-HLS (**내장 녹화 미사용**) | `deploy/mediamtx.yml` | 기능 §4.4 | ✅ |
| 가짜 카메라 4경로 + **밀리초 벽시계 타임코드 소성** | `deploy/fake_cams.py` | API §1.2 · FN-UI-02 | ✅ |
| REC 컴포넌트 — 세그먼트 녹화 · 보존 · §4.7 API 3종 | `recorder/` | API §4.7 | ✅ |
| §4.7 계약 스키마 (`ClipRequest` · `ClipResponse` · `RecStatusResponse`) | `packages/contracts/.../rest.py` | API §4.7 | ✅ |
| 메인 스트림 상태 감시 · `system` 발행 | `server/infra/stream/` | API §5.3 · FN-SYS-01 | ✅ |
| `GET /system/status` (storage 는 REC 프록시) | `server/app/routes/system.py` | API §4.6 | ✅ |
| `/ws/dashboard` 허브 (M1 은 `system` 만 흐른다) | `server/app/ws_dashboard.py` | API §5 | ✅ |
| NTP 오프셋 확인 (FN-SYS-02) | `server/infra/timesync.py` | 기능 §4.8 | ✅ |
| 실시간 관제 화면 — WHEP 우선 · HLS 폴백 · 표시 시각 | `front/src/live/` · `front/src/pages/LivePage.tsx` | FN-UI-02 | ✅ |

**실측치** (2026-07-28, testsrc2 소스 기준)

| 항목 | 값 |
|---|---|
| 영상 지연 · WebRTC(WHEP) | **0.27 ~ 0.34초** (정상 재생 진입 후) |
| 영상 지연 · LL-HLS | **약 2.5초** |
| 카메라 → mediamtx → 소비자 (지연의 대부분) | **약 0.27초** |
| 녹화 용량 (2채널) | **1.95 GB/시간** (§4.4 산정 2.25 GB/시간 대비 −13%) |
| 카메라 끊김 감지 | **2.9초** 만에 `reconnecting`, 7.6초에 `down` |

> **오버레이 정합(±100ms) 관점**: WebRTC 경로는 0.3초 안쪽이라 `overlay_buffer_ms`
> 기본값 300ms 와 같은 자리수다. **HLS 폴백은 2.5초**라 같은 버퍼값으로는 맞출 수
> 없다. M2 에서 재생 경로에 따라 버퍼를 달리 잡아야 한다 — 화면에 어느 경로로
> 재생 중인지 표시해 둔 이유가 이것이다.

---

## 명세서 확인 필요

명세서를 SSOT로 두고 **코드에서 임의로 채우지 않은** 항목이다. 사람이 판단해
명세서를 갱신하면 그때 코드에 반영한다(CLAUDE.md 절대규칙 8).

### 해소됨

**v2** — §2 필수·선택 규약 명문화, §5 대시보드 스키마 정의, §6 컬럼 추가,
`keyframe_paths` 배열화, 카메라 규격 확정, `fall_*` 임계값 float화.

**v3** — §2.4 필드 표 재작성, §4.6 `edge.fps` 제거, `edge.msg_rejected_total` 신설,
§5.1 `bbox` 코너 형식 확정, §5.4 `zone_updated` 신설, `violation_type` 통일,
`event_updated` 전이별 동반 필드, `severity` = `AlertCommand.level`, §5.3 `metric`
필드 추가, `component`·`state` 값 목록, §6 `keyframe_paths` jsonb 표기.

**v4 (직전에 보고한 A 5건 · C 4건 전량)** — §5 구조 규약에 "REST 리소스 단일 객체"
중첩 허용 명시, §5.3 `system.cam_id` 와 camera 예시, §5.4 `action` 별 필수 필드 표,
카메라 상태 모델 재정비(`sub_state` / `main_state` + `StreamState`·`ComponentState`
분리 근거), §4.1 `confirmed_at`, §4.2 응답 스키마 3종, §4.4 `attachments[]` 4종,
부록 A-1·B 시안 파일명. — 전부 코드에 반영했다.

**v5** — §5.3 `system` 이 `component` 로 판별되도록 정리됐다. `stream` 필드가 신설되고
`component == "camera"` 면 `cam_id`·`stream` 필수 + `StreamState`, 그 외에는 둘 다 금지
+ `ComponentState` 로 확정됐다. 직전에 보고한 값 집합 모순이 해소됐다.

### A. 남아 있는 확인 필요

| 내용 | 상세 |
|---|---|
| **§4.6 관측 전 값의 표기** | `cameras[].fps` · `time_sync.edge_offset_ms` · `storage` 는 예시가 전부 "값이 있는 상태"뿐이라, 아직 관측 주체가 없을 때(M1) 무엇을 실을지 정하지 않았다. `0` 은 "엣지가 도는데 처리량 0" · "완벽히 동기화됨" 이라는 **다른 주장**이 되어 실제 장애와 구분되지 않으므로 **`null` 로 두고 계약을 nullable 로 넓혔다.** 명세서가 다른 표기를 원하면 되돌려야 한다 |
| **§4.6 `storage` 와 §4.7 `storage` 의 관계** | §4.7 은 "이 응답을 §4.6 의 `storage` 에 **그대로 전달**한다"고 하는데, §4.7 은 5필드(`total_gb`·`used_gb`·`free_gb`·`retention_days`·`oldest_segment_at`)이고 §4.6 예시는 2필드(`retention_days`·`free_gb`)다. **§4.6 스키마를 유지하고 값의 출처만 REC 으로** 했다(서버 디스크를 조회하지 않는다는 것이 §4.7 의 핵심 요구이므로). §4.6 을 5필드로 넓히려는 의도였다면 알려달라 |
| **§4.6 에 카메라별 녹화 여부가 없다** | §4.7 `GET /status` 에는 `cameras[].recording` 이 있지만 §4.6 에는 없다. 화면의 REC 표시는 REC 도달 여부(`storage` 가 채워졌는가) + `main_state` 로 **추론**하고 있다. 카메라별 녹화 상태를 화면에 정확히 띄우려면 §4.6 에 필드가 필요하다 |
| **§4.7 비-`ready` 응답의 필드** | `POST /clips` 예시가 `ready` 인 경우만 있다. `not_found` 면 파일이 없으므로 `size_bytes`·`download_url`·`actual_from`·`actual_to` 를 **전부 `null`** 로 두었다 |
| §5.4 `zone` 의 "동일한 형태" | "`GET /zones` 응답 원소와 동일한 형태"라고 하지만 예시와 필수 필드 표에는 `cam_id` 가 없다(메시지 최상위에 있음). 표를 따라 `cam_id` 없이 두었다 |
| §4.2 `points[].t` 의 타입 | `bucket` 에 따라 표기가 달라진다(`day` → `2026-08-12`, `hour` → ?). 예시가 날짜뿐이라 `str` 로 두었다 |
| §4.2 `distribution` 의 `key` | `by=hour_of_day` 는 "0~23을 `key` 로 사용"한다는데 int 인지 문자열인지 불명확하다. 다른 축이 전부 문자열이라 `str` 로 통일했다 |

### B. 판단이 필요했던 타입

| 필드 | 판단 |
|---|---|
| `anomaly_sample_interval_min` | "분 단위 주기"라 개수로 볼 수도 있으나 **지속시간 계열로 보아 `float`** 로 했다. 정수만 허용해야 한다면 되돌려야 한다 |
| `cls_min_crop_px` | Policies 에서 **유일하게 `int` 로 남긴 값**이다(픽셀 수는 셀 수 있는 값). 서브 640×360 기준 64px = 프레임 높이의 17.8% 로, FN-DET-04 카메라 설치 지침의 "약 18%"와 일치한다 |
| `AlertCommand.level` | §5.2가 "`severity` 와 동일한 척도이며 같은 값"이라 명시하므로 **`Literal[1,2,3]` 을 공유**하도록 좁혔다. §3 표의 타입 칸은 여전히 `int` 지만 산문이 1·2·3만 열거한다 |
| `overlay.objects[].violations` · `event_ids` · `nearby` | "없으면 빈 배열"이므로 **필드는 항상 실리는 것**으로 보고 기본값을 주지 않았다 |
| `event_created.zone_id` · `alerted_at` | §5.2 예시에는 값이 있으나 §4.1이 둘 다 nullable 이므로 **필수 + null 허용**으로 두었다 |
| `anomaly.note` · `keyframe_url` | 클라우드 미가용 시 설명이 없을 수 있어(FN-SYS-03) **필수 + null 허용**으로 두었다 |
| `table` 첨부의 `rows[][]` | 셀 타입이 명시되지 않았다(예시에 문자열·정수 혼재). `list[list[Any]]` 로 두었다 |
