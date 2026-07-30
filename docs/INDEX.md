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
| **M4** | 경고와 클립 | 음성 방송 · 경광등(MQTT) · 긴급 알림 · 수동 방송 · 클립 예약 추출 · 클라우드 격리 |
| **M5** | 관제 화면 P0 | 개요 · 실시간 관제(진행 중 이벤트·수동 방송) · 이벤트 · `tasks.py types` · vitest |
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
| FN-EVT-05 | 이벤트 수동 정정 (오탐·강제 종결) | P1 | SRV/WEB | 기능 §4.2 · API §4.1 | M3 (API) / M5 (화면) | `server/app/routes/events.py` · `front/src/pages/EventsPage.tsx` | ✅ |
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
| FN-ALM-01 | 경고 발동 (사전 녹음 음성 방송) | P0 | SRV | 기능 §4.3 | M4 | `server/infra/audio/` · `server/app/alert_service.py` · `assets/audio/` | ✅ |
| FN-ALM-02 | 경광등 · 부저 제어 (MQTT) | P0 | SRV/MCU | 기능 §4.3 · API §3 | M4 | `server/infra/mqtt/` · `server/domain/mcu_state.py` · `sim/mcu_sim/` | ✅ |
| FN-ALM-03 | 긴급 알림 (쓰러짐 · 관리자 확인) | P1 | SRV/WEB | 기능 §4.3 | M4 (서버) / M5 (화면) | `server/domain/event_machine.py`(`SEVERITY`) · `front/src/live/ActiveEvents.tsx` | ✅ |
| FN-ALM-04 | 수동 방송 송출 | P1 | WEB/SRV | 기능 §4.3 · API §4.5 | M4 (API) / M5 (화면) | `server/app/routes/alerts.py` · `front/src/live/QuickControls.tsx` | ✅ |
| FN-ALM-05 | 경고 일시중지 (정비 작업 등) | P1 | WEB/SRV | 기능 §4.3 · API §4.5 | M4 (API) / M5 (화면) | `server/app/routes/alerts.py` · `front/src/live/QuickControls.tsx` | ✅ |

> **경고 방송은 TTS가 아니다.** 위반 유형별 사전 녹음 wav를 재생한다(생성 지연 제거).
> 확정 → 방송 시작 **1초 이내**가 요구사항이며, **실측 중앙값 43.8ms**다(아래 M4 실측표).
> **이상 탐지(FN-AI-04)는 경고 방송을 발동하지 않는다.**
>
> **상태머신은 소리를 내지 않는다.** `_to_alerted` · `_to_re_alerted` 가 `Effect.alert`
> 에 `AlertIntent`(순수 판단)를 실어 보내고, 집행은 `server/app/alert_service.py` 가 한다.
> 상태 문자열(`status == "alerted"`)로 되짚지 않는 이유는 **재시작 복구처럼 상태만 다시
> 쓰는 경로**에서도 방송이 나가기 때문이다 — 지나간 위반에 뒤늦게 스피커가 울린다.
>
> **방송과 경광등은 서로를 막지 않는다.** 스피커가 죽어도 경광등은 켜지고 그 반대도
> 같다. 소음이 심한 구역에서는 경광등이 유일한 경보이므로, 한쪽 실패로 다른 쪽을
> 건너뛰면 하나 고장이 둘 고장이 된다.

---

## 4.4 기록 · 영상 (FN-REC) · 5건

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-REC-01 | 라이브 재스트리밍 (1080p 메인) | P0 | SRV | 기능 §4.4 | M1 | `server/infra/stream/` · `deploy/mediamtx.yml` · `front/src/live/` | ✅ |
| FN-REC-02 | 7일 링버퍼 녹화 | P0 | REC | 기능 §4.4 · API §4.7 | M1 | `recorder/capture.py` · `recorder/retention.py` | ✅ |
| FN-REC-03 | 이벤트 클립 · 키프레임 추출 | P0 | REC/SRV | 기능 §4.4 · API §4.7 | M1 (REC API) / M4 (예약 실행) | `recorder/clips.py` · `server/infra/clip/service.py` | ✅ |
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
> **예약 큐를 메모리에 두지 않았다.** 예약의 유일한 표현은 DB 의 `clip_status = pending`
> 이고 실행 시각은 `confirmed_at + clip_post_roll_s + margin` 으로 계산된다. 그래서
> **서버가 죽어도 예약이 남고, 재시작 뒤 첫 조회가 곧 복구다** — 복구 코드가 따로 없다.
> `sim/cases/clip_recovery.yaml` 이 이것을 잠근다.
>
> **REC 에 닿지 못한 것은 잡의 실패가 아니다.** `pending` 으로 두어 다음 주기에 다시
> 시도한다. `failed` 로 굳히면 REC 이 살아나도 아무도 다시 부르지 않는다. 반면
> `partial` · `not_found` 는 REC 이 **정상 동작한 결과**이므로 `failed` + 사유 기록이다.

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
| FN-UI-01 | 개요 — 핵심 지표 · 추세 · 분포 · 최근 이벤트 · 시스템 상태 | P0 | WEB | 기능 §4.6 | M5 | `front/src/pages/OverviewPage.tsx` | ✅ |
| FN-UI-02 | 실시간 관제 — 2채널 라이브 + 오버레이 · **단독 확대 보기** · 진행 중 이벤트 · 수동 방송 | P0 | WEB | 기능 §4.6 · API §5 | M1 (라이브·상태·확대) / M2 (오버레이) / M3 (경고 상태) / M5 (우측 패널) | `front/src/pages/LivePage.tsx` · `front/src/live/` | ✅ |
| FN-UI-03 | 이벤트 — 목록·필터 + 상세(클립·LLM·규정·타임라인) | P0 | WEB | 기능 §4.6 · API §4.1 | M5 | `front/src/pages/EventsPage.tsx` | ✅ (LLM·규정·유사사례 칸은 M8) |
| FN-UI-04 | 영상 검색 — 자연어 질의 · 유사도순 결과 | P1 | WEB | 기능 §4.6 · API §4.3 | M7 | `front/src/pages/SearchPage.tsx` | ⬜ |
| FN-UI-05 | 분석 · 보고서 — 시정률 추이 · 반복 순위 · 히트맵 · 이상 탐지 | P1 | WEB | 기능 §4.6 · API §4.2 | M8 | `front/src/pages/AnalysisPage.tsx` | ⬜ |
| FN-UI-06 | 챗봇 — 통계·검색·브리핑 질의 | P1 | WEB | 기능 §4.6 · API §4.4 | M7 | `front/src/pages/AssistantPage.tsx` | ⬜ |
| FN-UI-07 | 설정 — 구역 그리기 · 캘리브레이션 · 음원 · 임계값 · 시스템 | P1 | WEB | 기능 §4.6 · API §4.5 | M6 | `front/src/pages/SettingsPage.tsx` | ⬜ |

