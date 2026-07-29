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
| **M2** | 엣지 인터페이스와 이벤트 생성 | `/ws/edge` · 후보 병합(FN-EVT-01) · `overlay` · 오버레이 정합 · sim 시나리오 |
| **M3** | 상태머신과 지표 | 확정 · 해소 · 쿨다운 · 소실 유예 · **재결합** · 수동 정정 · 반복 위반 · **시정률/판정 불가율** |
| **M4** | 경고와 클립 | 음성 방송 · 경광등(MQTT) · 긴급 알림 · 수동 방송 · 클립 예약 추출 |
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
| FN-DET-12 | 이벤트 후보 생성 및 전송 | P0 | EDGE | 기능 §4.1 · API §2.2 | M2 (sim) / M9 | `sim/edge_sim/` · `sim/cases/` · `edge/rules.py` | ✅ (sim) |

> **주의** — 안전모에는 별도 bbox가 없다. 1단계는 `person`/`vehicle` 2클래스뿐이고
> 안전모는 사람 크롭을 2단계 분류가 판정한다. `helmet` 값은 `on`/`off` 둘뿐이며
> 판정 불가는 **필드 생략**으로 표현한다(`unknown` 클래스 없음).

---

## 4.2 이벤트 처리 (FN-EVT) · 7건

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-EVT-01 | 후보 수신 및 중복 병합 | P0 | SRV | 기능 §4.2 | M2 | `server/app/ws_edge.py` · `server/domain/event_machine.py` | ✅ |
| FN-EVT-02 | 이벤트 확정 판정 (`confirm_duration_s`) | P0 | SRV | 기능 §4.2 | M3 | `server/domain/event_machine.py` | ✅ |
| FN-EVT-03 | 해소(시정) 판정 (`resolve_duration_s`) | P0 | SRV | 기능 §4.2 | M3 | `server/domain/event_machine.py` | ✅ |
| FN-EVT-04 | 쿨다운 및 재경고 (`cooldown_s`) | P0 | SRV | 기능 §4.2 | M3 | `server/domain/event_machine.py` | ✅ |
| FN-EVT-05 | 이벤트 수동 정정 (오탐·강제 종결) | P1 | SRV/WEB | 기능 §4.2 · API §4.1 | M3 (API) / M5 (화면) | `server/app/routes/events.py` · `server/app/event_service.py` | 🟡 (화면만 남음) |
| FN-EVT-06 | 반복 위반 집계 (최근 7일) | P1 | SRV | 기능 §4.2 | M3 | `server/infra/db/repository.py` (`count_repeat_7d`) | ✅ |
| FN-EVT-07 | 트랙 소실 유예 및 재결합 | P0(유예) / P1(재결합) | SRV | 기능 §4.2 · API §2.3 | M3 | `server/domain/reassociation.py` · `event_machine.py` | ✅ |

> **FN-EVT-07 ④ 보조 시그니처(색상 히스토그램)는 P2 — 보류.**
> 단, 안전모 착용 여부는 게이트 조건으로 쓰지 않는다(판정 대상이므로 순환 논리).
>
> **재결합은 이벤트를 살리는 처리이지 시정을 인정하는 처리가 아니다.**
> 재결합 후 위반이 사라져 보여도 해소 타이머를 0부터 다시 채운다.

---

## 4.3 경고 (FN-ALM) · 5건

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-ALM-01 | 경고 발동 (사전 녹음 음성 방송) | P0 | SRV | 기능 §4.3 | M4 | `server/infra/audio/` · `assets/` | ⬜ |
| FN-ALM-02 | 경광등 · 부저 제어 (MQTT) | P0 | SRV/MCU | 기능 §4.3 · API §3 | M4 | `server/infra/mqtt/` · `sim/mcu_sim/` | ⬜ |
| FN-ALM-03 | 긴급 알림 (쓰러짐 · 관리자 확인) | P1 | SRV/WEB | 기능 §4.3 | M4 | `server/app/ws_dashboard.py` · `front/src/pages/LivePage.tsx` | ⬜ |
| FN-ALM-04 | 수동 방송 송출 | P1 | WEB/SRV | 기능 §4.3 · API §4.5 | M4 | `server/app/routes/alerts.py` | ⬜ |
| FN-ALM-05 | 경고 일시중지 (정비 작업 등) | P1 | WEB/SRV | 기능 §4.3 · API §4.5 | M4 | `server/app/routes/alerts.py` | ⬜ |

> **경고 방송은 TTS가 아니다.** 위반 유형별 사전 녹음 wav를 재생한다(생성 지연 제거).
> 확정 → 방송 시작 **1초 이내**가 요구사항이다.
> **이상 탐지(FN-AI-04)는 경고 방송을 발동하지 않는다.**
>
> **M3 에서 발동 지점은 이미 만들어져 있다.** 상태머신이 `alerted` · `re_alerted` 로
> 전이할 때 `alerted_at` · `alert_count` 를 기록하고 §5.2 메시지를 발행한다. M4 가
> 붙이는 것은 그 자리에서 **소리를 내고 MQTT 를 쏘는 부분**이며, 시정률의 기준점
> (`alerted_at`)은 이미 확정되어 있어 나중에 흔들리지 않는다.

---

## 4.4 기록 · 영상 (FN-REC) · 5건

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-REC-01 | 라이브 재스트리밍 (1080p 메인) | P0 | SRV | 기능 §4.4 | M1 | `server/infra/stream/` · `deploy/mediamtx.yml` · `front/src/live/` | ✅ |
| FN-REC-02 | 7일 링버퍼 녹화 | P0 | REC | 기능 §4.4 · API §4.7 | M1 | `recorder/capture.py` · `recorder/retention.py` | ✅ |
| FN-REC-03 | 이벤트 클립 · 키프레임 추출 | P0 | REC/SRV | 기능 §4.4 · API §4.7 | M1 (REC API) / M4 (예약 실행) | `recorder/clips.py` · `server/infra/clip/` | 🟡 |
| FN-REC-04 | 이벤트 DB 저장 | P0 | SRV | 기능 §4.4 · §6 | M2 | `server/infra/db/repository.py` · `server/app/routes/events.py` | ✅ |
| FN-REC-05 | 저장 용량 관리 | P1 | REC | 기능 §4.4 | M1 | `recorder/retention.py` | ✅ |

