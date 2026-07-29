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
| **M3** | 상태머신과 경고 | 확정 · 해소 · 쿨다운 · 소실 유예 · 음성 방송 · 경광등 · 클립 예약 추출 |
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
| FN-DET-12 | 이벤트 후보 생성 및 전송 | P0 | EDGE | 기능 §4.1 · API §2.2 | M2 (sim) / M9 | `sim/edge_sim/` · `sim/cases/` · `edge/rules.py` | ✅ (sim) |

> **주의** — 안전모에는 별도 bbox가 없다. 1단계는 `person`/`vehicle` 2클래스뿐이고
> 안전모는 사람 크롭을 2단계 분류가 판정한다. `helmet` 값은 `on`/`off` 둘뿐이며
> 판정 불가는 **필드 생략**으로 표현한다(`unknown` 클래스 없음).

---

## 4.2 이벤트 처리 (FN-EVT) · 7건

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-EVT-01 | 후보 수신 및 중복 병합 | P0 | SRV | 기능 §4.2 | M2 | `server/app/ws_edge.py` · `server/domain/event_machine.py` | ✅ |
| FN-EVT-02 | 이벤트 확정 판정 (`confirm_duration_s`) | P0 | SRV | 기능 §4.2 | M3 | `server/domain/event_machine.py` | ⬜ |
| FN-EVT-03 | 해소(시정) 판정 (`resolve_duration_s`) | P0 | SRV | 기능 §4.2 | M3 | `server/domain/event_machine.py` | ⬜ |
| FN-EVT-04 | 쿨다운 및 재경고 (`cooldown_s`) | P0 | SRV | 기능 §4.2 | M3 | `server/domain/event_machine.py` | ⬜ |
| FN-EVT-05 | 이벤트 수동 정정 (오탐·강제 종결) | P1 | SRV/WEB | 기능 §4.2 · API §4.1 | M4 | `server/app/routes/events.py` · `front/src/pages/EventsPage.tsx` | ⬜ |
| FN-EVT-06 | 반복 위반 집계 (최근 7일) | P1 | SRV | 기능 §4.2 | M4 | `server/domain/metrics.py` | ⬜ |
| FN-EVT-07 | 트랙 소실 유예 및 재결합 | P0(유예) / P1(재결합) | SRV | 기능 §4.2 · API §2.3 | M3 (유예) / M4 (재결합) | `server/domain/reassociation.py` | ⬜ |

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
| FN-UI-02 | 실시간 관제 — 2채널 라이브 + 오버레이 · **단독 확대 보기** · 수동 방송 | P0 | WEB | 기능 §4.6 · API §5 | M1 (라이브·상태·확대) / M2 (오버레이) / M3 (수동 방송) | `front/src/pages/LivePage.tsx` · `front/src/live/` | 🟡 (수동 방송만 남음) |
| FN-UI-03 | 이벤트 — 목록·필터 + 상세(클립·LLM·규정·타임라인) | P0 | WEB | 기능 §4.6 · API §4.1 | M5 | `front/src/pages/EventsPage.tsx` | ⬜ |
| FN-UI-04 | 영상 검색 — 자연어 질의 · 유사도순 결과 | P1 | WEB | 기능 §4.6 · API §4.3 | M7 | `front/src/pages/SearchPage.tsx` | ⬜ |
| FN-UI-05 | 분석 · 보고서 — 시정률 추이 · 반복 순위 · 히트맵 · 이상 탐지 | P1 | WEB | 기능 §4.6 · API §4.2 | M8 | `front/src/pages/AnalysisPage.tsx` | ⬜ |
| FN-UI-06 | 챗봇 — 통계·검색·브리핑 질의 | P1 | WEB | 기능 §4.6 · API §4.4 | M7 | `front/src/pages/AssistantPage.tsx` | ⬜ |
| FN-UI-07 | 설정 — 구역 그리기 · 캘리브레이션 · 음원 · 임계값 · 시스템 | P1 | WEB | 기능 §4.6 · API §4.5 | M6 | `front/src/pages/SettingsPage.tsx` | ⬜ |

> **오버레이는 도착 즉시 그리지 않는다.** `ts` 기준 지연 버퍼에 담았다가 재생 중인
> 프레임 시각에 맞춰 그린다. 정합 오차 목표 **±100ms**.
> **버퍼는 재생 경로별로 다르다** — `overlay_buffer_webrtc_ms`(400) ·
> `overlay_buffer_hls_ms`(2800). M1 실측 지연이 0.3초 대 2.5초라 단일 값으로는
> 맞출 수 없다. `overlay_stale_ms`(기본 1000ms) 초과 시 박스를 흐리게 표시한다.
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
| FN-SYS-04 | 지표 집계 (시정률 · 평균 시정 시간 · 판정 불가율 · 분포) | P0 | SRV | 기능 §4.8 · API §4.2·§6.7 | M4 | `server/domain/metrics.py` | ⬜ |
| FN-SYS-05 | 판정 불가 집계 (`expired` 별도 집계) | P0 | SRV | 기능 §4.8 · API §6.7 | M4 | `server/domain/metrics.py` | ⬜ |
| FN-SYS-06 | 엣지 메시지 거부 집계 (로깅 · 카운터 · 노출) | P0 | SRV | 기능 §4.8 · API §2.2 | M2 | `server/app/ws_edge.py` · `server/domain/edge_state.py` · `server/app/routes/system.py` | ✅ |

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

### A. 남아 있는 확인 필요

| 내용 | 상세 |
|---|---|
| **§2.2 JSON 예시와 산문이 어긋난다** | 산문은 "후보 메시지 하나에는 위반 유형이 하나만 담긴다"인데, 같은 절의 예시 JSON 과 필드 표는 여전히 `"violations": ["no_helmet", "zone_intrusion"]` · "동시 발생 가능"이다. **값의 규칙을 정하는 산문을 따랐다**(계약에서 길이 1로 제약). 예시와 표도 한 개로 고쳐 달라 |
| **§2.2 `observed_ms` 설명이 없는 필드를 가리킨다** | "이 메시지의 `violation_type` 조건을"이라고 적혀 있는데 `candidate` 에는 `violation_type` 필드가 없다(`violations[]` 뿐이다). 필드명을 `violation_type` 으로 바꿀 것인지, 산문을 `violations[0]` 으로 고칠 것인지 정해 달라. 지금은 **필드명을 표대로 `violations` 로 두고** 길이만 1로 좁혔다 |
| **§5 「오버레이 시간 정합」 4번에 옛 기본값이 남아 있다** | §4.5 정책 표는 `overlay_buffer_webrtc_ms` 를 **300** 으로 고쳤는데, §5 산문은 아직 "기본 400ms"라고 적혀 있다. 코드는 DB 값(§4.5)을 읽으므로 동작에는 영향이 없지만 읽는 사람이 헷갈린다 |
| §4.6 `cloud.quota_used` 의 관측 전 값 | null 규약 표에 `cloud` 는 없다. 하지만 `0.0` 은 "한도를 하나도 쓰지 않았다"는 관측 결과라 아직 아무도 재지 않은 상태와 구분되어야 하므로, `edge.gpu_util 등` 과 같은 취급으로 **nullable 로 넓혔다.** 클라우드는 `available: false` 만으로 충분하다는 판단이면 되돌린다 |

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