> **오버레이는 도착 즉시 그리지 않는다.** `ts` 기준 지연 버퍼에 담았다가 재생 중인
> 프레임 시각에 맞춰 그린다. 정합 오차 목표 **±100ms**.
> **버퍼는 재생 경로별로 다르다** — `overlay_buffer_webrtc_ms` · `overlay_buffer_hls_ms`(2800).
> M1 실측 지연이 0.3초 대 2.5초라 단일 값으로는 맞출 수 없다.
> WebRTC 값은 **300 을 유지한다** — 360 제안과 그 판단 근거는 아래
> 「오버레이 시간 정합 — M5 결과」 ③ 에 있다.
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
| FN-CFG-03 | 경고 음원 매핑 (유형별 음원 + **등급**) | P0 | SRV/WEB | 기능 §4.7 · §6 | M4 (저장소) / M5 (§6 컬럼 반영) / M6 (화면) | `server/infra/db/models.py`(`alert_sounds`) · `server/infra/audio/library.py` · `scripts/seed_sounds.py` | 🟡 (화면만 남음) |
| FN-CFG-04 | 임계값 정책 관리 | P1 | SRV/WEB | 기능 §4.7 · API §4.5 | M6 | `server/app/routes/policies.py` | ⬜ |
| FN-CFG-05 | 위험 반경 설정 (클래스별) | P1 | SRV/WEB | 기능 §4.7 · API §4.5 | M6 | `server/app/routes/vehicle_classes.py` | ⬜ |

---

## 4.8 시스템 (FN-SYS) · 6건

명세서 §4.8 표는 `01 · 02 · 03 · 05 · 06 · 04` 순서로 적혀 있다. 여기서는 ID 순으로 정렬했다.

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-SYS-01 | 구성요소 상태 감시 (엣지·카메라·MCU·클라우드·저장소) | P0 | SRV | 기능 §4.8 · API §4.6 | M1 (카메라·저장소) / M2 (엣지) / M4 (MCU·클라우드) | `server/app/routes/system.py` · `server/domain/edge_state.py` · `mcu_state.py` · `cloud_state.py` | ✅ |
| FN-SYS-02 | 시각 동기화 (NTP · 클립 정합의 전제) | P0 | SRV/EDGE | 기능 §4.8 | M1 (서버) / M2 (엣지 오프셋) | `server/infra/timesync.py` · `edge/` | 🟡 |
| FN-SYS-03 | 클라우드 장애 격리 | P1 | SRV | 기능 §4.8 | M4 (격리·표시) / M7 (실제 어댑터) | `server/domain/cloud_state.py` · `server/tests/test_cloud_isolation.py` | 🟡 (어댑터만 남음) |
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
> `overlay_buffer_webrtc_ms`(300) · `overlay_buffer_hls_ms`(2800). 화면에 어느 경로로
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

~~**프론트 단위 테스트 러너가 없다.**~~ **M5 에서 vitest 를 넣었다.** `overlayBuffer.ts` 의
보간·부호·낡음 판정 10건과 표시 규약(`formatRate` · `metricsAddUp`) 7건이
`uv run tasks.py verify` 안에서 돈다. 그때까지는 스크래치에서 `tsc` 로 컴파일해 node 로
확인했고, 그 검증은 **다음 사람이 반복할 수 없는 것**이었다.

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

## M4 산출물 (경고와 클립)

**이 단계에서 P0 루프가 닫힌다.** 감지 → 확정 → **경고(소리·빛)** → 시정 → 숫자.
M3 까지는 "경고를 발동했다"는 기록만 있었고, 여기서 그 자리에 실제 장치가 붙었다.

| 항목 | 위치 | 근거 | 상태 |
|---|---|---|---|
| 경고 의도(`AlertIntent`) — 상태머신이 내는 순수 판단 | `server/domain/alerts.py` · `event_machine.py` | FN-ALM-01·02 | ✅ |
| 경고 집행 — wav 재생 · MQTT 발행 · 일시중지 · 실측 | `server/app/alert_service.py` | 기능 §4.3 | ✅ |
| 재생 백엔드 (winsound / ffplay·aplay·paplay / none) | `server/infra/audio/player.py` | FN-ALM-01 | ✅ |
| 음원 매핑 (**DB 에서 읽는다** · 경로 탈출 차단) | `server/infra/audio/library.py` · `alert_sounds` 테이블 | FN-CFG-03 · 절대규칙 6 | ✅ |
| 무음 wav 자동 생성 + 매핑 시드 | `scripts/seed_sounds.py` · `assets/audio/` | FN-ALM-01 | ✅ |
| MQTT 클라이언트 (`aegis/alert` 발행 · `device/status` 구독) | `server/infra/mqtt/client.py` | API §3 | ✅ |
| MCU 상태 (신선도 판정 · `GET /system/status` 의 `mcu` 절) | `server/domain/mcu_state.py` | §4.6 · FN-SYS-01 | ✅ |
| 클라우드 가용성 (분석만 중단 · 안전 루프 무관) | `server/domain/cloud_state.py` | FN-SYS-03 | ✅ |
| `POST /alerts/manual` · `/alerts/mute` (204) | `server/app/routes/alerts.py` | §4.5 · FN-ALM-04·05 | ✅ |
| 클립 예약 추출 (예약 큐 = DB · 재시작 복구) | `server/infra/clip/service.py` | FN-REC-03 · 기능 §4.4 | ✅ |
| REC 클라이언트 확장 (`GET /keyframe` · `POST /clips` · 다운로드) | `server/infra/rec_client.py` | §4.7 | ✅ |
| `GET /events/{id}/clip` · `/media/*` 정적 제공 | `server/app/routes/events.py` · `main.py` | §4.1 · §5 경로 규약 | ✅ |
| 마이그레이션 `0004`(`dropped_at`) · `0005`(`alert_sounds`) | `server/infra/db/migrations/` | §6 | ✅ |
| 시나리오 12종 (경고·클립 기대값 포함) + `clip_recovery` · `alert_muted` · `alert_suppressed` | `sim/cases/` · `sim/case_check.py` | — | ✅ |
| 확정 → 방송 지연 실측 도구 | `scripts/measure_alert_latency.py` | FN-ALM-01 | ✅ |