> **녹화는 서버가 아니라 REC 컴포넌트(`recorder/`)가 한다** (기능명세서 §4.4 「녹화 컴포넌트(REC) 분리」).
> 운용 시 7일 원본은 엣지 NVMe SSD 에 있고, 서버는 파일 경로가 아니라 **HTTP API(§4.7)로만**
> 접근한다. 개발 중 같은 기계에서 돌더라도 이 규칙을 지킨다 — M9 에 옮길 때 고치는 값이
> `RECORDER_BASE` 하나여야 하기 때문이다.
>
> **비-`ready` 응답은 사유를 담는다**(§4.7 `reason`). "보존 기간 경과" · "그 시각에
> 녹화가 없다" · "앞/뒤 N초 없음" 을 구분한다 — `status` 만으로는 지워진 것과 찍은 적이
> 없는 것이 같아 보이는데 대응이 다르다. **세그먼트 경계로 클립이 최대 10초 길어지는
> 것은 정상 동작이며 `partial` 이 아니다.**
>
> **FN-REC-03 이 🟡 인 이유**: `POST /clips` · `GET /keyframe`(추출 API)는 M1 에서 동작하지만,
> `confirmed_at + clip_post_roll_s + margin` 예약 실행과 `clip_status` 관리는 M4 다.
> 예약을 걸 자리(확정 시각)는 M3 상태머신이 이미 만들어 두었다.

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
| FN-UI-02 | 실시간 관제 — 2채널 라이브 + 오버레이 · **단독 확대 보기** · 수동 방송 | P0 | WEB | 기능 §4.6 · API §5 | M1 (라이브·상태·확대) / M2 (오버레이) / M3 (경고 상태 표시) / M4 (수동 방송) | `front/src/pages/LivePage.tsx` · `front/src/live/` | 🟡 (수동 방송만 남음) |
| FN-UI-03 | 이벤트 — 목록·필터 + 상세(클립·LLM·규정·타임라인) | P0 | WEB | 기능 §4.6 · API §4.1 | M5 | `front/src/pages/EventsPage.tsx` | ⬜ |
| FN-UI-04 | 영상 검색 — 자연어 질의 · 유사도순 결과 | P1 | WEB | 기능 §4.6 · API §4.3 | M7 | `front/src/pages/SearchPage.tsx` | ⬜ |
| FN-UI-05 | 분석 · 보고서 — 시정률 추이 · 반복 순위 · 히트맵 · 이상 탐지 | P1 | WEB | 기능 §4.6 · API §4.2 | M8 | `front/src/pages/AnalysisPage.tsx` | ⬜ |
| FN-UI-06 | 챗봇 — 통계·검색·브리핑 질의 | P1 | WEB | 기능 §4.6 · API §4.4 | M7 | `front/src/pages/AssistantPage.tsx` | ⬜ |
| FN-UI-07 | 설정 — 구역 그리기 · 캘리브레이션 · 음원 · 임계값 · 시스템 | P1 | WEB | 기능 §4.6 · API §4.5 | M6 | `front/src/pages/SettingsPage.tsx` | ⬜ |

> **오버레이는 도착 즉시 그리지 않는다.** `ts` 기준 지연 버퍼에 담았다가 재생 중인
> 프레임 시각에 맞춰 그린다. 정합 오차 목표 **±100ms**.
> **버퍼는 재생 경로별로 다르다** — `overlay_buffer_webrtc_ms` · `overlay_buffer_hls_ms`(2800).
> M1 실측 지연이 0.3초 대 2.5초라 단일 값으로는 맞출 수 없다.
> WebRTC 값은 **360 으로 확정**됐으나 반영은 M5 다(아래 「M5 보류 항목」).
> `overlay_stale_ms`(기본 1000ms) 초과 시 박스를 흐리게 표시한다.
>
> **단독 확대 보기에서 다른 채널의 구독을 끊지 않는다.** 영상만 내리고 이벤트 수신과
> 경고는 계속 돌린다 — 화면에 안 보이는 것과 감시가 멈추는 것은 다르다.
> 확대 상태는 URL(`/live?cam=1`)에 있어 새로고침해도 유지된다.
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
| FN-SYS-01 | 구성요소 상태 감시 (엣지·카메라·MCU·클라우드·저장소) | P0 | SRV | 기능 §4.8 · API §4.6 | M1 (카메라·저장소) / M2 (엣지) / M3 (MCU) / M7 (클라우드) | `server/app/routes/system.py` · `server/domain/edge_state.py` · `server/infra/stream/watcher.py` | 🟡 (MCU·클라우드만 남음) |
| FN-SYS-02 | 시각 동기화 (NTP · 클립 정합의 전제) | P0 | SRV/EDGE | 기능 §4.8 | M1 (서버) / M2 (엣지 오프셋) | `server/infra/timesync.py` · `edge/` | 🟡 |
| FN-SYS-03 | 클라우드 장애 격리 | P1 | SRV | 기능 §4.8 | M7 | `server/ai/adapter.py` | ⬜ |
| FN-SYS-04 | 지표 집계 (시정률 · 평균 시정 시간 · 판정 불가율 · 분포) | P0 | SRV | 기능 §4.8 · API §4.2·§6.7 | M3 (summary) / M8 (분포·시계열) | `server/domain/metrics.py` · `server/app/routes/metrics.py` | 🟡 |
| FN-SYS-05 | 판정 불가 집계 (`expired` 별도 집계) | P0 | SRV | 기능 §4.8 · API §6.7 | M3 | `server/domain/metrics.py` | ✅ |
| FN-SYS-06 | 엣지 메시지 거부 집계 (로깅 · 카운터 · 노출) | P0 | SRV | 기능 §4.8 · API §2.2 | M2 | `server/app/ws_edge.py` · `server/domain/edge_state.py` · `server/app/routes/system.py` | ✅ |

> **FN-SYS-06 — 후보를 조용히 버리지 않는다.** 스키마 검증에 실패한 엣지 메시지를
> 로그 없이 폐기하면 안 된다. 감지된 위반이 검증 단계에서 소리 없이 사라지는 것은
> 오탐보다 위험하다. 원본 페이로드와 검증 오류를 `WARNING` 이상으로 남기고,
> `edge_msg_rejected_total{type, reason}` 을 올리고, `GET /system/status` 와 대시보드
> 시스템 상태에 건수를 노출한다. 엣지 구현이 바뀌어 필드가 누락되기 시작하면
> 이 값이 오르는 것으로 즉시 드러나야 한다.