**실측치** (2026-07-30, 개발 노트북 · Windows · winsound · PostgreSQL 실물)

| 항목 | 값 |
|---|---|
| **확정 → 방송 시작** (중앙값) | **43.8 ms** (평균 48.6 · p95 77.6 · 최대 87.6 · 30/30회) |
| 같은 구간, 저장소를 메모리로 두면 | 중앙값 3.4 ms — 차이 약 40ms 가 **DB 쓰기 몫**이다 |
| 요구 (FN-ALM-01) | 1000 ms — **약 23배 여유** |
| 키프레임 1장 추출 (REC · ffmpeg) | **약 5초** ★ 아래 「뒤로 넘긴 이유」 |
| 클립 20초 추출 + 전송 + 저장 | **14.9초** (1080p 15fps 2.5Mbps · 6.6MB) |
| 실제 클립 검증 (`ffprobe`) | h264 1920×1080 15fps · **21.07초** (요청 20초 · 세그먼트 경계로 +1.07초) |
| MQTT 왕복 (발행 → `mcu_sim` 수신) | 4종 전량 수신 · `fall` 만 level 3(연속 부저) |

> **확정 → 방송을 재는 기준점은 `candidate.ts`(관측 시각)다.** 서버 수신 시각을 쓰면
> 네트워크 지연이 예산에서 빠져 실제보다 좋아 보인다. `uv run python -m
> scripts.measure_alert_latency --store db` 로 다시 잴 수 있다.
>
> **키프레임 추출을 뒤로 넘긴 이유** — 실측에서 한 장에 약 5초가 걸렸다(ffmpeg 이
> 세그먼트를 열고 되감아 디코딩한다). 확정 처리 안에서 기다리면 그동안 같은 루프의
> `/ws/edge` 수신이 멈춰 **10초치 프레임이 밀리고, 밀린 만큼 다른 이벤트의 타이머가
> 늦게 흐른다.** 경고는 이보다 먼저 나가므로 1초 예산과는 무관하지만, 그다음 관측들이
> 막히는 것은 시정률에 직접 영향을 준다. 그래서 `asyncio.create_task` 로 넘기고
> 종료 시에만 기다린다(`ClipService.wait_idle`).

**시나리오 12종** (`uv run tasks.py cases`) — M4 가 둘, M5 가 하나를 더했다

| 시나리오 | 무엇을 잠그는가 | 경고 | 클립 |
|---|---|---|---|
| `normal_resolve` | 확정과 같은 순간에 방송 1회 · 예약 → ready | 1건 (level 2) | `ready` |
| `no_resolve` | 쿨다운 30초 뒤 재경고는 `repeat: true` 로 나간다 | 2건 (2번째 repeat) | `ready` |
| `fall_excluded` | **`fall` 은 항상 level 3**, 안전모는 2 | 2건 (3 · 2) | — |
| `dropped` | 확정 전 소멸 — 방송도 예약도 없다 | **0건** | `null` |
| **`alert_muted`** | 일시중지 중 장치가 조용하고 **시정률이 `null`** 이 된다(방송이 없었다) | **0건** | `ready` |
| **`alert_suppressed`** (M5 신규) | 방송 있는 건과 없는 건을 섞어 **분모에서 빠지는지** 잠근다 — 새면 1.00 이 0.50 | 1건 | `ready` |
| **`clip_recovery`** (신규) | `pending` 중 서버 재시작 → 잡이 복구되어 `ready` | 1건 | **`ready`** |

> `expect.alerts` 는 **전량 목록**이다. 기대보다 많이 나가도 실패한다 — 중복 경고는
> 누락만큼이나 현장에서 문제이고, 그것을 막는 것이 쿨다운(FN-EVT-04)이다.
>
> `clip_recovery` 는 `expect.restarts: 1` 로 **재시작이 실제로 일어났는지**까지 잠근다.
> `restart_at` 오타 하나로 평범한 시나리오가 되어 조용히 통과하는 것을 막는다.

**설계 판단 (M4 에서 정한 것)**

| 판단 | 이유 |
|---|---|
| 경고는 `Effect.alert`(순수 판단)로 나가고 집행은 앱 계층이 한다 | 상태 문자열로 되짚으면 **재시작 복구처럼 상태만 다시 쓰는 경로**에서도 방송이 나간다. 지나간 위반에 뒤늦게 스피커가 울리는 것이 그 결과다 |
| `repeat` 을 상태가 아니라 **`alert_count`** 로 정한다 | 재시작 직후 `active` 로 복구된 이벤트가 첫 경고를 내보내는 경로가 있는데, 상태로 판별하면 그 첫 경고가 재경고로 나가 ESP32 가 상습 패턴을 점멸한다 |
| 방송 실패와 경광등 실패가 서로를 막지 않는다 | 소음이 심한 구역에서는 경광등이 유일한 경보다. 한쪽 고장으로 다른 쪽을 건너뛰면 하나 고장이 둘 고장이 된다 |
| 경고 실패로 **상태 전이를 되돌리지 않는다** | 되돌리면 `alerted_at` 이 사라져 시정률의 기준점이 없어진다. 위반이 관측된 것은 사실이므로 기록은 남기고, 실패는 따로 집계·표시한다 |
| 재생기가 없으면 `SilentPlayer` 가 **매번 실패**한다 | 조용히 성공한 척하면 "경고음이 나갔다"는 기록만 남고 아무 소리도 나지 않는다. `AUDIO_BACKEND=none` 은 **명시적으로 선언할 때만** 고른다(절대규칙 9) |
| 음원 매핑을 DB(`alert_sounds`)에 둔다 | 파일명을 코드에 박으면 절대규칙 6 과 FN-CFG-03(화면에서 지정) 둘 다 깨진다. §6 에 없는 테이블이라 「명세서 확인 필요」에 올렸다 |
| 파일명에 경로가 섞이면 거부한다 | 수동 방송의 `sound`(§4.5)는 **바깥에서 온다.** 그것이 경로가 되면 서버 파일 아무거나 열 수 있다 |
| 일시중지에 **기한이 반드시 있다** | 무기한으로 끌 수 있으면 꺼둔 것을 잊는 순간 감시가 조용히 멎는다. 그 상태는 오탐보다 위험하다 |
| 일시중지가 **이벤트·지표를 건드리지 않는다** | 이벤트까지 멈추면 정비 시간 동안의 위반이 통째로 사라져 그 구간에 사고가 나도 기록이 없다. 다만 「방송 후」 시정률 분모에 남는 것이 옳은지는 명세서에 정의가 없어 아래에 올렸다 |
| 수동 방송은 경광등을 **켜지 않는다** | §3 `AlertCommand` 는 `event_id` 와 `ViolationType` 을 필수로 요구하는데 수동 방송에는 둘 다 없다. 없는 값을 지어내면 ESP32 와 대시보드가 존재하지 않는 이벤트를 참조한다 |
| 클립 예약 큐를 **DB 로만** 표현한다 | 메모리 타이머였다면 재시작 순간 진행 중이던 이벤트의 클립이 영원히 `pending` 으로 남는다. DB 질의 하나가 곧 복구라 복구 코드가 따로 없다 |
| REC 미도달은 `pending` 유지, `partial`·`not_found` 는 `failed` | 앞은 **다시 시도할 수 있는 실패**이고 뒤는 원본이 없다는 **사실**이다. 둘을 합치면 REC 이 잠깐 죽은 이벤트가 영영 증거를 갖지 못한다 |
| 키프레임 추출을 뒤로 넘긴다 | 실측 5초/장. 확정 처리 안에서 기다리면 그동안 `/ws/edge` 가 멈춰 다른 이벤트의 타이머가 밀린다 |
| MCU 온라인 판정을 **브로커 연결이 아니라 보고 신선도**로 한다 | 서버가 브로커에 붙어 있어도 ESP32 는 전원이 나갔을 수 있다. `EdgeRuntime` 이 하트비트에 하는 것과 같은 방식이다 |
| 클라우드는 기동 시 `available: false` 다 | "아직 불러본 적 없다"를 "쓸 수 있다"로 낙관하면 분석 결과가 비어 있는 이유가 화면에서 사라진다(§4.6 null 규약) |

**FN-SYS-03 격리를 무엇으로 확인했는가** (`server/tests/test_cloud_isolation.py`)

1. 클라우드가 죽은 상태(`available: false`)에서 `normal_resolve` 시나리오가 확정 →
   방송 → 경광등 → 시정 → 시정률 1.00 까지 끝까지 돈다.
2. 안전 경로(`server/domain` · `alert_service` · `infra/clip`)에 클라우드 클라이언트가
   **하나도 없다** — `server/ai/` 는 비어 있고, 실패는 `GET /system/status` 의 `cloud`
   절과 §5.3 `system` 으로만 나간다.
3. 클라우드 상태가 바뀌어도 같은 응답의 카메라·엣지·저장소 절이 흔들리지 않는다.

---

## M5 산출물 (관제 화면 P0)

**이 단계가 끝나 시연이 가능해졌다.** 감지 → 확정 → 경고 → 시정 → 숫자가 전부
화면으로 나오고, 「방송 후 시정률」이 판정 불가율·방송 없이 확정 건수와 함께 표시된다.

| 항목 | 위치 | 근거 | 상태 |
|---|---|---|---|
| FN-UI-01 개요 — 지표 4개 · 추세 · 분포 · 최근 이벤트 · 시스템 상태 | `front/src/pages/OverviewPage.tsx` · `overview.css` | 기능 §4.6 · 시안 1p | ✅ |
| FN-UI-02 완성 — 진행 중 이벤트 · 빠른 제어(수동 방송 · 일시중지) | `front/src/live/ActiveEvents.tsx` · `QuickControls.tsx` | 기능 §4.6 · 시안 2p | ✅ |
| FN-ALM-03 긴급 알림 — 쓰러짐 최상위 등급 + **관리자 확인** | `front/src/live/ActiveEvents.tsx` | 기능 §4.3 | ✅ |
| FN-UI-03 이벤트 — 목록·필터·상세(클립 · 타임라인 · note · `clip_status`) | `front/src/pages/EventsPage.tsx` · `events.css` | 기능 §4.6 · API §4.1 · 시안 3p | ✅ |
| FN-EVT-05 수동 정정 화면 — 메모 · 강제 종결 · 오탐 표시 | `front/src/pages/EventsPage.tsx` | §4.1 `PATCH` | ✅ |
| **`uv run tasks.py types`** — Pydantic → JSON Schema → TS (모델 83종) | `scripts/gen_types.py` · `front/src/types/contracts.ts` | 절대규칙 5 | ✅ |
| **vitest** — `overlayBuffer` 10건 · 표시 규약 7건 · `verify` 에 포함 | `front/src/**/*.test.ts` · `front/vite.config.ts` | — | ✅ |
| 계약 열거형 → 화면 표기 한 곳 (부록 B 대조표) | `front/src/types/labels.ts` | 부록 B | ✅ |
| REST 클라이언트 (§1.4 오류 봉투를 문장으로) | `front/src/api/client.ts` · `events.ts` · `metrics.ts` · `alerts.ts` | §1.4 · §4.1 · §4.2 · §4.5 | ✅ |
| 명세서 갱신 반영 — `alert_sounds` 재정의 · `alert_suppressed` · `clip_error` · 정책 키 2개 · mute 응답 · `notify_device` | 아래 「명세서 갱신 반영 (v11)」 | §4.5 · §4.8 · §6 | ✅ |
| 키프레임·클립 추출 성능 | `recorder/clips.py` | — | ✅ |

**실측치** (2026-07-30 · 개발 노트북 · Windows · ffmpeg 8.1.2)