> `expired` 는 **시정률 분모·분자 모두에서 제외**하고 `undetermined_rate` 로 따로 집계한다.
> 두 숫자는 **항상 병기**한다 — `방송 후 시정률 87% (판정 불가 5%)`.
> `fall` · `is_false_positive` · `dropped` 도 시정률에서 전량 제외한다.
>
> **분모가 0이면 두 비율은 `null` 이다**(§6.7). `0.00` 은 "시정률 0%"라는 주장이고
> 실제로는 "판정 가능한 이벤트가 없다"이므로 화면은 `–` 로 그린다.
> 늦은 시정(`resolve_window_s` 초과 해소)은 `resolved_late` 로 분리해 분모에만 넣는다.
>
> **FN-SYS-04 가 🟡 인 이유**: `GET /metrics/summary`(시정률 · 판정 불가율 · 평균 시정
> 시간)는 M3 에서 동작한다. 같은 §4.2 의 `timeseries` · `distribution` · `repeat` 는
> 분석 화면(FN-UI-05)의 데이터원이라 M8 에 함께 만든다.

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
| 보존 기간 **개발 1시간 / 운용 7일** (`REC_RETENTION_DAYS=0.0417`) | `.env.example` | 기능 §4.4 | ✅ |
| mediamtx — RTSP 수신 · WHEP · LL-HLS (**내장 녹화 미사용**) | `deploy/mediamtx.yml` | 기능 §4.4 | ✅ |
| 가짜 카메라 4경로 + **밀리초 벽시계 타임코드 소성** | `deploy/fake_cams.py` | API §1.2 · FN-UI-02 | ✅ |
| REC 컴포넌트 — 세그먼트 녹화 · 보존 · §4.7 API 3종 | `recorder/` | API §4.7 | ✅ |
| §4.7 계약 스키마 (`ClipRequest` · `ClipResponse` · `RecStatusResponse`) | `packages/contracts/.../rest.py` | API §4.7 | ✅ |
| 메인 스트림 상태 감시 · `system` 발행 | `server/infra/stream/` | API §5.3 · FN-SYS-01 | ✅ |
| `GET /system/status` (storage·recording 은 REC 프록시 · null 규약) | `server/app/routes/system.py` | API §4.6 | ✅ |
| `/ws/dashboard` 허브 (M1 은 `system` 만 흐른다) · 소켓 1개 공유 | `server/app/ws_dashboard.py` · `front/src/api/system.ts` | API §5 | ✅ |
| NTP 오프셋 확인 (FN-SYS-02) | `server/infra/timesync.py` | 기능 §4.8 | ✅ |
| 실시간 관제 화면 — WHEP 우선 · HLS 폴백 · 표시 시각 | `front/src/live/` · `front/src/pages/LivePage.tsx` | FN-UI-02 | ✅ |
| **단독 확대 보기** — 타일 클릭·상단 버튼 · Esc · `/live?cam=N` · 가장자리 알림 | `front/src/pages/LivePage.tsx` · `front/src/live/live.css` | FN-UI-02 | ✅ |

**실측치** (2026-07-28, testsrc2 소스 기준)

| 항목 | 값 |
|---|---|
| 영상 지연 · WebRTC(WHEP) | **0.27 ~ 0.34초** (정상 재생 진입 후) |
| 영상 지연 · LL-HLS | **약 2.5초** |
| 카메라 → mediamtx → 소비자 (지연의 대부분) | **약 0.27초** |
| 녹화 용량 (2채널) | **1.95 GB/시간** (§4.4 산정 2.25 GB/시간 대비 −13%) |
| 카메라 끊김 감지 | **2.9초** 만에 `reconnecting`, 7.6초에 `down` |

> **오버레이 정합(±100ms) 관점**: 이 실측을 근거로 명세서가 버퍼를 경로별로 나눴다 —
> `overlay_buffer_webrtc_ms`(400) · `overlay_buffer_hls_ms`(2800). 화면에 어느 경로로
> 재생 중인지 계속 표시하고(타일 하단), 그 라벨의 툴팁에 적용 정책 키를 적어 둔다.
> **값은 프론트에 적지 않는다** — `GET /policies`(M6)로 읽는다. 경로 → 정책 키 대응만
> `front/src/live/player.ts` 의 `OVERLAY_BUFFER_POLICY_KEY` 에 있고, M2 의 오버레이
> 렌더링이 이 대응을 따라 버퍼를 고른다.

**단독 확대 보기 실측** (2026-07-29, 1440×900 뷰포트)

| 상태 | 영상 크기 |
|---|---|
| 분할 (2채널) | 412 × 232 |
| 단독 확대 | **1158 × 652** (면적 약 7.9배) |

확대 중 cam2 를 내렸을 때 사이드바 표시가 `카메라 메인 2/2 → 1/2` 로 바뀌었고
**새로 열린 WebSocket 은 0개**였다 — 영상만 내려가고 구독은 유지된다는 뜻이다.

---

## M2 산출물 (엣지 인터페이스와 이벤트 생성)

**이번 단계에는 상태머신이 없다.** 확정(3초)·경고·해소·쿨다운·재결합·소실 유예는
전부 M3 이다. 여기서 만든 이벤트는 `status = "candidate"` 에 머문다.

| 항목 | 위치 | 근거 | 상태 |
|---|---|---|---|
| `/ws/edge` — 4종 수신 · 검증 · 디스패치 | `server/app/ws_edge.py` | API §2 | ✅ |
| **거부 집계** — 로깅 · `{type, reason}` 카운터 · `system` 발행 | `server/app/ws_edge.py` · `server/domain/edge_state.py` | §2.2 · FN-SYS-06 | ✅ |
| 엣지 상태 (하트비트 → `sub_state` · `fps` · 게이지) | `server/domain/edge_state.py` | §2.4 · §4.6 | ✅ |
| 후보 병합 판단 (순수) | `server/domain/event_machine.py` | FN-EVT-01 | ✅ |
| `frame` + 이벤트 상태 → `overlay` 합성 (순수) | `server/domain/overlay.py` | §5.1 | ✅ |
| 이벤트 저장소 · 구역 · 정책 (DB 구현) | `server/infra/db/repository.py` | §6 · FN-REC-04 | ✅ |
| `GET /events` · `/events/{id}` (커서 페이징 · §1.4 오류 봉투) | `server/app/routes/events.py` | §4.1 | ✅ |
| `GET /zones` · `GET /policies` (읽기 전용) | `server/app/routes/zones.py` · `policies.py` | §4.5 | ✅ |
| 시나리오 3종 + **키프레임 보간(`frame_fps`)** | `sim/cases/` · `sim/edge_sim/scripted.py` | FN-DET-01 · FN-DET-12 | ✅ |
| 오버레이 지연 버퍼 · 트랙별 선형 보간 | `front/src/live/overlayBuffer.ts` | §5 「오버레이 시간 정합」 | ✅ |
| 오버레이 렌더링 (표시 규칙 · 거리선 · 구역 라벨) | `front/src/live/OverlayCanvas.tsx` | 기능 §4.6 표시 규칙 | ✅ |
| 정책값·구역 캐시 (값을 프론트에 적지 않는다) | `front/src/api/policies.ts` · `zones.ts` | 절대규칙 6 · §5.4 | ✅ |
| 개발용 구역 시드 · 계약에 없는 정책 키 정리 | `scripts/seed_zones.py` · `scripts/seed_policies.py` | — | ✅ |
| **2채널 동시 시나리오** (오버레이가 `cam_id` 로 갈리는지) | `sim/cases/both_cameras.yaml` | — | ✅ |
| **정합 진단 표시** (개발용 · `/live?debug=1`) | `front/src/live/CameraTile.tsx` | FN-UI-02 | ✅ |
| **marker 대조** — 영상·좌표가 한 정의를 공유 | `deploy/marker_path.py` · `sim/edge_sim/marker.py` · `tasks.py marker` | FN-UI-02 | ✅ |

**설계 판단 (M2 에서 정한 것)**