| 항목 | 고치기 전 | 고친 뒤 |
|---|---|---|
| **키프레임 1장 추출** (중앙값) | **593 ms** | **390 ms** (−34%) |
| 그중 제거한 ffprobe 몫 | 175~208 ms | 0 (호출하지 않는다) |
| 클립 20초 추출 — 세그먼트 길이 측정 3회 | 533 ms (순차) | **342 ms** (동시) |
| 클립 20초 추출 전체 | 1352 ms | **1228 ms** (−9%) |
| ffmpeg 프로세스 기동만 (`ffmpeg -version`) | — | **140~190 ms** ← 남은 시간의 하한 |

> **`-ss` 위치는 원래 맞았다.** 보고받은 진단(「`-ss` 를 `-i` 뒤에 두면 느리다」)은 사실이지만
> **이 코드에 해당하지 않았다** — `extract_keyframe` 과 `_cut` 은 처음부터 `-ss` 를 `-i`
> 앞에 두고 있었고 그 이유가 주석에도 적혀 있었다. 확인 삼아 출력 seek 을 재보니
> 5초 지점 735ms · 9.5초 지점 1119ms 로 **오프셋에 비례해 느려졌고**, 입력 seek 은
> 오프셋과 무관하게 480~690ms 였다. 즉 그 함정은 이미 피해 있었다.
>
> **실제로 낭비되고 있던 것은 ffprobe 한 번이었다.** 오프셋을 파일 끝 안쪽으로 자르려고
> 세그먼트 길이를 재고 있었는데, 그 경계는 **이웃 세그먼트의 시작 시각**으로 알 수 있다
> (`select_overlapping` 이 이미 그 규칙을 쓴다). 프로세스 하나가 175~208ms 였으므로
> 그것만 없애 590ms → 390ms 가 됐다.
>
> **남은 390ms 는 더 깎을 수 없다.** 그중 140~190ms 가 ffmpeg 프로세스 기동이고
> (`ffmpeg -version` 실측) 나머지가 mp4 열기 · GOP(2초 · 30프레임) 디코딩 · 1920×1080
> JPEG 인코딩이다. **「수십 ms」는 자식 프로세스로 ffmpeg 을 부르는 구조에서 도달할 수
> 없다** — 그 값을 원하면 인프로세스 디코더(PyAV 등)를 들여야 하고, 그것은 REC 의
> 의존성과 젯슨 이식 범위를 바꾸는 결정이라 여기서 임의로 하지 않았다.
>
> 클립 쪽은 **길이 측정을 추정으로 바꾸지 않았다.** 그 값이 곧 절단 위치이고,
> `actual_from` 은 계산이 아니라 실측이어야 한다(§4.7). 대신 세 번의 ffprobe 를
> **동시에** 돌려 533ms → 342ms 로 줄였다. 남은 시간은 ffmpeg 3패스 + ffprobe 1회,
> 즉 프로세스 4개의 기동 비용이며 3패스 구조는 `actual_from` 을 실측으로 얻기 위한 것이다.
>
> **빈 출력을 성공으로 넘기지 않는다.** `-ss` 가 실제 파일 끝을 넘으면 ffmpeg 은
> **0바이트를 내고 종료코드 0** 으로 끝난다. 그대로 돌려주면 "키프레임을 저장했다"는
> 기록만 남고 그림이 없으므로 오류로 올린다(`recorder/tests/test_clips.py` 가 잠근다).

**M5 가 고른 것 (설계 판단)**

| 판단 | 이유 |
|---|---|
| **위험 등급(`level`)의 원천을 DB 로 옮겼다** | §6 이 `alert_sounds.level` 을 정의하면서 "관리자가 유형별 음원과 **등급**을 바꿀 수 있다"고 적었다. 코드에 박힌 `SEVERITY` 표는 절대규칙 6 위반이 된다. 상태머신은 순수성을 지키려 값을 **주입받고**(`set_severity`), `SEVERITY` 는 DB 를 못 읽었을 때의 대비값으로 남는다 — 등급을 모른다고 경고를 못 내보내면 DB 장애가 안전 기능 정지로 번진다 |
| 등급을 **상태머신 한 곳에서만** 갈아끼운다 | §5.2 `severity` 와 §3 `AlertCommand.level` 은 같은 값이어야 한다. 집행 계층에서 따로 덮으면 ESP32 가 받은 등급과 화면에 뜬 등급이 갈리고, 어느 쪽이 맞는지 사후에 알 수 없다 |
| `AlertSink.fire` 가 **`bool` 을 돌려준다** | 일시중지로 조용했다는 사실이 호출자에게 돌아가지 않으면 `alert_suppressed` 를 기록할 방법이 없다. **재생 실패는 `True` 다** — "사람이 일부러 멈췄다"와 "내보내려 했으나 고장났다"는 다르고, 후자를 지표에서 빼면 장애가 시정률을 좋아 보이게 만든다 |
| 일시중지 창을 `dict[int \| None, ...]` 로 둔다 | §4.5 의 「`cam_id` 생략 = 전체 카메라」를 표현하는 자리다. `0` 이나 `-1` 같은 가짜 번호를 만들면 실제 카메라 번호와 섞여 **엉뚱한 카메라의 경고가 조용히 멎는다.** 조회는 카메라별 창과 전체 창을 **둘 다** 본다 — 하나만 보면 "이 카메라는 안 멈췄다"고 잘못 표시한다 |
| `minutes` 생략 시 정책 기본값을 **올림**한다 | `mute_default_duration_s` 가 30초처럼 1분 미만이면 내림하면 0이 되어 「즉시 해제」로 뒤집힌다. 중지를 요청했는데 켜지는 것이 가장 나쁜 결과다 |
| 타입 생성물을 **`serialization` 모드**로 뽑고 `?` 를 붙이지 않는다 | `validation` 모드는 기본값이 있는 필드를 옵셔널로 낸다. 그러면 `Policies.overlay_stale_ms` 가 `number \| undefined` 가 되어 프론트가 `?? 1000` 로 값을 메우게 되고, 그것이 절대규칙 6 이 금지하는 것이다. nullable 은 `\| null` 로 그대로 구분된다. 대가로 요청 모델도 전부 필수가 되지만 그쪽은 `Partial<>` 로 좁히면 된다 |
| 생성 대상을 **계약이 내보내는 SpecModel 전량**으로 한다 | 화면이 쓰는 것만 고르면 다음 화면을 만들 때 무엇이 빠졌는지 아무도 모르고, 손으로 옮기는 관행이 되살아난다 |
| 추세·분포를 **최근 이벤트로 계산**한다 | `GET /metrics/timeseries` · `/distribution` 은 M8 이다. 없는 API 를 흉내 내 곡선을 그리면 **시연에서 사실처럼 보인다.** 표본으로 그렸다는 것을 화면에 적었다 |
| 개요가 `metric`(§5.3)을 받으면 **다시 조회한다** | §5.3 페이로드는 §4.2 의 부분집합이라 `suppressed` 가 없다. 메시지 값만으로 갱신하면 「방송 없이 확정」이 낡은 채 남는데, 그 숫자는 **분모가 왜 줄었는지**를 설명하는 값이므로 시정률과 함께 움직여야 한다 |
| 이벤트 상세가 `clip_status` 로 재생 여부를 정한다 | `pending` 인 동안 `<video>` 를 붙이면 조용히 재생에 실패한다(§4.1 은 그 상황에 404 를 준다). 키프레임으로 대체하고 **왜 아직 없는지**를 적는다 |
| M8 칸(LLM · 유사 사례 · 규정)을 **비워 두되 이유를 적는다** | 빈 칸은 "아직 그 기능이 없다"와 "생성에 실패했다"를 구분하지 못한다(§4.6 null 규약) |
| 클립 링크로 `/events/{id}/clip` 을 쓴다 | `/media/clips/...` 정적 경로로 직접 붙으면 `pending` 과 「파일 없음」이 같아 보인다. 서버 경로는 **없는 것을 없다고** 404 로 말해준다 |