| 판단 | 이유 |
|---|---|
| `overlay.objects[].alert_state` 는 M2 에서 **`candidate`** | 명세서 v7 이 §5.1 에 `candidate` 를 추가했다. `null`(이벤트 없음)과 구분되며, 대시보드는 **적색으로 그리지 않고** 청록 점선 + `확정 중` 라벨로 표시한다 — 확정 전이므로 위반으로 단정할 수 없다 |
| §5.2 `event_created` 를 **발행하지 않는다** | "신규 **확정** 이벤트"이고 `confirmed_at` 이 필수다. 확정 판정이 M3 이므로 지금 보낼 수 있는 것이 없다 |
| 지게차 `overlay.anchor` 는 **엣지가 보낸 값**을 그대로 쓴다 | 명세서 v7 이 §2.1 에 정규화 `anchor` 를 신설했다. 마스크 하단에서 산출한 값이라 박스 아래변 중앙과 다르며(포크가 뻗었거나 적재물이 있으면 어긋난다), 서버가 추정하지 않는다 |
| `track_lost` 는 **오버레이만 내리고** 이벤트를 전이시키지 않는다 | 소실 유예(FN-EVT-07 ①)에는 만료 타이머가 딸려 있다. 전이만 흉내 내면 `expired` 로 끝나는 길이 없어 이벤트가 영원히 `lost` 로 남고 판정 불가율이 왜곡된다 |
| 위반 표시는 후보가 오면 켜지고 **트랙이 사라질 때만** 꺼진다 | 해소 판정(FN-EVT-03)이 M3 이다. 지금 임의의 시간으로 끄면 그 값이 곧 가짜 시정률이 된다 |
| `events.zone_id` 는 **확정 후 얼어붙는다** | §4.2. 확정 전에는 최신 관측값으로 따라가되, 확정 이후에는 "어디서 확정됐는가"를 고정한다 — 위반자가 구역을 나간 뒤 이벤트의 구역까지 바뀌면 구역별 집계가 사후에 흔들린다 |
| 주소 기본값에 **`localhost` 을 쓰지 않는다** | Windows 에서 `::1` 로 먼저 풀려 연결마다 IPv6 타임아웃 2.6초를 먹는다. 좌표 지연 2.8초의 주범이었다. `.env` · `vite.config.ts` 주석에 이미 있던 규약을 코드 기본값 전부에 적용했다 |
| 가짜 카메라를 **모듈로**(`-m deploy.fake_cams`) 띄운다 | 파일 경로로 실행하면 `sys.path[0]` 이 `deploy/` 가 되어 marker 궤적 공유 정의를 import 할 수 없다 |
| 정책값을 못 읽으면 **오버레이를 그리지 않는다** | 지연 버퍼를 모르는 채 그린 박스는 틀린 위치에 있고, 틀린 박스는 없는 박스보다 나쁘다. 타일에 `오버레이 대기` 를 띄운다 |
| `금지구역 폴리곤`은 캐시만 하고 **아직 그리지 않는다** | `polygon_m` 은 지면 실좌표다(§6). 화면에 그리려면 역호모그래피가 필요한데 캘리브레이션이 M6 다. 지금은 사람 라벨의 구역 표시 이름에만 쓴다 |

**좌표 지연 2.8초 — 원인과 실측** (2026-07-29)

시나리오 재생 중에도 좌표가 2~2.8초 뒤처지는 문제를 구간별로 재서 원인을 좁혔다.
**버퍼 값 오적용이 아니었다** — 화면 표시와 실제 적용 버퍼는 같은 값을 보고 있었다.

| 구간 | `ws://localhost:8000` | `ws://127.0.0.1:8000` |
|---|---|---|
| `load_case` 파싱·검증 (225건) | 254 ms | 150 ms |
| **WebSocket connect** | **2638 ms** | **8.4 ms** |
| 첫 메시지 `ts` 와 실제 송신 시각의 어긋남 | **2897 ms** | 163 ms |

원인은 두 가지가 겹친 것이다.

1. **`localhost` 이 `::1`(IPv6)로 먼저 풀린다.** 서버는 `127.0.0.1` 에만 바인딩하므로
   매 연결이 IPv6 타임아웃 2.6초를 먹고 IPv4 로 폴백했다. `.env` 규약과
   `front/vite.config.ts` 주석에 이미 적혀 있던 함정을 **코드 기본값들이 지키지
   않고 있었다.** 시뮬레이터·vite 프록시·서버·REC·MQTT 기본값을 전부 `127.0.0.1` 로 바꿨다.
2. **`ts` 기준점과 재생 기준점을 서로 다른 순간에 잡았다.** `ts` 는 파싱 **전**에,
   재생은 연결 **후**에 잡혀서 그 사이 시간(파싱 + 연결)이 전 구간 고정 오차로 남았다.
   `retime()` 을 두어 **연결 직후에 두 기준점을 나란히** 잡고 `ts` 를 다시 찍는다.

| 지표 | 고치기 전 | 고친 뒤 |
|---|---|---|
| `overlay` 도착 − `ts` (중앙값) | **2813 ms** | **17 ms** |
| 최소 / 최대 | 2805 / 2882 ms | 3.7 / 341 ms |

최대 341ms 는 Windows `asyncio.sleep` 의 스케줄링 분해능(약 15ms)과 GC 가 겹친 꼬리다.
중앙값이 17ms 이므로 좌표 경로는 사실상 지연이 없다.

**실측치** (2026-07-29)

| 항목 | 값 |
|---|---|
| 시나리오 메시지 수 (`no_helmet`, 26초) | `frame` 209 + `candidate` 17 + `heartbeat` 6 = 232건 |
| 엣지 → 서버 프레임률 (`frame_fps: 8`) | 카메라당 8fps (FN-DET-01 요구 하한과 동일) |
| `both_cameras` 2채널 동시 송출 | `frame` cam1 129 + cam2 145 · `candidate` 8 = 286건 |
| `no_helmet` 실행 후 생성된 이벤트 | **정확히 2건**, 후보 17건이 병합됨 |
| `basic_walk` 실행 후 생성된 이벤트 | **0건** |
| 좌표 경로 지연 (`overlay` 도착 − `ts`) | **중앙값 17ms** |
| 오버레이 지연 버퍼 (WebRTC) | `overlay_buffer_webrtc_ms` = **300ms** (`GET /policies`) |
| M1 실측 영상 지연 (WebRTC) | 0.27 ~ 0.34초 (중앙값 약 305ms) |
| **예상 정합 오차** | **−5 ~ +30ms** (버퍼 300 − 영상 지연 270~340) |

> 좌표 경로가 17ms 이므로 정합 오차는 사실상 `버퍼(300) − 영상 지연(270~340)` 이다.
> 실제 값은 marker 검증으로 화면에서 재야 한다 — 영상의 **촬영** 시각은 브라우저가
> 알려주지 않으므로 계산만으로는 확정할 수 없다.

**정합 검증 수단 두 가지**

| 수단 | 무엇을 보는가 |
|---|---|
| 화면의 「정합 진단」 토글 (`/live?debug=1`) | 표시 프레임 시각 · 그린 좌표 `ts` · 둘의 차이 · **실제 적용된** 버퍼 값과 정책 키 · 좌표 도착 지연 · 버퍼 적재량. 차이가 적용 버퍼와 다르면 버퍼가 잘못 걸린 것이다 |
| marker 대조 (`uv run tasks.py marker`) | 영상에 태운 사각형과 오버레이 박스가 겹치는가. **영상과의 실제 오차는 이쪽으로만 잰다.** 궤적은 `deploy/marker_path.py` 한 곳에만 정의되고, ffmpeg 표현식과 파이썬 함수가 같은 값을 내는지 테스트가 대조한다 |

**프론트 단위 테스트 러너가 없다.** `overlayBuffer.ts` 의 보간·부호·낡음 판정은
스크래치에서 `tsc` 로 컴파일해 node 로 9가지 성질을 확인했지만(전부 통과),
`uv run tasks.py verify` 는 프론트에서 `tsc --noEmit` 과 `vite build` 만 돈다.
러너(vitest 등)를 넣을지는 M5(`tasks.py types`)에서 함께 정한다.

---

## M3 산출물 (상태머신과 지표)

**이 단계에서 「방송 후 시정률」이 만들어진다.** 이 프로젝트의 유일한 차별점이므로,
설계 판단이 갈릴 때마다 값이 커지는 쪽이 아니라 **방어할 수 있는 쪽**을 택했다.

| 항목 | 위치 | 근거 | 상태 |
|---|---|---|---|
| 상태머신 (확정·해소·쿨다운·소실 유예·게이팅 동결) | `server/domain/event_machine.py` | 기능 §4.2 · API §6.3 | ✅ |
| 재결합 매칭 (시간 비례 반경 · 1:1) | `server/domain/reassociation.py` | FN-EVT-07 ②③ | ✅ |
| 지표 산출 (시정률 · 판정 불가율 · 평균 시정 시간) | `server/domain/metrics.py` | §4.8 · §6.7 | ✅ |
| 집행 계층 (저장 · §5.2 발행 · 틱 · 재시작 복구) | `server/app/event_service.py` | §5.2 · §5.3 | ✅ |
| `GET /metrics/summary` | `server/app/routes/metrics.py` | §4.2 | ✅ |
| `PATCH /events/{id}` (오탐 · 강제 종결) | `server/app/routes/events.py` | §4.1 · FN-EVT-05 | ✅ |
| 저장소 확장 (`find_open_all` · `metrics_rows` · 타임라인) | `server/infra/db/repository.py` | §4.1 · §6 | ✅ |
| `candidate.violation_type` 단수화 (계약·시나리오·서버) | `packages/contracts/.../edge.py` · `sim/cases/` | §2.2 | ✅ |
| **`dropped` 종결 상태** (확정 전 소멸 · 레코드 보존) | `packages/contracts/.../enums.py` · `event_machine.py` | §4.2 | ✅ |
| **`resolved_late` 버킷 · 분모 0 → `null`** | `server/domain/metrics.py` · `.../rest.py` | §4.2 · §6.7 | ✅ |
| **`last_alerted_at` · `note` 컬럼** (마이그레이션 `0003`) | `server/infra/db/` · `event_service.py` | §6 · §5.2 | ✅ |
| **`track_miss_timeout_ms`** 로 소실 판정 (표시용 키와 분리) | `.../policies.py` · `event_machine.py` | §4.5 | ✅ |
| 시나리오 9종 + **기대값 자동 대조** | `sim/cases/*.yaml` · `sim/case_check.py` · `sim/tests/test_cases.py` | — | ✅ |
| 전이 → 오버레이 · 재시작 복구 검증 | `server/tests/test_event_service.py` | §5.1 · FN-UI-02 | ✅ |
| `uv run tasks.py cases` (지표를 표로 확인) | `tasks.py` | — | ✅ |
| 오버레이 라벨에 재경고 표시 | `front/src/live/OverlayCanvas.tsx` | FN-EVT-04 | ✅ |

**시나리오 9종 — 기대값과 실행 결과** (`uv run tasks.py cases`)

| 시나리오 | 무엇을 잠그는가 | 시정률 | 판정 불가율 | 해소 | 늦은 시정 | 미시정 | 판정 불가 | 쓰러짐 |
|---|---|---|---|---|---|---|---|---|
| `normal_resolve` | 확정 3초 · 해소 10초 기본 경로 | 1.00 | 0.00 | 1 | 0 | 0 | 0 | 0 |
| `no_resolve` | 쿨다운 30초 → 재경고, 미시정은 분모에 남는다 | 0.00 | 0.00 | 0 | 0 | 1 | 0 | 0 |
| `reassoc_success` | 시간 비례 반경으로 되살아나 시정까지 간다 | 1.00 | 0.00 | 1 | 0 | 0 | 0 | 0 |
| `reassoc_fail` | 유예 15초 만료 → `expired` 는 **미시정이 아니다** | **`null`** | 1.00 | 0 | 0 | 0 | 1 | 0 |
| `id_switch_guard` | 재결합 후 해소 타이머를 **0부터** 다시 채운다 | 1.00 | 0.00 | 1 | 0 | 0 | 0 | 0 |
| `gating_freeze` | `helmet` 생략 구간에서 타이머 **동결**(초기화 아님) | 0.00 | 0.00 | 0 | 0 | 1 | 0 | 0 |
| `fall_excluded` | 쓰러짐이 분모에 섞이면 1.00 이 0.50 이 된다 | 1.00 | 0.00 | 1 | 0 | 0 | 0 | 1 |
| `false_positive` | 오탐이 분모에 남으면 1.00 이 0.50 이 된다 | 1.00 | 0.00 | 1 | 0 | 0 | 0 | 0 |
| `dropped` | 확정 전 소멸이 **레코드로 남고** 어느 비율에도 안 든다 | **`null`** | **`null`** | 0 | 0 | 0 | 0 | 0 |

> **`reassoc_fail` 의 시정률이 `0.00` 이 아니라 `null` 인 이유**(§6.7). 해소 0 · 늦은
> 시정 0 · 미시정 0 이면 분모가 0 이다. `0.00` 은 "시정률 0%"라는 주장인데 실제로는
> "판정 가능한 이벤트가 없다"이며, 판정 불가만 있는 구간에서 0% 가 표시되면 시스템이
> 전혀 작동하지 않은 것처럼 보인다. 대시보드는 `null` 을 `–` 로 그린다
> (`front/src/types/system.ts` 의 `formatRate`).
>
> **`dropped` 시나리오가 잠그는 것**: 후보가 2초만 관측되고 사라진다(확정에 1초
> 모자란다). 레코드는 `dropped` 로 남고, 병합 키는 풀리며, 두 비율은 모두 `null` 이다.
> 미시정으로 새면 시정률이 `0.00`, 판정 불가로 새면 판정 불가율이 `1.00` 으로 나온다 —
> 셋이 모두 구분된다.

기대값은 각 yaml 의 `expect:` 블록에 있고, 대조는 `sim/case_check.py` 가 한다.
**눈으로 보고 판단하는 경로를 남기지 않았다** — 같은 검사가 `pytest`(따라서
`uv run tasks.py verify`) 안에서도 돈다.

시각까지 잠근 시나리오가 셋이다. 이 숫자들은 타이머가 **왜** 그 시각에 끝났는지를
구분한다.

| 시나리오 | 잠근 시각 | 규칙이 깨졌다면 |
|---|---|---|
| `gating_freeze` | 확정 **+9.5초** | 게이팅 무시면 +3.5초, 초기화면 +11.0초 |
| `id_switch_guard` | 해소 **+20.0초** | 적립분(2초)을 이어받았다면 +18.0초 |
| `reassoc_fail` | `expired` (+23.0초) | 유예 없이 종결했다면 +8.0초에 끝났다 |