**화면에서 확인한 것** (실제 서버 · PostgreSQL · REC · 가짜 카메라 2대)

| 확인 | 결과 |
|---|---|
| 개요 지표 4개 · 시정률 병기 | `100% / 판정 불가 0%` · `방송 없이 확정 1건` |
| 일시중지 중 확정 → 지표 | `correction_rate` 1.00 유지 · `suppressed` 1 · `total_violations` 1 (섞였다면 0.50) |
| 이벤트 상세에서 **클립 재생** | `readyState 4` · 20.07초 · 1920×1080 · 8.5초 지점 디코딩 픽셀 14400/14400 비검정 |
| `POST`/`GET /alerts/mute` | 15분 · 정책 기본값(900초 → 15분) · `cam_id` 생략(전체) · `minutes:0` 해제 전부 왕복 |
| 빠른 제어 UI 로 일시중지 | 배너에 `14분 31초 남음 · 정비 작업` 표시 · 서버 상태와 일치 |
| 레이아웃 | 사이드바 232px · 지표 타일 4×274px 균등 · 2열(711/418) · 가로 스크롤 없음 |

> **스크린샷은 남기지 못했다.** 이 환경의 브라우저 창이 화면에 표시되지 않아 프레임을
> 합성하지 않는다(캡처 시도가 타임아웃). 위 값들은 DOM·계산 스타일·`getBoundingClientRect`
> 와 실제 비디오 디코딩 픽셀로 확인한 것이다.

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

**v10 (직전에 보고한 4건 + 2건 전량)** — 전부 코드에 반영했다.

| 항목 | 확정된 내용 | 반영 |
|---|---|---|
| **§4.8 시정률 식** | `resolved / (resolved + resolved_late + unresolved)` 로 갱신 — §6.7 과 일치. **§6.7 을 따른 기존 판단이 맞았다** | 코드 변경 없음. `test_spec_v10.py` 가 세 절의 식이 같다는 것을 잠근다 |
| **§4.2 판정 불가율 분모** | `resolved_late` **포함**으로 확정. 근거 명시 — 늦은 시정은 모집단이지 판정 불가가 아니다 | 코드 변경 없음(이미 §6.7 을 따랐다) + 회귀 테스트 |
| **§4.2 · §5.3 예시의 `total_violations`** | **24** 로 정정(네 버킷 합) | 명세서 예시 회귀 테스트를 24 로 갱신하고, **예시 안에서 산술이 성립하는지**를 새 테스트가 검산한다 |
| **§5.3 `metric` 에 `resolved_late`** | 추가됨 | `MetricMsg.resolved_late` · `_publish_metric` · `front/src/types/system.ts`. 화면이 받은 숫자만으로 시정률을 검산할 수 있게 됐다 |
| **§4.1 `GET /events/{id}` 의 `last_alerted_at` · `note`** | 응답에 추가됨 — **저장만 되고 못 읽던 상태가 끝났다** | `EventSummary` 에 필수(nullable) 추가 · 저장소가 채운다 · 오탐 사유가 화면(FN-UI-03)까지 도달한다. **재시작 복구가 저장된 `last_alerted_at` 을 쓰게 되어**, 재경고를 여러 번 한 이벤트가 복구 직후 즉시 재경고하던 문제도 함께 사라졌다 |
| **§6 `events.dropped_at`** | 추가됨 | 마이그레이션 `0004` · `_to_dropped` 가 시각을 찍고 §4.1 `timeline` 에 `dropped` 가 나온다. 종결 시각 셋(`resolved`·`expired`·`dropped`)이 모두 생겼다 |

**v11 (M4 에서 보고한 7건 전량)** — 전부 코드에 반영했다.