**설계 판단 (M3 에서 정한 것)**

| 판단 | 이유 |
|---|---|
| **타이머는 관측이 있을 때만 흐른다** | 사람이 보이지 않는 구간에서 해소 타이머가 차오르면 그냥 사라진 사람이 "시정했다"로 집계된다. 확정·해소 타이머는 `tick` 이 아니라 `frame` · `candidate` 도착 시점에만 전진한다 |
| 확정 판정에 `observed_ms`(엣지 값)를 쓰지 않는다 | §2.2 가 "참고값"이라고 했다. 그대로 믿으면 엣지 규칙이 바뀔 때 서버 확정 기준까지 함께 흔들린다. 서버는 자기 관측으로 3초를 잰다 |
| **확정 전 소멸한 후보는 `dropped` 로 종결한다** (M3 갱신) | 처음에는 남길 상태가 없어 레코드를 지웠으나, 명세서가 `dropped` 를 신설해 되돌렸다. 지우면 `dropped / (dropped + 확정)` 을 셀 수 없어 `confirm_duration_s` 튜닝 근거가 사라지고, `expired` 로 보내면 판정 불가율이 오염되며, `candidate` 로 두면 병합 키(FN-EVT-01)를 점유한다. 종결 상태이므로 병합 키는 풀린다 |
| DB `alerted_at` 은 **최초**, `last_alerted_at` 이 **최근** (M3 갱신) | 처음에는 컬럼 하나로 버텼다. 명세서가 컬럼과 메시지를 분리해 이제 둘 다 저장한다. 최근 시각으로 `alerted_at` 을 덮으면 `resolution_sec`(= `alerted_at → resolved_at`)이 마지막 방송 기준으로 줄어 **시정률이 부풀려진다** |
| 해소 판정을 **`frame`** 으로 한다 | 후보는 규칙이 걸릴 때만 온다(§2.2). "후보가 끊겼다"만으로는 위반이 사라진 것과 대상이 사라진 것을 구분할 수 없다. 프레임에는 둘이 다르게 나타난다 |
| `proximity` 해소 거리는 접지점↔`anchor` 로 재되 `min_distance_m` 에는 쓰지 않는다 | 그 컬럼의 원천은 후보의 `nearby[].dist_m`(마스크 최근접 · §6.5)이다. 두 방식의 값을 같은 칸에 섞으면 어느 방식으로 잰 숫자인지 사후에 알 수 없다 |
| 게이팅 동결은 **`no_helmet` 과 `fall`** 에만 적용 | §6.3 의 동결은 분류 결과를 채택하지 못한 상황을 말한다. `zone_intrusion` · `proximity` 는 좌표로 판정하므로 `helmet` 과 무관하다. `fall` 은 `posture: unknown` 이 같은 뜻이라 동결한다 |
| 재결합은 **트랙 단위**로 한다 | 한 사람에게 안전모 미착용과 구역 침입이 동시에 걸려 있었다면 두 이벤트가 함께 살아나야 한다. 하나만 살리면 나머지가 `expired` 로 떨어져 판정 불가율이 이유 없이 오른다 |
| 재결합해도 DB `lost_at` 을 지우지 않는다 | "이 이벤트는 한 번 끊겼다"는 사실 자체가 추적 품질의 근거다. `reassoc_count` 와 함께 남긴다 |
| 엣지가 끊겨도 이벤트를 종결하지 않는다 | 오버레이 표시만 내리고, 진행 중 이벤트는 미관측으로 보아 `lost` → `expired`(판정 불가)로 간다. 관측 주체가 사라졌다는 사실을 "시정했다"로도 "미시정"으로도 바꾸지 않는다 |
| 기동 시 진행 중 이벤트를 복구하되 **타이머는 0부터** | 복구하지 않으면 재시작 한 번이 그 이벤트들을 영원히 미해소로 남긴다. 반대로 재시작 전 관측량을 추정해 채우면 관측 없이 확정·해소가 일어난다. `lost` 유예도 기동 시각부터 다시 센다(늦게 종결되는 쪽이 안전하다) |
| `resolved` · `resolved_late` · `unresolved` 는 **배타적** (M3 갱신) | 처음에는 늦은 시정이 `unresolved` 에 섞였다. 명세서가 `resolved_late` 를 신설해 셋으로 갈랐고, 셋의 합이 분모다 — 응답만 보고 `correction_rate = resolved / (resolved + resolved_late + unresolved)` 가 성립한다. "시정은 했으나 늦었다"와 "아직 안 했다"는 현장 대응이 다르다 |
| **분모가 0이면 비율은 `null`** (M3 갱신) | `0.0` 은 "시정률 0%"라는 주장이고 실제로는 "판정 가능한 이벤트가 없다"이다. 둘을 같은 값으로 내보내면 판정 불가만 있던 구간이 "아무도 시정하지 않았다"로 읽힌다 — 대응이 정반대인 두 상황이다 |
| `resolved` 인데 `resolution_sec` 이 없으면 **`resolved_late`** | 깨진 레코드다. 창 안에 시정됐다고 주장할 근거가 없으므로 분자에서 빼되, `unresolved`(아직 안 했다)도 사실이 아니다. 분모에만 들어가는 자리가 늦은 시정 쪽이다 |
| 소실 판정에 **`track_miss_timeout_ms`** 를 쓴다 (M3 갱신) | 전용 정책 키가 없어 `overlay_stale_ms`(표시용)를 빌려 쓰던 것을, 명세서가 신설한 키로 바꿨다. 박스를 흐리게 그릴 시점(1000ms)과 이벤트를 `lost` 로 보낼 시점(1500ms)은 튜닝 이유가 다르므로 **혼용하지 않는다** |
| 지표 기간의 기본값은 **UTC 오늘** | 저장이 UTC 다(§1.2). 집계 경계를 로컬로 옮기면 같은 이벤트가 어느 날에 속하는지가 서버 시간대 설정에 따라 달라진다 |

**M3 이 쓰는 정책값** — 전부 `GET /policies`(DB)에서 읽는다. 코드에 값이 없다.

| 키 | 기본값 | 쓰이는 곳 |
|---|---|---|
| `confirm_duration_s` | 3.0 | 확정, 그리고 **확정 전 후보 폐기**(같은 길이의 소멸 지속) |
| `resolve_duration_s` | 10.0 | 해소 |
| `cooldown_s` | 30.0 | 재경고 |
| `track_lost_grace_s` | 15.0 | 유예 만료 → `expired` |
| `reassoc_window_s` · `reassoc_max_speed_ms` · `reassoc_radius_cap_m` | 10.0 · 1.5 · 5.0 | 재결합 |
| `resolve_window_s` | 300.0 | 시정률 **분자** 조건 (`resolved` / `resolved_late` 를 가른다) |
| `proximity_threshold_m` | 2.0 | `proximity` 해소 판정 |
| `track_miss_timeout_ms` | 1500.0 | **소실 판정**과 타이머 적산 상한. 표시용 `overlay_stale_ms` 와 혼용하지 않는다 |

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