| 항목 | 확정된 내용 | 반영 |
|---|---|---|
| **`alert_sounds` 테이블** ★ | §6 에 실렸고 컬럼이 확정됐다 — `violation_type` · `file_path` · `level`(1/2/3) · `label` · `active`. 서버가 임시로 만든 `key`·`filename` 과 다르다 | 마이그레이션 `0006` 이 **테이블을 옮긴다**(새로 만들지 않는다 — 현장에서 바꿔 둔 매핑을 지우면 FN-CFG-03 이 깨진다). `level`·`label` 은 시드 기본값으로 백필했고 `fall` 만 3이다. `test_db_schema.py` 의 `EXTRA_TABLES` 가 **비었다** |
| **`level` 의 원천** | §6 이 "관리자가 유형별 음원과 **등급**을 바꿀 수 있다"고 명시 | `EventMachine.set_severity()` 로 주입한다. `SEVERITY` 표는 DB 미도달 시 대비값으로만 남는다(절대규칙 6 · 2 를 동시에 지키는 유일한 형태) |
| **일시중지 중 확정 이벤트와 시정률** ★ | §4.8 이 **전량 제외 + `suppressed` 별도 집계**로 확정. 「방송 후」 시정률이므로 알린 적 없는 건은 모집단이 아니다 | `events.alert_suppressed`(마이그레이션 `0006`) · `AlertSink.fire` 가 `bool` 반환 · `metrics.summarize` 가 제외하고 센다 · `sim/cases/alert_suppressed.yaml` 이 **1.00 이 0.50 으로 새는지** 잠근다 |
| **`clip_error` 컬럼** | §6 에 추가됨 | `note` 의 `[클립]` 접두사 임시 처리를 없앴다. 관리자 메모와 기계가 남긴 사유가 더 이상 한 칸을 쓰지 않는다 |
| **정책 키 2개** | `mute_default_duration_s`(900) · `clip_extract_margin_s`(2) | 서버 설정(`CLIP_MARGIN_S`)에서 정책으로 옮겼다. `ClipService.set_policies` 가 margin 까지 DB 값으로 갈아끼운다 |
| **mute 응답과 조회** | `cam_id` · `muted` · `muted_until` · `reason`. `GET /alerts/mute` 도 같은 형태. `minutes:0` 은 즉시 해제, `cam_id` 생략은 전체 카메라 | 204 를 버렸다 — 새로고침 뒤에도 "경고가 꺼져 있다"가 화면에 남는다. `minutes` 생략 시 정책 기본값이 붙어 **기한 없는 중지를 만들 수 없다** |
| **`notify_device`** | `POST /alerts/manual` 에 추가(기본 `true`). 참이면 `level` 로 MQTT 도 발행 | 수동 방송이 경광등을 켠다. `AlertCommand` 가 요구하는 두 값은 `MANUAL-cam{N}-{ISO}` 와 `zone_intrusion` 으로 채우고 그 사실을 아래에 올렸다 |

### A. 남아 있는 확인 필요

M5 에서 새로 드러난 것들이다. 전부 **명세서가 요구하는 기능을 구현하려는데 둘 자리가
없어서** 서버가 임시로 정한 것이며, 코드에는 그 사실을 주석으로 표시해 두었다.

| 내용 | 상세 |
|---|---|
| **§4.2 응답 예시에 `suppressed` 가 없다** ★ | 기능명세서 §4.8 은 「`suppressed` 로 별도 집계」를 요구하는데 API명세서 §4.2 `GET /metrics/summary` 예시 JSON 과 필드 표에는 그 칸이 없다. 예시에 없다는 이유로 계약에서 빼면 지표가 자기 정의를 못 지키므로 **응답에 두었다**. `packages/contracts/tests/test_spec_examples.py` 의 `SUMMARY_FIELDS_BEYOND_EXAMPLE` 한 곳에만 그 차이가 적혀 있다. §4.2 에 추가해 달라 |
| **§5.3 `metric` 에도 `suppressed` 가 없다** | 같은 이유다. 지금은 화면이 `metric` 을 받으면 `GET /metrics/summary` 를 **다시 조회**해 그 칸을 채운다(종결 전이당 요청 한 번). §5.3 에 추가되면 재조회를 없앨 수 있다 |
| **§4.1 응답에 `clip_status` · `clip_error` · `alert_suppressed` 자리가 없다** ★ | 셋 다 §6 `events` 컬럼인데 §4.1 목록·상세 예시에는 없다. **다시 읽을 수 없으면 화면이 그릴 수 없는** 값들이라 `EventDetail` 에 두었다 — `clip_status` 없이는 클립 재생 여부를 정할 수 없고(§5.2 `event_updated` 는 그 순간 보고 있던 사람만 받는다), `alert_suppressed` 없이는 "왜 이 이벤트가 지표에 없나"를 설명할 수 없다. §4.1 에 추가할지 정해 달라 |
| **수동 방송의 `type` 을 §3 에 정의할 자리가 없다** | `notify_device` 가 생겨 수동 방송도 MQTT 를 발행하는데, §3 `AlertCommand.type` 은 `ViolationType` 이고 수동 방송에는 위반 유형이 없다. ESP32 가 이 값으로 **점멸 패턴을 고르므로** 아무 것이나 될 수 없어 지금은 `zone_intrusion`(「지금 그 구역을 주목하라」에 가장 가까운 일반 경보)을 쓴다. `event_id` 는 `MANUAL-cam{N}-{ISO8601}` 로 두어 조회 가능한 이벤트처럼 보이지 않게 했다. §3 에 「수동 방송」 경우를 정의해 달라 |
| **`AlertCommand.duration_s` 에 대응하는 정책 키가 없다** | §3 이 경광등·부저 지속 시간을 요구하는데 §4.5 `GET /policies` 목록에 그 키가 없다. **장치 쪽 운용값**이라 상태머신 타이머와 성격이 다르다고 보아 서버 설정(`ALERT_DURATION_S`, 기본 5)에 두었다. `clip_extract_margin_s` 가 이번에 정책으로 올라갔으니 이것도 함께 정해 달라 |
| **`alert_sounds.level` 과 §5.2 `severity` 의 우선순위** | 등급의 원천을 DB 로 옮겼으므로 관리자가 `no_helmet` 을 3으로 올리면 §5.2 `severity` 와 §3 `level` 이 함께 3이 된다. 그런데 §3 은 「**`fall` 은 항상 3**」을 못박았다 — 관리자가 `fall` 을 2로 **내리는** 것을 서버가 막아야 하는지가 정의되지 않았다. 지금은 막지 않는다(DB 값을 그대로 쓴다). 하한을 강제해야 하면 알려 달라 |
| **`alert_sounds.label` 을 읽을 API 가 없다** | §6 이 표시 이름을 정의했지만 그것을 내보내는 엔드포인트가 §4.5 에 없다. FN-CFG-03 화면(M6)이 필요하므로 그때 `GET /alert-sounds` 같은 것을 정의해 달라. **M5 는 그것 없이 만들었다** — 수동 방송이 고를 수 있는 것은 위반 유형 넷(값 자체가 절대규칙 11 로 고정)과 「기본 안내」(`sound` 생략)뿐이라 파일명이 프론트에 없다 |

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