**v6 (직전에 보고한 A 7건 전량)** — 전부 코드에 반영했다.

| 항목 | 확정된 내용 | 반영 |
|---|---|---|
| §4.6 관측 전 값 | **`null`** 로 확정. 필드별 규약 표 신설. 예외는 `edge.msg_rejected_total`(항상 `int`, 0 시작)과 `sub_state`(`"down"`) | 계약 nullable · 라우트 · 대시보드가 `null` 을 "측정 불가"로 0 과 다르게 표시 |
| §4.6 `storage` | §4.7 과 **동일한 5필드**로 확장 (`total_gb`·`used_gb`·`free_gb`·`retention_days`·`oldest_segment_at`) | 서버가 고르지 않고 그대로 전달 |
| §4.6 `cameras[].recording` | 신설. REC `GET /status` 값을 **그대로 전달** | 프론트 REC 표시가 추론이 아니라 이 값이다. REC 미도달이면 `null`(점선 · `REC ?`) |
| §4.7 비-`ready` 응답 | `reason` 필드 신설. 세그먼트 경계로 클립이 최대 10초 **길어지는 것은 정상 동작**으로 명시 | REC 이 보존 경과 / 미녹화 / 앞뒤 부족을 구분해 문구로 담는다. 길어진 것은 `partial` 로 보고하지 않는다 |
| §5.4 `zone` | `GET /zones` 원소에서 **`cam_id` 를 제외한** 형태로 확정 | 현재 구현이 맞았다 — 변경 없음 |
| §4.2 `points[].t` | `day`·`week` → `YYYY-MM-DD`(주는 월요일), `hour` → `YYYY-MM-DDTHH:00:00Z` | `str` 유지 + 형식 회귀 테스트 |
| §4.2 `distribution.key` | 모든 축에서 **문자열**, `hour_of_day` 는 `"00"`~`"23"` 제로패딩 | `str` 유지 + 정렬 회귀 테스트 |

**v6 · 오버레이 버퍼 분리** — M1 실측(WebRTC 0.27~0.34초 / LL-HLS 약 2.5초)을 근거로
`overlay_buffer_ms`(300) 가 `overlay_buffer_webrtc_ms`(400) · `overlay_buffer_hls_ms`(2800)
로 나뉘었다. Policies·시드·프론트에 반영했다.

**v7 (직전에 보고한 5건 전량)** — 전부 코드에 반영했다.

| 항목 | 확정된 내용 | 반영 |
|---|---|---|
| §5.1 `alert_state` | **`candidate` 추가.** `candidate`(관측됐으나 확정 전)와 `null`(이벤트 없음)은 다르다. 대시보드는 `candidate` 를 **적색으로 그리지 않는다** | `AlertState` 확장 · 오버레이가 `EventStatus.CANDIDATE → "candidate"` 로 매핑 · 프론트는 청록 + **점선** + `확정 중` 라벨 |
| §2.1 vehicle `anchor` | **정규화 접지 좌표 신설.** 마스크 하단에서 산출하며 **bbox 아래변 중앙이 아니다** | 계약 필수 필드 · 서버가 추정을 그만두고 그대로 사용 · `sim/cases` 가 bbox 중앙과 다른 값을 싣는다 |
| §2.2 `observed_ms` | **후보 메시지 하나에 위반 유형 하나.** 유형마다 조건 충족 시각이 다르므로 각각 보낸다 | `violations` 를 길이 1로 제약 · `plan_candidate` 단순화 · 시나리오의 복합 후보를 유형별로 분리(`observed_ms` 도 유형 기준으로 다시 계산) |
| `overlay_buffer_webrtc_ms` | **400 → 300** (영상 지연 실측 중앙값 약 305ms) | 계약 기본값 · DB 재시드 |
| `events.zone_id` | **확정 시점에 고정.** 확정 전에는 최신 관측값으로 갱신 | `merge_changes` 가 `status == candidate` 일 때만 갱신 |

**v8 (직전에 보고한 A 4건 전량)** — 명세서에서 해결되어 코드에 반영했다.

| 항목 | 확정된 내용 | 반영 |
|---|---|---|
| §2.2 `violations[]` | **`violation_type`(단수 문자열)로 필드명 자체가 바뀌었다.** 예시 JSON · 필드 표 · 산문이 모두 일치한다 | 계약 필드명 변경 · `edge_sim` 시나리오 전량 · 서버 수신부 · 테스트. **§5.1 `overlay.objects[].violations` 는 배열 그대로다** — 한 트랙에 이벤트가 여럿 걸릴 수 있고 화면은 합쳐 보여준다 |
| §2.2 `observed_ms` | 위 변경으로 가리키는 필드가 실재하게 됐다 | 문구 그대로 구현. 다만 **확정 판정에는 쓰지 않는다**(M3 설계 판단 참조) |
| §5 오버레이 정합 4번 | `400` → **`300`** 으로 §4.5 와 일치 | 문서만. 코드는 원래 DB 값을 읽었다 |
| §4.6 `cloud.quota_used` | **nullable 확정** | 이미 그렇게 구현되어 있었다 — 변경 없음 |

**v9 (직전에 보고한 A 6건 전량 + 사람이 찾은 1건)** — 전부 코드에 반영했다.

| 항목 | 확정된 내용 | 반영 |
|---|---|---|
| **분모가 0일 때의 시정률** ★ | §4.8 · §6.7 이 **`null`** 로 확정. `0.00` 은 "시정률 0%"라는 주장이지만 실제로는 "판정 가능한 이벤트가 없다"이다. 대시보드는 `–` 로 그리고 0% 와 다르게 표시한다 | `MetricsSummary` · `MetricMsg` 의 두 비율을 nullable 로. `_ratio` 가 `None` 을 낸다. `reassoc_fail` 기대값을 `null` 로 바꿨고, 프론트에 `formatRate`(→ `–`)를 두었다 |
| `alerted_at` 이 최초인가 최근인가 | **컬럼과 메시지를 분리.** `events.last_alerted_at` 신설, `alerted_at` 은 최초로 고정. `resolution_sec` 은 `alerted_at`(최초) 기준 유지 | 마이그레이션 `0003` · `_STATUS_STAMP` · `EventUpdatedMsg.last_alerted_at` · `_to_re_alerted` 가 `alerted_at` 을 건드리지 않는다 |
| §4.2 `resolved` · `unresolved` 의 정의 | **`resolved_late` 버킷 신설.** 셋이 서로 배타적이고 합이 분모다. `correction_rate = resolved / (resolved + resolved_late + unresolved)` | `summarize` 가 세 버킷을 따로 센다. `GET /metrics/summary` 응답에 `resolved_late` 추가 |
| `frame` 연속 미관측의 기준 시간 | **`track_miss_timeout_ms`(1500ms) 신설.** 표시용 `overlay_stale_ms` 와 혼용 금지 | `Policies` · `PolicyPatch` · DB 시드 · `EventMachine._miss_s` |
| §5.2 `event_created.keyframe_url` | **nullable 로 확정** | 계약을 넓히고, M3 은 `null` 을 보낸다 — 404 가 될 URL(`KEYFRAME_URL_TEMPLATE`)을 지웠다. M4(FN-REC-03)가 채운다 |
| `events.note` 컬럼 | **신설** | 마이그레이션 `0003` · `PATCH /events/{id}` 가 저장한다 |
| 확정 전 소멸한 후보의 상태 값 | **`dropped` 신설.** 지표 전량 제외, 병합 키 미점유, `dropped / (dropped + 확정)` 은 진단용으로 보존 | `EventStatus.DROPPED` · `_to_dropped` · `Effect` 에서 `delete` 액션 제거 · 저장소 `delete` 제거 · 시나리오 `dropped` 추가 |