## 오버레이 시간 정합 — M5 결과

M2 에서 드러나 M5 로 넘긴 세 항목이다. **둘은 닫혔고 하나는 측정 수단만 만들었다.**

### ① marker 모드의 overlay 필터가 더하는 지연 — **닫힘**

| 항목 | 값 |
|---|---|
| 기본 체인 (`scale,fps,realtime제외,setpts,drawtext`) · 450프레임 | 프레임당 **4.01 ms** |
| marker 체인 (위 + `overlay=eval=frame`) | 프레임당 **3.88 ms** |
| **짝 차이 중앙값** (같은 회차 안에서 번갈아 측정) | **프레임당 0.29 ms** (범위 −1.2 ~ +2.5) |
| 같은 체인 회차 간 흔들림 | 프레임당 0.93 ms |
| 15fps 프레임 간격(66.7 ms) 대비 | **0.43%** |

`overlay` 는 **상태 없는 프레임 단위 필터**다 — 2차 입력이 1프레임(`repeatlast=1`)이고
재정렬·버퍼링이 없다. 따라서 이 필터가 더하는 **지연 = 프레임당 처리 시간**이며, 그 값이
프레임 간격의 0.5% 미만이고 측정 노이즈(0.93 ms)와 구분되지 않는다.

> **결론: marker 대조 수치를 그대로 정합 오차로 읽어도 된다.** 필터가 더하는 몫은
> ±100ms 목표의 100분의 1 이하다. 측정은 CPU 가 한가할 때(가짜 카메라 정지) 한 것이며,
> 개발 스택이 다 떠 있는 상태에서는 노이즈가 3.4 ms/프레임까지 커져 **차이를 분리할 수
> 없었다** — marker 실측은 다른 프로세스를 내린 뒤에 해야 한다.

### ② `requestVideoFrameCallback` 의 `captureTime` · `rtpTimestamp` — **측정 수단만**

**정합 방식을 바꾸지 않았다.** 이 환경에서 필드 존재 여부를 확인할 수 없었기 때문이다.

* 이 레포에 딸린 브라우저 창은 **화면에 표시되지 않아 프레임을 합성하지 않는다** —
  `requestVideoFrameCallback` 이 아예 불리지 않는다(3초 대기 후 타임아웃).
* 실제 Chrome 은 `127.0.0.1:5173` 에 `ERR_CONNECTION_REFUSED` 로 닿지 못했다
  (같은 기계에서 `curl` 은 200 을 받는다).

대신 **`/live?debug=1` 정합 진단에 세 줄을 추가**했다. 실제 브라우저로 열면 한눈에 답이 나온다.

| 표시 | 읽는 법 |
|---|---|
| `촬영 시각(rVFC)` | 값이 뜨면 `captureTime` 이 실려 온다. `없음 — 고정 버퍼 사용` 이면 이 경로가 없다 |
| `실제 영상 지연` | `표시 시각 − 촬영 시각`. **적용 버퍼와 100ms 이상 다르면 붉게 표시된다** |
| `rtpTimestamp` | 있으면 함께 표시. 벽시계가 아니라 클럭레이트 카운터라 단독으로는 쓸 수 없다 |

**바꾸지 않은 이유** (측정 없이 채택하면 더 나빠질 수 있다): `captureTime` 은 WebRTC
경로에서 **송신 측이 `abs-capture-time` RTP 확장을 실어 보낼 때만** 채워진다. mediamtx 가
그것을 넣는지 확인되지 않았고, 넣더라도 그 값이 **카메라 센서 시각인지 mediamtx 수신
시각인지**에 따라 의미가 정반대다 — 후자라면 영상 지연의 대부분인 카메라→mediamtx
0.27초가 빠져 **고정 버퍼보다 나빠진다.** 「실제 영상 지연」 줄이 0에 가까우면 센서
시각이고, 250~300ms 대면 중간 지점이다. 그 숫자를 보고 정하면 된다.

### ③ `overlay_buffer_webrtc_ms` 기본값 제안 — **제안만** (명세서는 고치지 않았다)

| 값 | 출처 |
|---|---|
| **300** | API명세서 §4.5 · `Policies` 기본값 · DB 시드 (현재 동작하는 값) |
| **360** | M2 실측 중앙값 358ms 를 반영한 M5 제안값 |
| 실측 영상 지연 (M1 · WebRTC) | 0.27 ~ 0.34초 (중앙값 약 305ms) |

**제안: 300 을 유지하고, ②의 「실제 영상 지연」을 재고 나서 한 번에 정한다.**

근거 — 300 과 360 의 차이 60ms 는 ±100ms 규격 **안에 있어** 어느 쪽도 규격을 벗어나지
않는다. 반면 값을 옮기는 비용은 작지 않다.

* `Policies` 기본값을 360 으로 바꾸면 **명세서 §4.5 와 갈린다.** 그 기본값은
  `test_spec_examples.py` 가 명세서 예시와 한 글자까지 대조하는 값이다.
* 시드만 360 으로 바꾸면 `scripts/seed_policies.py` 가 계약 기본값에서 파생된다는 규약이
  깨진다 — 두 곳이 갈리는 순간 "지금 DB 에 뭐가 들어 있나"를 코드로 알 수 없게 된다.
* 그리고 **360 의 근거인 358ms 자체가 고정 버퍼 기반 추정치다.** ②가 `captureTime` 을
  주면 그 값이 곧 정답이 되므로, 지금 60ms 를 옮기는 것은 곧 다시 바꿀 값을 두 곳에
  퍼뜨리는 일이다.

바꾸기로 정한다면 손댈 곳은 **두 곳**이다 — `packages/contracts/.../policies.py` 의 기본값과
`packages/contracts/tests/test_spec_examples.py` 의 `POLICIES_EXAMPLE`. 그리고 그 전에
**API명세서 §4.5 를 360 으로 갱신**해야 한다(코드가 명세서를 앞서갈 수 없다 · 절대규칙 8).