### A. 남아 있는 확인 필요

이번 반영 중에 드러난 **명세서 내부의 불일치**다. 코드는 더 구체적인 절(§6.7 정의)을
따랐고, 그 선택을 여기 적는다(CLAUDE.md 절대규칙 8).

| 내용 | 상세 |
|---|---|
| **§4.8 의 시정률 식이 `resolved_late` 를 빠뜨렸다** | 기능명세서 §4.8 은 여전히 `correction_rate = resolved / (resolved + unresolved)` 다. API §4.2 · §6.7 은 `resolved / (resolved + resolved_late + unresolved)` 다. §4.8 표에 `dropped` 행은 추가됐으나 식은 갱신되지 않았다. **코드는 §6.7 을 따랐다.** 두 절의 식을 맞춰 달라 |
| **§4.2 와 §6.7 의 판정 불가율 식이 다르다** | §4.2 는 `expired / (resolved + unresolved + expired)`, §6.7 은 `expired / (resolved + resolved_late + unresolved + expired)` 다. 늦은 시정이 판정 불가율 분모에 드는지가 갈린다. **코드는 §6.7 을 따랐다** — `resolved_late` 는 모집단이지 판정 불가가 아니므로 분모에 있어야 일관된다 |
| **§4.2 예시의 `total_violations` 가 버킷 합과 안 맞는다** | 예시가 `total_violations: 23` 인데 `resolved(20) + resolved_late(1) + unresolved(2) + undetermined(1) = 24` 다. `resolved_late` 를 넣으면서 합계를 갱신하지 않은 것으로 보인다. **코드는 네 버킷의 합을 `total_violations` 로 낸다** — 응답 안에서 산술이 성립해야 하기 때문이다 |
| **§5.3 `metric` 에 `resolved_late` 가 없고 nullable 여부도 없다** | §5.3 예시는 `resolved` · `unresolved` 만 싣고 비율은 숫자다. 그러나 같은 값이므로 분모가 0이면 `null` 을 실을 수밖에 없다. **코드는 두 비율을 nullable 로 넓히고 `resolved_late` 는 넣지 않았다**(§5.3 예시 그대로). 화면이 늦은 시정 건수를 알려면 `GET /metrics/summary` 를 읽어야 한다 |
| **`dropped` 의 종결 시각 컬럼이 없다** | §6 `events` 에 `resolved_at` · `expired_at` 은 있으나 `dropped_at` 이 없다. 그래서 §4.1 `timeline` 에 `dropped` 가 나오지 않고, `dropped / (dropped + 확정)` 진단도 `detected_at` 기준으로만 기간을 끊을 수 있다. 없는 컬럼을 만들지 않았다 |
| **`last_alerted_at` · `note` 를 다시 읽을 경로가 없다** | 두 컬럼은 §6 에 생겼는데 §4.1 `GET /events/{id}` 응답 필드 목록에는 없다. 그래서 **저장은 되지만 REST 로 다시 조회할 수 없다** — 오탐 사유를 화면에서 보려면 응답에 `note` 가 있어야 한다(FN-UI-03 · M5 가 이것을 필요로 한다). 응답 스키마에 추가할지 정해 달라 |

### B. 판단이 필요했던 타입

| 필드 | 판단 |
|---|---|
| `anomaly_sample_interval_min` | "분 단위 주기"라 개수로 볼 수도 있으나 **지속시간 계열로 보아 `float`** 로 했다. 정수만 허용해야 한다면 되돌려야 한다 |
| `cls_min_crop_px` | Policies 에서 **유일하게 `int` 로 남긴 값**이다(픽셀 수는 셀 수 있는 값). 서브 640×360 기준 64px = 프레임 높이의 17.8% 로, FN-DET-04 카메라 설치 지침의 "약 18%"와 일치한다 |
| `AlertCommand.level` | **확정됨** — §3 표가 `1 \| 2 \| 3` 만으로 좁혀졌고 §5.2 `severity` 와 같은 열거형을 공유한다. 코드가 이미 `Literal[1,2,3]` 이었다 |
| `table` 첨부의 `rows[][]` | **확정됨** — 셀은 `string` / `number` / `null` 만이다. `Any` 를 버리고 `TableCell = str \| int \| float \| None` 로 좁혔다 |
| `overlay.objects[].violations` · `event_ids` · `nearby` | "없으면 빈 배열"이므로 **필드는 항상 실리는 것**으로 보고 기본값을 주지 않았다 |
| `event_created.zone_id` · `alerted_at` | §5.2 예시에는 값이 있으나 §4.1이 둘 다 nullable 이므로 **필수 + null 허용**으로 두었다 |
| `anomaly.note` · `keyframe_url` | 클라우드 미가용 시 설명이 없을 수 있어(FN-SYS-03) **필수 + null 허용**으로 두었다 |
| 위반 유형별 `severity` (M3 신규) | 명세서가 못박은 것은 **`fall` = 3** 하나이고 §3 예시가 `no_helmet` = 2 다. 나머지 둘(`zone_intrusion` · `proximity`)도 같은 「경고」 급인 **2** 로 두었다. 1(주의)은 위반이 아닌 이상 탐지(FN-AI-04)의 자리이고 이상 탐지는 애초에 경고를 발동하지 않는다 |

---

## M5 보류 항목 (오버레이 시간 정합)

M2 에서 드러났지만 **M5(관제 화면 P0)에서 함께 처리한다.** 지금 손대지 않는다.

| 항목 | 내용 |
|---|---|
| `overlay_buffer_webrtc_ms` = **360** 확정 | 실측 중앙값 358ms, 규격 ±100ms 안이다. **API명세서 §4.5 기본값 300 과 다르며 DB 값이 우선한다** — 코드는 원래 `GET /policies` 로 읽으므로 시드만 바꾸면 된다 |
| `requestVideoFrameCallback` 의 `captureTime` · `rtpTimestamp` 조사 | 브라우저가 **프레임 촬영 시각**을 알려준다면 고정 버퍼 없이 그 시각으로 직접 정합할 수 있다. 지금 남아 있는 지터(260~458ms)의 원인이 고정 버퍼이므로 이것이 되면 문제 자체가 사라진다 |
| marker 모드의 overlay 필터가 더하는 지연 몫 측정 | marker 대조는 영상·좌표를 같은 정의로 만들지만, 필터 체인이 영상 쪽에만 지연을 더한다면 측정값이 그만큼 왜곡된다. 그 몫을 따로 재야 marker 수치를 실제 정합 오차로 읽을 수 있다 |
