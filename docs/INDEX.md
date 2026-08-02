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
| **M6** | 설정과 좌표계 | 캘리브레이션 · 구역 편집 · 음원 매핑 · 정책 · `packages/vision` 순수 계산 |
| **M7** | P1 감지 정밀화 | 근접·마스크 최근접·쓰러짐 3조건·뎁스 온디맨드 · 합성 마스크 · 반복 위반 |
| **M8** | 지능·분석 | 임베딩 · 장면 검색 · LLM 분석 · 규정 매핑 · 챗봇 · 브리핑 · 분석 화면 · 이상 탐지 — **P1 완료** |
| **M9** | 엣지 실물 이식 | 시뮬레이터를 실물 Jetson 러너로 교체 |

> **M7 이 「지능 기능」에서 「P1 감지 정밀화」로 바뀌었다.** 감지 판정이 시뮬레이터가
> 실어 보내는 값에 머물러 있는 채로 지능 기능을 얹으면, LLM 이 읽는 맥락(`nearby` ·
> `posture`)이 전부 사람이 손으로 적은 값이 된다. 지능·분석은 M8 로 합쳤고
> **M9(엣지 실물 이식)는 그대로**다 — 코드 곳곳의 "M9 에서 교체한다" 주석이 가리키는
> 번호이므로 옮기지 않았다.

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
| FN-DET-06 | 접지점 산출 및 실좌표 변환 | P0 | EDGE | 기능 §4.1 · API §6.1·6.2 | M6 (로직) / M9 (엣지) | `packages/vision/footpoint.py` · `homography.py` · `sim/edge_sim/scripted.py` | ✅ (로직·sim) |
| FN-DET-07 | 금지구역 침입 판정 (히스테리시스) | P0 | EDGE | 기능 §4.1 | M6 / M9 | `packages/vision/zones.py` · `sim/tests/test_coordinates.py` | ✅ (로직) |
| FN-DET-08 | 지게차 근접 판정 | P1 | EDGE | 기능 §4.1 | M7 / M9 | `packages/vision/distance.py`(`proximity_candidate`) · `sim/edge_sim/derive.py` | ✅ (로직·sim) |
| FN-DET-09 | 마스크 기반 최근접 거리 | P1 | EDGE | 기능 §4.1 · API §6.5 | M7 / M9 | `packages/vision/distance.py` · `sim/edge_sim/masks.py` · `sim/cases/mask_vs_center.yaml` | ✅ (로직·sim) |
| FN-DET-10 | 쓰러짐 판정 (3조건 동시 충족) | P1 | EDGE | 기능 §4.1 · API §6.4 | M7 / M9 | `packages/vision/posture.py` · `sim/tests/test_masks.py` | ✅ (로직·sim) |
| FN-DET-11 | 뎁스 온디맨드 검증 | P1 | EDGE | 기능 §4.1 · API §6.6 | M7 (트리거·캐시) / M9 (모델) | `packages/vision/depth.py` · `edge/depth.py` | 🟡 (모델만 남음) |
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
| FN-REC-03 | 이벤트 클립 · 키프레임 추출 (스냅샷 버퍼) | P0 | REC/SRV | 기능 §4.4 · API §4.7 | M1 (REC API) / M4 (예약 실행) / M6 (타이밍·버퍼) | `recorder/clips.py` · `recorder/snapshots.py` · `server/infra/clip/service.py` | ✅ |
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
> 이고 실행 시각은 `confirmed_at + clip_post_roll_s + rec_segment_seconds +
> clip_extract_margin_s` 로 계산된다. 그래서
> **서버가 죽어도 예약이 남고, 재시작 뒤 첫 조회가 곧 복구다** — 복구 코드가 따로 없다.
> `sim/cases/clip_recovery.yaml` 이 이것을 잠근다.
>
> **REC 에 닿지 못한 것은 잡의 실패가 아니다.** `pending` 으로 두어 다음 주기에 다시
> 시도한다. `failed` 로 굳히면 REC 이 살아나도 아무도 다시 부르지 않는다. 반면
> `partial` · `not_found` 는 REC 이 **정상 동작한 결과**이므로 `failed` + 사유 기록이다.

> **클립은 확정 즉시 추출하지 않는다.** 확정 순간에는 사후 구간이 아직 녹화되지 않았다.
> `confirmed_at + clip_post_roll_s + rec_segment_seconds + clip_extract_margin_s` 시점에
> 예약 실행하고, 그동안 `clip_status = pending` 으로 노출한다.
> **세그먼트 길이는 REC 의 `GET /status` 에서 읽는다** — 서버에 상수로 두면 REC 설정을
> 바꿨을 때 아직 열려 있는 파일을 잘라 뒤가 빈 클립이 `ready` 로 굳는다(M6 에서 반영).
> 서버 재시작 시 `pending` 잡은 DB에서 복구해 재실행한다.
>
> **키프레임은 세그먼트가 아니라 REC 의 메모리 스냅샷 버퍼에서 나온다**(초당 1장 · 최근
> 60초 · §4.4). 확정 순간의 프레임은 아직 어떤 파일에도 없어서, 세그먼트만 보던 시절에는
> 그 요청이 500 이었고 이벤트 상세 화면에 보여줄 그림이 없었다.

---

## 4.5 지능 기능 (FN-AI) · 10건

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-AI-01 | 이벤트 키프레임 임베딩 (halfvec 3072) | P1 | SRV/CLD | 기능 §4.5 | M8 | `server/ai/service.py` · `gemini.py` · `repository.save_embedding` | ✅ |
| FN-AI-02 | 자연어 장면 검색 (하이브리드) | P1 | SRV/CLD | 기능 §4.5 · API §4.3 | M8 | `server/ai/search.py` · `server/app/routes/search.py` | ✅ |
| FN-AI-03 | 반복 위반 시각적 클러스터링 | P2 | SRV | 기능 §4.5 | M8 | `server/ai/cluster.py` | 보류 |
| FN-AI-04 | 정상 풀 축적 및 이상 탐지 | P2 | SRV/CLD | 기능 §4.5 · API §6.8 | M8 | `server/ai/vectors.py` · `service.sample_once` | ✅ |
| FN-AI-05 | LLM 심층 분석 생성 (LangGraph) | P1 | SRV/CLD | 기능 §4.5 | M8 | `server/ai/graph.py` | ✅ |
| FN-AI-06 | 규정 매핑 (사전 구축 테이블) | P1 | SRV | 기능 §4.5 | M8 | `server/ai/regulations.py` · `assets/seeds/regulations.yaml` | ✅ |
| FN-AI-07 | 유사 사고사례 매칭 | P2 | SRV/CLD | 기능 §4.5 | M8 | `server/ai/incidents.py` · `assets/seeds/incidents.yaml` | ✅ |
| FN-AI-08 | 챗봇 질의 라우팅 (sql·vector·vision) | P1 | SRV/CLD | 기능 §4.5 · API §4.4 | M8 | `server/ai/assistant.py` · `routes/assistant.py` | ✅ |
| FN-AI-09 | 실시간 현장 브리핑 | P1 | SRV/CLD | 기능 §4.5 · API §4.4 | M8 | `server/ai/service.briefing` | ✅ |
| FN-AI-10 | 주간 보고서 생성 | P2 | SRV/CLD | 기능 §4.5 · API §4.4 | M8 | `server/ai/service.start_weekly_report` | ✅ |

> **클라우드가 죽어도 안전 기능은 무영향이어야 한다**(FN-SYS-03).
> 규정 조항은 **LLM이 생성하지 않는다** — 사전 매핑 테이블로 결정적으로 연결한다.
>
> **M8 실측**: 어댑터가 붙어 있고 호출마다 2초 뒤 실패하는 상태에서 후보 → 확정·경고가
> **1.0ms**, 확정 → 해소가 **2.4ms** 였다. 분석은 배경 태스크이고 `EventService` 가
> 그것을 기다리지 않는다(아래 「M8 산출물」).
>
> **FN-AI-03(시각적 클러스터링)만 보류로 남았다.** P2 이고, 반복 위반 집계는
> `GET /metrics/repeat`(FN-EVT-06 · 구역·카메라·추적 축)로 이미 화면에 나온다 —
> 시각적 클러스터링은 그 위에 얹는 것이라 없어도 반복 위반을 못 보는 상태가 아니다.

---

## 4.6 관제 화면 (FN-UI) · 7건

| FN-ID | 화면 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-UI-01 | 개요 — 핵심 지표 · 추세 · 분포 · 최근 이벤트 · 시스템 상태 | P0 | WEB | 기능 §4.6 | M5 | `front/src/pages/OverviewPage.tsx` | ✅ |
| FN-UI-02 | 실시간 관제 — 2채널 라이브 + 오버레이 · **단독 확대 보기** · 진행 중 이벤트 · 수동 방송 | P0 | WEB | 기능 §4.6 · API §5 | M1 (라이브·상태·확대) / M2 (오버레이) / M3 (경고 상태) / M5 (우측 패널) | `front/src/pages/LivePage.tsx` · `front/src/live/` | ✅ |
| FN-UI-03 | 이벤트 — 목록·필터 + 상세(클립·LLM·규정·타임라인) | P0 | WEB | 기능 §4.6 · API §4.1 | M5 / M8(AI 칸) | `front/src/pages/EventsPage.tsx` | ✅ |
| FN-UI-04 | 영상 검색 — 자연어 질의 · 유사도순 결과 | P1 | WEB | 기능 §4.6 · API §4.3 | M8 | `front/src/pages/SearchPage.tsx` · `api/analysis.ts` | ✅ |
| FN-UI-05 | 분석 · 보고서 — 시정률 추이 · 반복 순위 · 히트맵 · 이상 탐지 | P1 | WEB | 기능 §4.6 · API §4.2 | M8 | `front/src/pages/AnalysisPage.tsx` · `analysis.css` | ✅ |
| FN-UI-06 | 챗봇 — 통계·검색·브리핑 질의 | P1 | WEB | 기능 §4.6 · API §4.4 | M8 | `front/src/pages/AssistantPage.tsx` | ✅ |
| FN-UI-07 | 설정 — 구역 그리기 · 캘리브레이션 · 음원 · 임계값 · 시스템 | P1 | WEB | 기능 §4.6 · API §4.5 | M6 | `front/src/pages/SettingsPage.tsx` · `settings.css` · `front/src/api/settings.ts` | ✅ |

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
| FN-CFG-01 | 카메라 캘리브레이션 (지면 4점 → 호모그래피 · 재투영 오차 표시) | P0 | SRV/WEB | 기능 §4.7 · API §4.5 | M6 | `packages/vision/homography.py` · `server/app/routes/cameras.py` · `scripts/seed_cameras.py` | ✅ |
| FN-CFG-02 | 금지구역 편집 (폴리곤 → 지면 좌표 · `zone_updated` 발행) | P0 | SRV/WEB | 기능 §4.7 · API §4.5 · §5.4 | M6 | `server/app/routes/zones.py` · `front/src/pages/SettingsPage.tsx` | ✅ |
| FN-CFG-03 | 경고 음원 매핑 (유형별 음원 + **등급** · `fall` 하한 3) | P0 | SRV/WEB | 기능 §4.7 · §6 · API §4.5 | M4 (저장소) / M5 (§6 컬럼) / M6 (API·화면) | `server/app/routes/sounds.py` · `server/domain/alerts.py`(`check_level`) · `front/src/pages/SettingsPage.tsx` | ✅ |
| FN-CFG-04 | 임계값 정책 관리 (**재시작 없이 반영**) | P1 | SRV/WEB | 기능 §4.7 · API §4.5 | M6 | `server/app/routes/policies.py` · `front/src/pages/SettingsPage.tsx` | ✅ |
| FN-CFG-05 | 위험 반경 설정 (클래스별) | P1 | SRV/WEB | 기능 §4.7 · API §4.5 | M6 | `server/app/routes/vehicles.py` · `server/infra/db/repository.py` | ✅ |

---

## 4.8 시스템 (FN-SYS) · 6건

명세서 §4.8 표는 `01 · 02 · 03 · 05 · 06 · 04` 순서로 적혀 있다. 여기서는 ID 순으로 정렬했다.

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-SYS-01 | 구성요소 상태 감시 (엣지·카메라·MCU·클라우드·저장소) | P0 | SRV | 기능 §4.8 · API §4.6 | M1 (카메라·저장소) / M2 (엣지) / M4 (MCU·클라우드) | `server/app/routes/system.py` · `server/domain/edge_state.py` · `mcu_state.py` · `cloud_state.py` | ✅ |
| FN-SYS-02 | 시각 동기화 (NTP · 클립 정합의 전제) | P0 | SRV/EDGE | 기능 §4.8 | M1 (서버) / M2 (엣지 오프셋) | `server/infra/timesync.py` · `edge/` | 🟡 |
| FN-SYS-03 | 클라우드 장애 격리 | P1 | SRV | 기능 §4.8 | M4 (격리·표시) / M8 (실제 어댑터) | `server/domain/cloud_state.py` · `server/ai/guard.py` · `server/ai/gemini.py` | ✅ |
| FN-SYS-04 | 지표 집계 (시정률 · 평균 시정 시간 · 판정 불가율 · 분포) | P0 | SRV | 기능 §4.8 · API §4.2·§6.7 | M3 (summary) / M8 (분포·시계열) | `server/domain/metrics.py` · `aggregates.py` · `routes/metrics.py` | ✅ |
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
> **FN-SYS-04 는 M8 에서 닫혔다.** `GET /metrics/summary` 는 M3 에서 동작했고, 같은
> §4.2 의 `timeseries` · `distribution` · `repeat` 를 분석 화면(FN-UI-05)과 함께 만들었다.
> 비율 규칙은 여전히 `server/domain/metrics.py` **한 곳**에만 있다 — `aggregates.py` 가
> 버킷마다 `summarize` 를 그대로 부른다. 두 벌이 되면 요약과 추이가 다른 시정률을 말한다.

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

## 개발 환경 성능 — 가짜 카메라가 CPU 를 먹는 문제

**"컴퓨터가 느려서"가 아니었다.** 화면 끊김의 원인은 가짜 카메라의 x264 실시간 재인코딩이다.
실물 젯슨 환경에는 **이 부하가 아예 없다** — 카메라가 이미 h264 를 뱉는다.

**실측** (2026-07-30 · Intel Core 5 120U · 물리 10 / 논리 12코어 · 저전력 15W급)

| 항목 | 기본 모드 | `--copy` |
|---|---|---|
| 가짜 카메라 ffmpeg 4개 CPU | **405%** (1080p 152+145 · 640p 57+52) | **4.9%** |
| 전체 CPU | 83% | 42~68% (나머지는 IDE·브라우저 등) |
| mediamtx `reader is too slow` | 145 · 398 · 33 프레임 폐기 | **0건** (75초 관찰) |
| ffmpeg `time discontinuity` | `-2270672 us, resetting` 반복 | **0건** |

`realtime` 필터가 2초씩 밀렸다가 리셋되는 것이 결정적 증거다 — **인코더가 실시간을
따라가지 못한다**는 뜻이고, 그 결과 mediamtx 가 소비자에게 보낼 프레임을 버린다.

    uv run tasks.py cams --copy                  # testsrc2 를 30초 클립으로 굽고 루프
    uv run tasks.py cams --copy --source a.mp4   # 그 파일을 루프 (h264 mp4 그대로)

클립을 스트림 규격별로 **한 번만** 인코딩해 `media/run/prepared/` 에 캐시하고, 이후
`-re -stream_loop -1 -c copy` 로 리먹스한다. 디코딩도 인코딩도 하지 않는다.

**대가: 영상에 타임코드가 없다.** 클립을 루프하면 파일 안의 시각이 되감겨 벽시계와
어긋나는데, 그 타임코드는 "지금 몇 시의 프레임인가"를 눈으로 대조하는 도구다(오버레이
정합 실측). 어긋난 타임코드는 없는 타임코드보다 나쁘다. **정합을 재려면 기본 모드나
`--marker` 를 쓴다** — 그리고 그때는 다른 프로세스를 내려야 한다(위 실측 참조).

**B-프레임을 만들지 않는다(`-bf 0`).** WebRTC 는 B-프레임 H264 를 받지 못해 mediamtx 가
`WebRTC doesn't support H264 streams with B-frames` 로 세션을 즉시 닫고, 화면에는 검은
타일만 남는다. 그 실패는 **브라우저 콘솔에도 서버 로그에도 보이지 않아** mediamtx 컨테이너
로그를 뒤져야 원인을 안다(실제로 그렇게 찾았다). 기본 모드는 `-tune zerolatency` 가
B-프레임을 함께 껐기 때문에 드러나지 않았다. 실물 IP 카메라도 저지연을 위해 B-프레임을
쓰지 않으므로 규격에 맞다. `require_no_b_frames` 가 준비된 클립과 **캐시 재사용 시에도**
검사해 걸리면 송출하지 않고 멈춘다(절대규칙 9).

> **드랍 프레임 수치를 믿지 마라 (이 환경에서).** 브라우저 창이 표시되지 않으면 프레임을
> 합성하지 않아 `getVideoPlaybackQuality()` 가 수신 프레임 전량을 `dropped` 로 센다
> (실측 223/223). 재생이 정상인지는 **`currentTime` 진행**으로 본다 — 15초 관찰에
> 14.9초 진행이면 흐르고 있는 것이다.

---

## M5 이후 — 화면을 띄워 보고 고친 것들

M5 본작업이 끝난 뒤 **실제로 스택을 띄워 쓰면서** 나온 것들이다. 네 건 모두 화면이나
로그를 보지 않았으면 드러나지 않았을 문제이고, 셋은 성능·사용성이며 하나는 명세서와
구현의 불일치다.

| 커밋 | 무엇 | 근거 |
|---|---|---|
| `8bf9846` | FN-UI-02 우측 패널만 스크롤 | 상태를 보려고 스크롤하면 영상이 화면 밖으로 나갔다 |
| `ae6ef37` | 가짜 카메라 `--copy` 모드 | CPU 405% → 4.9% · 프레임 폐기 0 |
| `b93cfc2` | `media/sample.mp4` 기본 소스 · `cams` 기본을 `--copy` 로 | 실물 카메라와 같은 상태(h264 그대로)로 개발한다 |
| `a764639` | 대시보드 폴링·재조회 축소 | 대기 60초당 요청 12건 → 3건 |

### ① 우측 패널만 스크롤 (FN-UI-02)

관제 중에 진행 중 이벤트나 저장소 상태를 훑어보려고 스크롤하면 **영상이 화면 밖으로
나갔다.** 그건 관제 화면이 아니다. 화면 높이를 뷰포트에 못박아 페이지 자체 스크롤을
없애고 넘치는 쪽만 자기 안에서 움직이게 했다.

실측: 우측 786px 스크롤 가능 · 페이지·좌측 스크롤 0 · 끝까지 굴려도 타일 `top` 변화 0px.
좁은 화면(<1100px)에서는 1열로 접히므로 높이를 풀어 평범한 페이지 스크롤로 돌린다 —
1열에서 영상을 고정하면 우측 패널을 볼 방법이 없다.

### ② 화면 끊김의 진짜 원인 — 가짜 카메라의 실시간 재인코딩

**"컴퓨터가 느려서"가 아니었다.** 위 「개발 환경 성능」 절에 실측을 정리했다. 요점만:

* 가짜 카메라 ffmpeg 4개가 **CPU 405%**(논리 12코어 중 4개)를 상시 점유
* 그래서 `realtime` 필터가 2초씩 밀렸다가 리셋(`time discontinuity detected`)
* mediamtx 가 소비자에게 보낼 프레임을 버림(`reader is too slow, discarding 398 frames`)
* **실물 젯슨 환경에는 이 부하가 없다** — 카메라가 이미 h264 를 뱉는다

`--copy` 로 클립을 한 번만 굽고 리먹스하니 **4.9%** 가 됐다.

**밟은 함정**: 준비 클립에 B-프레임이 섞이자 WebRTC 가 세션을 즉시 닫고 화면이 검게
남았다. 그 실패는 **브라우저 콘솔에도 서버 로그에도 보이지 않는다** — mediamtx 컨테이너
로그에만 `WebRTC doesn't support H264 streams with B-frames` 로 찍힌다. `-bf 0` 으로
고치고 `require_no_b_frames` 가 준비 직후와 **캐시 재사용 시에도** 검사하게 했다.

### ③ `media/sample.mp4` 를 기본으로

`--source` 없이도 그 파일을 쓴다(없으면 testsrc2 로 떨어지고, **어느 쪽을 골랐는지
로그에 적는다**). 소스 규격이 960×540·25fps 여도 준비 단계에서 1920×1080 / 640×360 ·
15fps 로 맞춘다. 소스가 있으면 `-stream_loop` 없이 **파일 전체를 그대로** 굽는다 —
28초 영상을 30초로 채우면 루프 이음새가 한 바퀴에 두 번 생긴다.

`uv run tasks.py cams` 와 `dev` 의 기본이 `--copy` 다. 옛 동작은 `--timecode` 로 남겼고
`--marker` 는 매 프레임 사각형을 다시 그리므로 자동으로 타임코드 모드를 쓴다.

### ④ 서버 로그를 되찾기

`server.log` 마지막 20줄이 전부 `GET /alerts/mute` 였다. 동작에는 문제가 없지만 **정작
봐야 할 줄을 덮어** 무언가 잘못됐을 때 원인을 찾을 수 없게 만든다(§4.4 문제를 찾을 때
실제로 이 로그가 쓸모없었다).

* 일시중지 폴링 15초 → **120초**. 늦어지지 않는 이유는 바뀌는 순간을 따로 잡기
  때문이다 — 걸거나 풀면 §5.3 `system`(`component: mcu`)이 오고, 기한 만료는 그 시각에
  맞춰 한 번 더 읽는다. 폴링은 둘 다 놓쳤을 때의 대비책이다
* §5.2 재조회를 **400ms 창으로 병합**한다(`front/src/api/useRefresh.ts`). 한 전이가
  메시지를 여럿 만들고 개요는 그때마다 두 요청을 보내므로, 접지 않으면 전이 하나에
  요청이 네 개 붙는다. **마지막 것을 보낸다** — 앞의 것을 보내면 최신 상태를 놓친다

### ⑤ 코드로 고치지 않고 보고한 것 — §4.4 추출 타이밍 2건

「명세서 확인 필요」 A 절 맨 위 두 줄이다. 화면에서 **클립이 `failed`, 키프레임이 0장**
으로 나오는 것을 보고 파고들어 찾았다. 둘 다 `--copy` 와 무관한 원래 문제이며, §4.4
타이밍 표를 고쳐야 하므로 코드를 먼저 바꾸지 않았다(절대규칙 8).

**런타임에만 반영한 것**: `clip_extract_margin_s` 를 DB 에서 **2 → 12**(=세그먼트 10초
+ 여유 2초)로 올렸다. 정책값이라 현장 조정 대상이고 코드 기본값(2 · 명세서 값)은
건드리지 않았다. 이 값으로 `clip_status = ready` 를 확인했다.

> **이 절이 남는 이유.** 위 넷 중 셋은 `uv run tasks.py verify` 로는 절대 잡히지 않는다.
> 스크롤이 영상을 밀어내는 것, CPU 포화로 프레임이 버려지는 것, 로그가 접근 기록으로
> 덮이는 것 — 전부 **띄워서 써 봐야** 보이는 것들이다. M6 이후에도 화면을 실제로 켜 보는
> 단계를 마일스톤 안에 두는 편이 낫다.

---

## M6 산출물 (설정과 좌표계)

**이 단계에서 실좌표계가 성립했다.** 지금까지 시뮬레이터가 미터값을 손으로 실어 보냈지만,
이제 픽셀에서 미터를 계산하는 코드(`packages/vision`)가 생겼고 시나리오·설정 화면·서버가
**같은 호모그래피 하나**를 쓴다.

| 항목 | 위치 | 근거 | 상태 |
|---|---|---|---|
| `homography.py` — 실측 4점 → H(DLT · Hartley 정규화) · 픽셀↔미터 양방향 · 재투영/왕복 오차 | `packages/vision/src/aegis_vision/homography.py` | API §6.2 · §4.5 | ✅ |
| `footpoint.py` — 마스크 하위 8% 띠의 x 중앙값 · bbox 경로 · `foot_conf` 3요인 | `.../footpoint.py` | API §6.1 | ✅ |
| `zones.py` — 점-다각형 · 부호 있는 거리 · `buffer_m` 히스테리시스 | `.../zones.py` | FN-DET-07 | ✅ |
| `distance.py` — `bbox_center` / `mask_nearest` · 위험 반경 경계 포함 | `.../distance.py` | API §6.5 · FN-DET-08·09 | ✅ |
| FN-CFG-01 캘리브레이션 API + 화면 (재투영 오차 표시 · 구역 재발행) | `server/app/routes/cameras.py` · `front/src/pages/SettingsPage.tsx` | §4.5 · §5.4 | ✅ |
| FN-CFG-02 구역 편집 — 화면에서 그린 **픽셀**을 서버가 미터로 변환 · `zone_updated` 발행 | `server/app/routes/zones.py` | §4.5 · §5.4 | ✅ |
| FN-CFG-03 음원 매핑 API (`GET`/`PUT /alert-sounds`) · `fall` 등급 하한 422 | `server/app/routes/sounds.py` · `server/domain/alerts.py` | §4.5 · §3 | ✅ |
| FN-CFG-04 `PATCH /policies` — **재시작 없이** 상태머신·경고·클립에 즉시 반영 | `server/app/routes/policies.py` | §4.5 | ✅ |
| FN-CFG-05 `GET`/`PATCH /vehicle-classes` — 위험 반경 | `server/app/routes/vehicles.py` | §4.5 | ✅ |
| FN-UI-07 설정 화면 — 영상 위 4점 클릭 · 폴리곤 그리기 · 음원 표 · 임계값 격자 · 위험 반경 | `front/src/pages/SettingsPage.tsx` · `settings.css` | 시안 4p · 부록 A-1 | ✅ |
| edge_sim 이 **정규화 픽셀만** 싣고 `packages/vision` 으로 미터를 계산 | `sim/edge_sim/scripted.py` · `scripts/seed_cameras.py` | FN-DET-06 | ✅ |
| 좌표 일관성 회귀 — 미터 직접 기재 금지 · `in_zone` 기하 일치 · `within_danger_radius` 검산 | `sim/tests/test_coordinates.py` | — | ✅ |

### 기존 시나리오의 좌표는 두 벌이었다 (★ 이번에 드러난 것)

M6 이전 시나리오는 `foot_point`(픽셀)와 `foot_point_m`(미터)를 **각각 손으로** 적었다.
둘이 어긋나도 아무 테스트가 깨지지 않는다 — 서버는 미터만 보고 화면은 픽셀만 보기 때문이다.
변환 경로를 붙이기 전에 그 두 벌이 서로 맞는지부터 쟀다.

| 검사 | 결과 |
|---|---|
| cam1 의 (픽셀, 미터) 쌍 41개에 **하나의 호모그래피**가 맞는가 | **아니다.** 최소제곱 잔차 평균 5.72 m · 최대 83 m |
| 같은 검사를 RANSAC 으로 (오차 0.3 m 이내) | 41쌍 중 **24쌍만** 한 평면 위에 있었다 |
| cam2 의 15쌍 | **전부 일치**(중앙값 0.10 m · 최대 0.27 m) — 이쪽은 실제로 변환해 만든 값이다 |
| `no_helmet` 한 파일만 따로 | 잔차 0.006 m — 핀홀 모델로 되맞추니 **높이 2.18 m · 틸트 5.9°** 가 나왔다 |

즉 **변환이 틀린 것이 아니라 기존 좌표 일부가 손으로 쓰인 것**이었다. 더 나쁜 것은
좌표와 라벨이 이미 어긋나 있었다는 점이다 — 아래는 **M6 이전부터 틀려 있던** 것들이다.

| 시나리오 | 적혀 있던 미터 | 적혀 있던 `in_zone` | 사실 |
|---|---|---|---|
| `alert_suppressed` p7 | (12.4, 7.88) | `forklift_lane` | 구역은 x 2~7 m 다 — **밖인데 안이라고 적혀 있었다** |
| `false_positive` p5 | (14.2, 8.4) | `forklift_lane` | 같은 오류 |
| `gating_freeze` p3 | (9.8, 14.2) | `forklift_lane` | y 도 벗어난다 |
| `fall_excluded` p3 | (3.1, 7.6) | `null` | **안인데 밖이라고 적혀 있었다** |
| `no_helmet_resolved` p3 | (6.02, 7.91) | `null` | 같은 오류 |

**복원한 카메라 기하를 개발용 캘리브레이션으로 굳혔다**(`scripts/seed_cameras.py`).
바닥의 6 m × 5 m 격자 네 점(x 3~9 · y 7~12)을 그 모델로 투영한 값이며, 그래서 기존 픽셀
경로가 예전 미터값과 **거의 같은 위치**로 변환된다 — `no_helmet` 기준 (8.28, 9.00) →
(8.23, 8.81), (6.49, 8.59) → (6.49, 8.47). `in_zone` · `zone_id` 는 이제 **계산해서 채웠고**,
같은 규칙을 `sim/tests/test_coordinates.py` 가 매번 검산한다.

### 시나리오 기대값은 유지됐다

`uv run tasks.py cases` — **12개 중 12개 통과**(시정률·판정 불가율·경고 목록·클립 상태 전부).
좌표계를 바꿨는데도 기대값이 그대로인 이유는 상태머신이 보는 것이 `violation_type` ·
`observed_ms` · `nearby[].dist_m` 이지 접지점 자체가 아니기 때문이다. 다만 **클립 예약
시각이 12초에서 22초로 늘어** 세 시나리오의 꼬리를 조정했다.

| 시나리오 | 조정 | 이유 |
|---|---|---|
| `normal_resolve` · `alert_muted` | `tail_s: 9.0` | 해소(+16초) 뒤라 시간을 더 흘려보내도 상태가 바뀌지 않는다 |
| `clip_recovery` | `rec.segment_seconds: 2` | 이 시나리오의 주제가 「재시작을 넘어 pending → ready」다. tail 을 22초 늘리면 관측이 끊긴 트랙이 `lost` 로 가서 보려는 것이 흐려진다 |
| `alert_suppressed` | 트랙 7 의 기대를 `clip_status: pending` 으로 | 확정(+14.5초) + 22초는 시나리오가 끝난 뒤다. **늦게 확정된 이벤트의 클립이 아직 준비되지 않은 것이 정상**이고, 그것을 기대값에 그대로 적었다 |

### 실측 — 화면을 실제로 켜서 확인한 것

실제 서버 · PostgreSQL · REC · 가짜 카메라 2대 · 브라우저에서 조작했다.

| 확인 | 결과 |
|---|---|
| 영상 위 4점 클릭 → 실측값 입력 → 저장 | `cam1 캘리브레이션 저장 — 재투영 오차 0.000 m` |
| 한 직선 위 4점(통로 한 줄을 따라 찍는 실수) | **422** · 화면에 「한 직선 위에 있다 — 지면 평면이 정해지지 않는다」 |
| 폴리곤 그리기 → 저장 | 픽셀 4점 → 지면 (3.73, 7.34) (7.24, 7.34) (7.14, 11.29) (3.58, 11.29) · 서버가 변환 |
| 저장된 구역이 영상 위에 다시 그려지는가 | 3개 폴리곤 렌더 (미터 → 픽셀 역변환) |
| 캘리브레이션 없는 카메라에 구역 저장 | 422 「먼저 4점 캘리브레이션을 하세요」 |
| `PATCH /policies` (확정 3→4초 · 쿨다운 30→25초) | 200 · 응답이 갱신 후 전량 · 재시작 없음 |
| `PUT /alert-sounds/fall` `level: 2` | **422** — 안전 하한은 설정 대상이 아니다 |
| 확정 → 방송 지연 | **113 ms** (FN-ALM-01 요구 1초) |
| 확정 시각 키프레임 | **2장 저장** (이전에는 0장 · REC 이 500 을 냈다) |
| 클립 | `ready` · 6.7 MB · 실제 구간 21.1초 (`partial` 아님) |
| 설정 화면 대기 시 요청 수 | 60초에 3건(`GET /alerts/mute` — 다른 탭의 실시간 관제 폴링) |

### 화면을 켜서 찾은 것 (verify 로는 잡히지 않는다)

| 문제 | 조치 |
|---|---|
| **서버가 남긴 로그가 하나도 보이지 않았다** | uvicorn 은 자기 로거만 설정한다. 루트에 핸들러가 없어 `log.info` 가 전부 사라지고 접근 로그만 남아 있었다 — 캘리브레이션 저장·`zone_updated` 발행·클립 예약이 전부 안 보였다. `_configure_logging()` 을 두었다(핸들러가 이미 있으면 손대지 않는다) |
| 로그를 켜니 **httpx2 가 초당 한 줄**을 찍었다 | 스트림 감시가 mediamtx 를 초당 폴링한다. `httpx2` 로거를 WARNING 으로 내렸다 — 실패는 그대로 보인다 |
| 한글 로그가 **cp949 로 깨져** 파일에 남았다 | 서버도 `stdout`/`stderr` 를 UTF-8 로 재설정한다(`tasks.py` · 시드 스크립트와 같은 처리) |
| 4점을 **빠르게 연속 클릭하면 한 점만** 남았다 | 같은 렌더 주기의 클릭들이 배열을 서로 덮어썼다. 함수형 갱신(`setPoints((current) => ...)`)으로 고쳤다 |
| 저장 실패인데 「설정을 읽지 **못했다**」로 떴다 | 읽기 실패와 저장 실패가 같은 문구를 쓰고 있었다. 문구를 부르는 쪽이 붙이게 했다 |
| 설정 화면의 카메라 이름이 **코드에 박혀** 있었다 | 설정 화면만 `GET /cameras` 의 `name`(§6 `cameras.name`)을 쓴다. 다른 화면은 아직 `labels.ts` 표를 쓴다 — 아래 「남아 있는 확인 필요」 참조 |

### ★ 스냅샷 버퍼의 CPU — 명세서 전제가 개발 기계에서는 성립하지 않는다

§4.4 는 「초당 1장 인코딩은 리먹스 부하에 비해 무시할 수준」이라고 적었다. **비용은 인코딩이
아니라 디코딩이었다** — 초당 1장을 뽑아도 `fps` 필터에 넣으려면 모든 프레임을 풀어야 한다.

| 방식 | 20초 동안 CPU | 코어 |
|---|---|---|
| 전체 디코딩 (`-vf fps=1`) — 현재 기본 | 6.5초 | **33%** |
| 키프레임만 (`-skip_frame nokey`) | 1.4초 | **7%** |
| 패킷 폐기 (`-discard nokey`) | 4.5초 | 23% |
| (비교) 세그먼트 녹화 = 리먹스 | 0.3초 | 2% |

카메라 2대면 코어의 **66%**다. 젯슨은 NVDEC 이 받아주므로 명세서의 전제가 성립하지만,
소프트웨어 디코딩을 쓰는 개발 노트북에서는 성립하지 않는다(M5 의 가짜 카메라 재인코딩과
같은 종류의 문제다). `REC_SNAPSHOT_KEYFRAMES_ONLY` 를 두되 **기본은 끔**으로 했다 —
켜면 샘플 간격이 스트림 GOP 를 따르므로 §4.4 가 보장한 「초당 1장 · 최대 0.5초 차이」가
깨질 수 있고, 명세서가 정한 값을 설정 하나로 조용히 바꾸지 않는다(절대규칙 8).

### 키프레임 응답 시간 (M6 실측)

| 요청 시각 | 경로 | 응답 |
|---|---|---|
| 지금 (버퍼 안) | 메모리 | **6.7 ms** · 176 KB |
| 180초 전 (버퍼 밖) | 세그먼트 + ffmpeg | 416 ms · 163 KB |

확정 순간의 요청이 **500 에서 200 으로** 바뀐 것이 이 변경의 요점이고, 62배는 덤이다.

### M6 이 고른 것 (설계 판단)

| 판단 | 이유 |
|---|---|
| `packages/vision` 에 **의존성을 두지 않았다**(numpy 도 안 쓴다) | 젯슨·서버·시뮬레이터가 함께 쓰는 순수 계산이다. 대응점 4~8개의 최소제곱과 프레임당 수십 번의 점 변환에 배열 라이브러리가 필요하지 않다. 대신 수치 안정성은 직접 챙겼다 — **Hartley 정규화 없이 풀면** 같은 데이터에서 잔차가 0.1 m 대에서 1.6 m 대로 커진다(실측) |
| 최소 고유벡터를 **야코비 회전**으로 구한다 | `AᵀA` 는 대칭이라 야코비면 충분하고 외부 라이브러리 없이 안정적이다 |
| 4점이 **한 직선 위면 거부**한다 | 통로 한 줄을 따라 찍는 실수는 실제로 일어나고, 행렬은 풀리지만 결과가 무의미하다. 조용히 통과시키면 모든 거리·구역 판정이 틀리면서 화면 어디에도 드러나지 않는다 |
| 지평선 위의 점을 **거부**한다 | 동차좌표의 `W` 가 0에 가까우면 대응하는 지면 점이 없다. 큰 수를 돌려주면 그 좌표가 거리 계산과 구역 판정으로 그대로 흘러간다 |
| 히스테리시스를 **`buffer_m` 하나로** 만든다 | 진입선 = 경계 + `buffer_m`(사전 경고 · §4.5), 이탈선 = 거기서 다시 `buffer_m`. 새 상수를 만들지 않았고, `buffer_m = 0` 이면 두 선이 경계로 겹쳐 히스테리시스가 사라진다 |
| 겹친 구역에서는 **더 좁은 쪽**을 고른다 | 「공장 전체」보다 「지게차 통행로」가 쓸모 있는 답이다. 목록 순서(= DB 조회 순서)로 정하면 아무 의미 없는 것이 판정을 바꾼다 |
| 픽셀 → 미터 변환을 **서버에서** 한다 | 프론트가 변환하면 호모그래피 적용 코드가 TypeScript 로 한 벌 더 생긴다. 되그릴 때만 역행렬을 곱한다(행렬 곱이지 캘리브레이션이 아니다) |
| 시나리오가 미터를 적으면 **오류**다 | 두 벌의 좌표가 다시 생기는 것을 막는 유일한 방법이다. 위 표가 그 대가를 보여준다 |
| 세그먼트 길이를 **모르면 클립을 뽑지 않는다** | 기본값(10초)으로 추측해 뽑으면 REC 설정이 다를 때 뒤가 잘린 클립이 `ready` 로 굳고 되돌릴 수 없다. 예약은 DB 에 남으므로 REC 이 살아나면 다음 주기에 집힌다 |
| `alert_sounds.level` 하한을 **읽는 쪽에서도** 본다 | API 가 422 로 막지만 DB 를 직접 고칠 수도 있다. `fall` = 2 를 그대로 쓰면 긴급 상황에서 부저가 울리지 않으므로, 읽을 때 3으로 올리고 그 사실을 ERROR 로 남긴다 |
| `GET /cameras` 를 새로 만들었다 | 설정 화면이 저장된 구역을 영상 위에 다시 그리려면 호모그래피가 필요한데, `POST` 응답만으로는 **새로고침 뒤에 아무것도 그릴 수 없다**. §4.5 에 조회 경로가 없어 아래에 올려 두었다 |

---

## M7 산출물 (P1 감지 정밀화)

**이 단계에서 감지 판정이 시뮬레이터의 손을 떠났다.** M6 까지 `height_ratio` ·
`axis_angle_deg` · `stillness_s` · `nearby[].dist_m` 은 시나리오 작성자가 손으로 적은
값이었다. 그 상태로는 「쭈그림이 쓰러짐으로 잡히지 않는다」를 검증할 수 없다 — 검증하는
사람이 곧 정답을 적는 사람이기 때문이다. 이제 시나리오는 **관측 가능한 것**(bbox · 자세 ·
움직임 · 포크 길이)만 적고, 판정은 `packages/vision` 이 한다.

| 항목 | 위치 | 근거 | 상태 |
|---|---|---|---|
| 근접 후보 판정 (세 반경 · `moving` 결합) | `packages/vision/distance.py` | FN-DET-08 · §4.5 | ✅ |
| 마스크 최근접 거리 + 합성 형상 검증 | `packages/vision/distance.py` · `tests/test_distance.py` | FN-DET-09 · §6.5 | ✅ |
| 쓰러짐 3조건 (높이 비율 · PCA 주축 · 정지 지속) | `packages/vision/posture.py` | FN-DET-10 · §6.4 | ✅ |
| 뎁스 온디맨드 — 트리거 A~D · 0.5초 캐시 · 이동 무효화 | `packages/vision/depth.py` | FN-DET-11 · §6.6 | ✅ (모델은 M9) |
| 반복 위반에 **위반 유형** 필터 (§4.1 「유사 이벤트」) | `server/infra/db/repository.py` | FN-EVT-06 | ✅ |
| 합성 마스크 생성기 (자세 4종 × 움직임 2종) | `sim/edge_sim/masks.py` | — | ✅ |
| 시나리오가 적은 자세 → 게이지 계산 | `sim/edge_sim/derive.py` | FN-DET-08~11 | ✅ |
| 시나리오 5종 + `expect.postures` · `expect.distances` 대조 | `sim/cases/` · `sim/tests/test_masks.py` | — | ✅ |
| 정지 판정 임계 (장비 종속 튜닝값) | `edge/config.yaml` `posture` 절 | 절대규칙 6 | ✅ |

### ★ 쓰러짐 오탐 억제 — 자세별 판정표

임계값은 `policies` 기본값(`fall_height_ratio_max` 0.5 · `fall_axis_angle_min_deg` 55 ·
`fall_stillness_s` 5.0)이고, 아래 숫자는 **합성 마스크에서 실제로 계산되어 나온 값**이다
(`uv run pytest sim/tests/test_masks.py`).

| 자세 | height_ratio ≤ 0.5 | axis_angle ≥ 55° | stillness ≥ 5.0s | 판정 |
|---|---|---|---|---|
| 서 있음 (일하는 중) | 0.972 ❌ | 1.1° ❌ | 0.0s ❌ | `standing` |
| **쭈그림** (일하는 중) | 0.176 ✅ | 90.0° ✅ | 0.0s ❌ | **`standing`** |
| **허리 굽힘** (일하는 중) | 0.335 ✅ | 68.1° ✅ | 0.0s ❌ | **`standing`** |
| 쓰러진 직후 (5초 미만) | 0.080 ✅ | 90.0° ✅ | 2.5s ❌ | `standing` |
| 쓰러짐 (5초 이상 정지) | 0.080 ✅ | 90.0° ✅ | 6.5s ✅ | **`fallen`** |
| 쓰러졌다가 일어남 | 0.972 ❌ | 1.1° ❌ | 0.0s ❌ | `standing` (복귀) |

> **가운데 두 행이 이 마일스톤의 결과다.** 쭈그림과 허리 굽힘은 ①②를 **통과한다** —
> 실제로 낮고 실제로 기울어져 있기 때문이다. 두 조건만으로 판정했다면 부품을 줍거나
> 설비 앞에서 허리를 굽힐 때마다 level 3 긴급 경고가 나갔을 것이고, 그런 시스템은
> 일주일이면 꺼진다. **셋을 갈라놓는 것은 ③(정지 지속)뿐이다.**
>
> 그래서 시험 마스크를 ①②에서 걸러지도록 그리지 **않았다.** 모양만으로 안전한
> 테스트는 ③이 죽어 있어도 통과한다. `expect.postures` 가 `meets` / `fails` 를 함께
> 적는 이유도 같다 — "무엇이 걸렀는가"까지 대조하지 않으면 통과의 의미가 없다.
>
> 마지막 행은 **판정이 양방향**임을 잠근다. `fallen` 이 한 번 붙고 굳어버리면 일어선
> 사람이 영원히 쓰러진 채로 남고, §4.2 의 `fall` 해소 조건(「자세가 `standing` 으로
> 복귀」)에 도달하는 길이 사라진다.

### ★ 마스크 최근접과 중심 거리가 갈리는 지점 (FN-DET-09)

`sim/cases/mask_vs_center.yaml` — 포크가 bbox 폭의 55%(지면 약 2.4m)를 차지하는 형상.

| 방식 | 값 | 위험 반경 3.0m 기준 |
|---|---|---|
| `bbox_center` (아래변 중앙끼리) | **3.50 m** | 안전으로 보인다 |
| `mask_nearest` (윤곽 최단) | **1.55 m** | 위험 · 경고 임계(2.0m)도 넘는다 |

**하나의 임계값을 사이에 두고 판정이 뒤집힌다.** 실제 접촉은 포크 끝에서 일어나므로
`mask_nearest` 가 맞다. 두 값이 비슷하게 나오는 형상(뻗은 부분이 없는 사각형)도 함께
잠갔다 — 항상 다르다면 그건 형상 때문이 아니라 계산이 틀린 것이다
(`test_on_a_compact_shape_the_gap_is_only_the_half_widths`).

### 실측 — 스냅샷 버퍼 재설계 (기능명세서 §4.4 갱신분)

지속 디코딩을 없앤 것이 이 변경의 전부다.

| 항목 | M6 (초당 1장 디코딩) | M7 (비트스트림 보관) |
|---|---|---|
| 스냅샷 경로 CPU (카메라 2대) | **66%** (코어) | **2.4%** (실측 20초에 0.48초) |
| REC 전체 CPU (녹화 + 스냅샷 + 보존, 2대) | — | **12.3%** |
| 메모리 | JPEG 60장 × 2 ≈ 20MB | 비트스트림 60초 × 2 = **11.4MB** (실측 `snapshot_bytes`) |
| 확정 시각 키프레임 응답 | 6.7 ms | **340~440 ms** |
| 버퍼 밖(180초 전) 응답 | 416 ms | 550 ms |
| 반환 프레임 | 초당 1장 샘플 중 가장 가까운 것 (최대 0.5초 오차) | **요청한 시각 그대로** |

> **응답이 50배 느려진 것은 의도한 교환이다.** 상시 66% 를 쓰던 것을 이벤트 확정
> 시점의 400ms 로 옮겼다. 젯슨에서는 추론이 이미 예산의 절반 이상을 쓰고 있어 상시
> 부하를 얹을 자리가 없고, 키프레임 요청은 확정 때만 일어난다. 400ms 의 대부분은
> Windows 의 ffmpeg 프로세스 기동 시간이며 GOP 디코딩 자체가 아니다.
>
> **근사를 없앤 것이 덤이 아니라 요점이다.** 예전에는 초당 1장 중 가장 가까운 것을
> 돌려줘 최대 0.5초 어긋난 그림이 증거로 남았다. 이제 목표 시각 직전 IDR 부터 목표
> 액세스 유닛까지만 디코딩해 **그 프레임 자체**를 낸다.
> `test_real_stream_returns_the_requested_frame_not_a_keyframe` 가 실제 ffmpeg 로
> 인코딩한 스트림에서 이것을 잠근다 — 잘라낸 조각을 디코딩한 결과가 전체를 디코딩해
> 같은 인덱스를 뽑은 것과 **바이트까지 같다**.

**표시 순서 주의**: 액세스 유닛의 도착 순서는 디코드 순서다. B프레임이 있으면 표시
순서가 뒤바뀌어 「마지막 출력 = 목표 프레임」이 깨지므로, B슬라이스를 만나면 경고를
남긴다(조용히 어긋난 그림을 내보내지 않는다 · 절대규칙 9). **실행 로그에 이 경고는
0건이었다** — 가짜 카메라(`deploy/fake_cams.py` 의 `-bf 0`)와 저지연 CCTV 는 B프레임을
쓰지 않는다.

### 화면을 실제로 켜서 확인한 것

실제 서버 · PostgreSQL · REC · 가짜 카메라 2대 · 브라우저에서 조작했다.

| 확인 | 결과 |
|---|---|
| `proximity_forklift` 실행 → 이벤트 | `resolved` · `min_distance_m` **0.25** (마스크 최근접 계산값) · `depth_verified` **true** · 클립 `ready` |
| `fall_detected` 실행 → 대시보드 | `event_created` `severity` **3** · 실시간 관제에 「긴급 · 쓰러짐 감지」 카드와 「관리자 확인」 버튼 |
| `overlay` 에 거리선 재료가 실리는가 | 209 프레임 중 **157 프레임**에 `nearby[{dist_m, anchor, in_danger_zone}]` — 캔버스가 이 값으로 선을 긋고 `0.2 m` 라벨을 붙인다 |
| 저장된 구역이 **픽셀 원본**으로 그려지는가 | 시드한 픽셀 폴리곤이 그대로 렌더 (`-7.29,89.29 …`) — 미터 역변환 경로를 타지 않는다 |
| ★ 캘리브레이션 갱신 → 지면 좌표 재계산 | 같은 4점을 **1.5배 축척**으로 다시 재서 저장하니 `polygon_m` 이 (2,6)→(3,9) · (7,11)→(10.5,16.5) 로 **정확히 1.5배**가 됐고 `polygon`(픽셀)은 그대로였다. §4.7 FN-CFG-01 「캘리브레이션이 축척 변환을 흡수한다」가 숫자로 성립한다 |
| 설정 화면 축척 안내 | 실측값 입력란 위에 5줄 — 같은 바닥 평면 · 환산 미터 · 임계값 고정 · 기준 신장 1.7m · 카메라 고정 |
| 보존 기간 표시 | 「보존 **1시간**」 (M6 에서는 「0일」이었다) |
| `GET /cameras` | `rtsp_main` · `rtsp_sub` · `calib_points` 4점 · `reproj_error_m` 0.0 전부 반환 |
| `GET /status` (REC) | `snapshot_fps` 사라짐 · `snapshot_bytes` 11,953,219 · `retention_days` 0.0417 (반올림하지 않는다) |
| 서버·REC 로그 WARNING 이상 | **0건** |
| 설정 화면 대기 60초 요청 수 | 서버 **0건** · REC 6건(서버의 10초 상태 폴링) |

### 화면을 켜서 찾은 것 (verify 로는 잡히지 않는다)

| 문제 | 조치 |
|---|---|
| 이전 세션의 서버·REC 프로세스가 **2일째 떠 있었다** | 새 프로세스가 포트를 못 잡고 종료코드 3으로 죽는데, 그동안 API 는 **옛 스키마로 정상 응답**했다(`snapshot_fps` 가 그대로 보였다). 새 코드를 확인한 줄 알고 옛 코드를 본 것이다 — 확인 전에 프로세스를 정리했다 |
| 시드가 `on_conflict_do_nothing` 이라 **새 컬럼이 빈 채**로 남았다 | 기존 구역·카메라 행이 있으면 `polygon`(픽셀)과 `calib_points` 가 채워지지 않는다. `--force` 로 다시 심었고, `seed_cameras.py` 가 대응점과 재투영 오차도 함께 심도록 고쳤다 |

### M7 이 고른 것 (설계 판단)

| 판단 | 이유 |
|---|---|
| 기대 높이를 **거리 반비례가 아니라 원근 배율(`W`)**로 구한다 | 「거리에 반비례」로 계산하려면 카메라의 지면 위치가 필요한데 §6 `cameras` 에 그런 칸이 없다. 호모그래피 셋째 행이 만드는 `W` 는 소실선까지의 세로 거리에 비례하고(`W = h21·(v − v_소실선)`), 그 비율이 곧 화면상 크기 비율이다 — **이미 저장된 값 하나로 곡선 전체가 정해진다** |
| 주축 각도를 재기 전에 **x 를 화면비로 되돌린다** | 정규화 좌표에서 x 1.0 은 y 1.0 보다 16/9 배 길다. 그대로 PCA 를 돌리면 누운 사람의 주축이 실제보다 수직에 가깝게 나와 ②가 헐거워진다 |
| 정지 판정이 중심 이동량과 **형태 변화량을 모두** 본다 | 중심만 보면 제자리에서 팔을 휘두르는 사람이 정지로 잡히고, 형태만 보면 자세를 유지한 채 미끄러지듯 이동하는 것을 놓친다(§6.4) |
| 움직였을 때 정지 시간을 **동결이 아니라 0으로** 되돌린다 | 게이팅 보류(§6.3)는 「관측하지 못했다」이고 이것은 「움직였다」는 관측 결과다. 둘을 같이 다루면 움직이는 사람에게 정지 시간이 쌓인다 |
| `moving` 이 위험도만 바꾸고 **문턱을 넓히지 않는다** | 이동 중이라고 경고 거리를 늘리면 정지한 지게차 옆을 지나가는 사람과 **같은 거리에서 다른 판정**이 나오고, 그 차이는 이벤트 기록에 남지 않아 사후에 설명할 수 없다 |
| `depth_verified` 를 근접 후보의 **필수 조건으로 두지 않는다** | 트리거 미충족이면 그 값이 항상 `false` 다(§6.6). 무조건 요구하면 회색지대 밖의 근접이 영영 잡히지 않는다 |
| `DepthResult` 에 **미터 필드를 두지 않는다** | 뎁스가 미터를 낼 수 있게 되는 순간 누군가 그것을 쓴다. 필드를 없애는 것이 "쓰지 마라"보다 강하다(절대규칙 4) |
| 반경 세 개(`screening` · `danger` · `warn`)를 **하나로 합치지 않는다** | 각각 다른 것을 정한다 — 5m 는 LLM 이 읽을 맥락, 3m 는 화면 표시, 2m 라야 후보다. 순서가 뒤집힌 설정은 생성 시점에 거부한다 |
| 합성 마스크의 움직임이 **결정적**이다(난수 없음) | 시나리오를 두 번 돌려 다른 값이 나오면 기대값을 적을 수 없다. 시각 하나로 정해지는 삼각함수만 쓴다 |
| `lying` 에서도 `motion` 을 살린다 | 팔을 빼면 「누웠다 = 쓰러졌다」가 되어 ③이 무력해진다. 바닥에 누워 작업하는 사람과 쓰러진 사람은 **모양이 같고 움직임만 다르다** |
| 옛 시나리오는 손으로 적은 값을 그대로 쓴다 | `mask` 를 적은 시나리오에서만 계산으로 덮어쓴다. M2~M4 의 11종을 한꺼번에 고치면 그 기대값들이 무엇을 잠그고 있었는지 함께 흔들린다 |
| 반복 위반을 **위반 유형별**로 센다 | §4.1 이 「**유사** 이벤트」라고 적었다. 안전모 미착용과 지게차 근접을 한 숫자로 합치면 무엇이 반복되는지가 사라져 대응을 정할 수 없다 |

---

## M8 산출물 (지능·분석)

**이 단계의 전제는 「클라우드가 죽어도 안전 기능은 무영향」이다**(FN-SYS-03). 그래서
지능 기능은 처음부터 **안전 루프 밖에서만** 돌게 만들었고, 그 사실을 실측으로 잠갔다
(아래 「클라우드를 끊고 잰 것」).

| 항목 | 위치 | 근거 | 상태 |
|---|---|---|---|
| 어댑터 경계 (`Embedder` · `Llm` 프로토콜) | `server/ai/ports.py` | §7 확장성 | ✅ |
| Gemini 어댑터 — **`google.genai` 를 아는 유일한 파일** | `server/ai/gemini.py` | 기능 §4.5 | ✅ |
| 클라우드 격리 — 실패를 상태로 바꾸고 거기서 멈춘다 | `server/ai/guard.py` · `server/domain/cloud_state.py` | FN-SYS-03 | ✅ |
| FN-AI-01 키프레임 임베딩 → `events.embedding`(halfvec 3072) | `server/ai/service.py` · `repository.save_embedding` | 기능 §4.5 | ✅ |
| FN-AI-02 하이브리드 검색 (SQL 선필터 + 벡터 랭킹) | `server/ai/search.py` · `repository.search_events` · `routes/search.py` | §4.3 | ✅ |
| FN-AI-05 LangGraph 4단계 분석 | `server/ai/graph.py` | 기능 §4.5 | ✅ |
| FN-AI-06 규정 매핑 (**사전 테이블**) | `server/ai/regulations.py` · `assets/seeds/regulations.yaml` | 기능 §4.5 | ✅ |
| FN-AI-07 유사 사고사례 (확정 시 1회 계산·저장) | `server/ai/incidents.py` · `assets/seeds/incidents.yaml` | §6 | ✅ |
| FN-AI-04 정상 풀 축적 · 이상 탐지 (k-NN 평균 코사인 거리) | `server/ai/vectors.py` · `service.sample_once` · `DbAiRepository` | §6.8 | ✅ |
| FN-AI-04 이상 목록 조회 · 화면 표시 | `routes/metrics.py`(`GET /anomalies`) · `front/src/api/anomalies.ts` · `LivePage`(주의 배너) · `AnalysisPage`(목록) | §5.3 · §6.8 | ✅ |
| FN-AI-08 챗봇 라우팅 (sql · vector · vision) | `server/ai/assistant.py` · `routes/assistant.py` | §4.4 | ✅ |
| FN-AI-09 실시간 현장 브리핑 | `server/ai/service.briefing` | §4.4 | ✅ |
| FN-AI-10 주간 보고서 (예약 → 배경 생성) | `server/ai/service.start_weekly_report` | §4.4 | ✅ |
| FN-SYS-04 잔여 — 시계열 · 분포 · 반복 | `server/domain/aggregates.py` · `routes/metrics.py` | §4.2 | ✅ |
| FN-UI-04 영상 검색 | `front/src/pages/SearchPage.tsx` | 기능 §4.6 | ✅ |
| FN-UI-05 분석 · 보고서 | `front/src/pages/AnalysisPage.tsx` | 기능 §4.6 | ✅ |
| FN-UI-06 챗봇 | `front/src/pages/AssistantPage.tsx` | 기능 §4.6 | ✅ |
| 이벤트 상세의 LLM · 규정 · 유사 사례 칸 | `front/src/pages/EventsPage.tsx` | §4.1 | ✅ |

### M8 이 고른 것 (설계 판단)

| 판단 | 이유 |
|---|---|
| **라우팅을 LLM 에게 맡기지 않는다** | 경로 판단이 비결정적이면 같은 질문이 날마다 다른 경로로 가고 그 차이를 설명할 수 없다. 무엇보다 `vision` 은 실제 프레임을 캡처하므로 통계 질문이 그쪽으로 새면 답이 틀리는 동시에 비용이 든다 |
| **질의 파싱도 정규식이다** | LLM 에게 "SQL 조건으로 바꿔줘"라고 시키면 **DB 에 나가는 조건을 생성 모델이 정한다.** 뽑아내지 못한 표현은 자유 문장으로 남아 벡터 쪽이 받으므로 놓치는 것이 없다 |
| **통계 숫자를 LLM 이 만들지 않는다** | SQL 집계가 숫자를 만들고 LLM 은 문장으로 옮기기만 한다. 표(`kind:"table"`)를 함께 실어 사람이 문장과 원본을 대조할 수 있다 |
| **표의 단위를 항목 이름에 적는다**(`… (%)`) | 셀에 0~1 을 그대로 실었더니 화면이 `1.0` 을 「1건」처럼 그렸다(실제로 그랬다). 백분율로 바꿔 실으면 `null` 은 `null` 인 채로 숫자가 자기 단위를 설명한다 |
| **재지 않은 유사도를 지어내지 않는다** | 임베딩이 없으면 `similar_incidents` 는 **빈 목록**이고 검색 결과의 `similarity` 는 `null` 이다. 유형만 같은 사례에 숫자를 붙이면 그 숫자가 곧 근거가 된다 |
| **분석 결과를 저장한다** | 조회할 때마다 부르면 같은 이벤트가 볼 때마다 다른 설명을 갖고, 「그때 무엇을 근거로 조치했는가」를 재현할 수 없다. 비용도 조회 수에 비례한다 |
| **비어 있는 칸은 `changes` 에 넣지 않는다** | `None` 을 그대로 쓰면 앞선 분석 결과를 덮어 지운다 — 재실행이 개선이 아니라 손실이 된다 |
| **정상 풀은 판정 여부와 무관하게 쌓는다** | 이상이었던 프레임을 빼면 풀이 점점 좁아져 「정상」의 정의가 스스로 조여든다 |
| **풀이 얇으면 판정하지 않는다**(`MIN_POOL`) | 축적 초기의 큰 거리는 「이상」이 아니라 「모른다」다. `anomaly_score` 도 풀이 비면 `0.0` 이 아니라 `None` 을 낸다 |
| **모집단이 빈 버킷은 점을 만들지 않는다** | §4.2 `points[].value` 는 `float` 이고 §6.7 은 분모 0이면 비율이 없다고 말한다. 0을 찍으면 이벤트가 없던 구간이 「시정률 0%」로 보인다 |
| 반복 순위의 `track` 라벨이 **「추적」이지 「작업자」가 아니다** | §4.2 — 추적 번호는 신원이 아니고 카메라를 벗어나면 유효하지 않다. 라벨이 사람을 가리키면 그 숫자가 개인 평가로 읽힌다 |
| 이상 '주의'를 **위반 알림과 다른 배열·다른 색으로** 그린다 | 같은 목록에 담으면 화면이 둘을 같은 모양으로 그리게 되고, 그 순간 '주의'가 경고처럼 읽힌다. 조명·날씨로도 점수가 오르므로 곧 **둘 다** 무시된다. 앰버 배너 · 소리 없음 · 「평소와 다르다」(단정하지 않는 문구) |
| 이상 목록을 **조회와 WebSocket 둘 다**로 받는다 | 발행만 보면 새로고침한 화면이 텅 비고, 조회만 하면 보고 있는 동안 생긴 것이 안 뜬다. `mergeAnomalies` 가 `anomaly_id` 로 합치며 **순수 함수라 클라우드 없이 테스트가 잠근다** |
| 보고서를 **DB 테이블로 만들지 않았다** | 클립 예약(FN-REC-03)과 달리 놓쳐도 증거가 사라지지 않는다 — 다시 요청하면 된다. 결과 캐시임을 코드에 적었다 |

### 화면을 실제로 켜서 확인한 것

실제 서버 · PostgreSQL · REC · 가짜 카메라 2대 · 브라우저에서 조작했다.
**클라우드 키는 설정하지 않았다** — 즉 아래 전부가 「클라우드 없는 현장」의 동작이다.

| 확인 | 결과 |
|---|---|
| `proximity_forklift`(우회 되돌린 뒤) 실행 | `resolved` · **`min_distance_m` 1.55** (같은 순간 접지점 거리는 2.90m) · `resolution_sec` 13초 · 클립 `ready` |
| 확정 → 방송 | **170ms** (로그 실측 · 클라우드 없음) |
| 이벤트 상세 규정 칸 | 제172조 · 제39조 · 제179조 — **클라우드와 무관하게 채워졌다** |
| 이벤트 상세 LLM · 유사 사례 칸 | 비어 있고, **왜 비었는지**가 화면에 적힌다 |
| `POST /search/scenes` (조건만) | `mode: "sql"` · 6건 · `similarity` 전부 `null` |
| `POST /assistant/chat` 3경로 | `sql` · `vector` · `vision` 모두 200. 통계 답변에 표 첨부 |
| 브리핑 (클라우드 없음) | 「프레임은 확보했으나 분석이 꺼져 있다」 — **「이상 없음」이라고 하지 않는다** |
| `POST /reports/weekly` → `GET /reports/{id}` | `generating` → `ready`. 집계 문장만으로 본문이 나왔다 |
| 분석 화면 추이 | `07-29` 는 시정률 `–` · 판정 불가율 100% — **0% 로 접히지 않았다** |
| 분석 화면 반복 순위 | 「추적 #3」 · 「1번 카메라 · 조립 라인」(DB `cameras.name`) · 「지게차 통행로」 |
| 분석 화면 대기 60초 요청 수 | **0건** (CPU 0.9%) — 이 화면은 폴링하지 않는다 |
| 챗봇 3회 조작 | 요청 **3건** · CPU 0.38초 |
| 서버 로그 WARNING 이상 | **0건** |

### 이상 탐지를 실제 경로로 돌린 것 (FN-AI-04)

`Embedder` **하나만** 결정적 대역으로 바꾸고 나머지는 실물 코드로 돌렸다 — REC 스냅샷
캡처 · 정상 풀 축적 · k-NN 점수 · 임계 판정 · `anomalies` 저장 · §5.3 발행 전부.

| 확인 | 결과 |
|---|---|
| 풀 축적 14회(하한 12) | 플래그 **0건** — 축적 초기의 큰 거리는 「이상」이 아니라 「모른다」다 |
| 평소와 다른 장면 1회 | 점수 **1.00** · 플래그 1건 · §5.3 `anomaly` 발행 · DB 저장 |
| `note` | `null` — LLM 이 없으면 설명이 안 붙는다(클라우드 미가용의 정상 모습) |
| 경고 방송 | **0건** — `AlertService` 를 부르지 않는다 |
| 실시간 관제 화면 | 앰버 배너 `rgb(245,158,11)` — 위반 적색과 다르다. 클릭 → `?cam=1` 전환 · 닫기 동작 |
| 분석 화면 | 「이상 탐지 (최근 7일)」 표에 시각·카메라·점수·「설명 없음 (클라우드 미가용)」 |

### 클라우드를 붙이고 잰 것 (실제 Gemini · 2026-08-01)

`.env` 에 키를 넣고 FN-AI 전량을 실제로 호출했다. 가짜 카메라 소스는
`media/sample.mp4`(실제 창고 영상 — 지게차·작업자·적재 자재)다.

| 확인 | 결과 |
|---|---|
| 기동 시 사례 임베딩 | KOSHA 8건 · `cloud.available = true` |
| FN-AI-05 심층 분석 | 규정 3 · 사례 3 · 임베딩 있음 · 분석문 있음 — **네 칸 전부** |
| 분석문의 사실성 | 준 사실만 인용(1.55m · 추적 3 · forklift_lane · 반복 5회 · 조항 3건). **없는 조항 번호를 만들지 않았다** |
| FN-AI-07 유사 사례 순위 | 지게차 협착 **0.758** > 지게차 후진 충돌 **0.723** > 보호구 미착용 **0.659** — 근접 이벤트에 지게차 사례가 먼저 온다 |
| FN-AI-02 자유 문장 검색 | `mode = hybrid` · 유사도 실림 · 유사도순 정렬 |
| FN-AI-02 조건 우선 | 「1번 카메라에서 …」 → 결과 카메라 `{1}` — 조건이 SQL 로 먼저 걸렸다 |
| FN-AI-08 챗봇 3경로 | `sql` · `vector` · `vision` 전부 의도한 경로로 |
| FN-AI-09 브리핑 | 실제 장면을 정확히 읽었다 — 지게차 운전자 · 노트북 든 보행 작업자 · 안전모 착용 · 근접 위험 |
| FN-AI-10 보고서 | `generating` → `ready` · 721자 3단락 서술 |
| FN-AI-04 이상 탐지 (실제 임베딩) | 깨끗한 풀에서 13회 축적 · **오탐 0건** |

**총 12개 검사 전량 통과.**

### 대화를 이어 보고 고친 것 (FN-AI-08)

사람이 실제로 챗봇을 쓰다가 찾은 것들이다. **API 응답은 200 이었고 문장도 그럴듯해서
자동 검사로는 전부 통과했다.**

| 무엇 | 왜 |
|---|---|
| **★ 「이번 주」라고 물어도 「오늘」로 답했다** | 라우터가 `summary()` 를 인자 없이 불러 넘겼다 — 항상 오늘치다. 문장은 그럴듯하고 숫자만 틀리므로 아무도 알아채지 못한다. 검색과 **같은 파서**(`parse_query`)로 질문에서 기간을 뽑아 그 구간으로 집계한다 |
| **★ 답변이 고정돼 보였다** | LLM 은 실제로 돌고 있었지만 **넣어주는 숫자가 매번 같은 오늘치**라 내용이 변하지 않았다. 「돌지 않는다」가 아니라 「같은 것만 준다」가 원인이었다 |
| **★ 후속 질의가 장면 검색으로 샜다** | 「각각 무슨 위반이야?」에 통계 신호가 없어 기본값(`vector`)으로 떨어졌다. ① 유형·내역 관련 말을 `sql` 신호에 넣고 ② 신호 없는 짧은 질의는 **앞 질문의 경로를 물려받게** 했다 |
| **★ 요약에 유형별 내역이 없었다** | `total_violations` 에는 유형이 없다. 분석 화면과 **같은 코드**(`aggregates.distribution`)로 유형별 건수를 함께 낸다 |
| **★ 화면을 떠나면 대화가 사라졌다** | 턴이 컴포넌트 state 였다. `sessionStorage` 로 옮기고(탭 한정 — `localStorage` 면 다음 날 대화가 살아나 서버 이력과 어긋난다) 「대화 지우기」를 두었다. 지울 때 **세션 ID 도 새로 만든다** |

검증 — 사용자가 겪은 대화를 그대로 재생했다.

| 질문 | 답변 |
|---|---|
| 「이번주에 얼마나 위반이 있었고, 무슨 위반들이 있었는지」 | **2026-07-25 ~ 지금** 82건 · 안전모 72 · 지게차 근접 7 · 금지구역 4 · 쓰러짐 2 |
| 「각각 무슨 위반이야?」 | 같은 기간 유지 · `sql` 경로 유지 · 앞 답변을 반복하지 않고 상태별로 답함 |
| 「그 중에 지게차 관련된 건 몇 건이야?」 | **「지게차 근접 7건」** — 앞 답변의 내역을 보고 답했다 |

### 클라우드를 붙여 보고 고친 것

| 무엇 | 왜 |
|---|---|
| **★ 키프레임 임베딩이 400 으로 실패했다** | `gemini-embedding-001` 은 **텍스트 전용**이다(`400 The text content is empty`). 한동안 **장면을 Flash 로 묘사한 뒤 그 문장을 임베딩**하는 두 단계로 우회했다 |
| **★ 다시 이미지를 직접 임베딩한다** | `gemini-embedding-2` 가 **멀티모달**이다 — 이미지·텍스트 모두 3072차원으로 나와 `halfvec(3072)` 을 그대로 쓴다(마이그레이션 없음). 우회를 걷어낸 이유는 비용(장당 2회 → 1회)보다 **묘사가 같으면 서로 다른 장면이 같은 벡터가 되던 것**이다 — 문장은 픽셀보다 훨씬 거친 요약이라 이상 탐지(FN-AI-04)가 볼 수 있는 차이가 그만큼 사라졌다. 묘사 프롬프트와 `describe()` 는 삭제했고, 벡터를 만드는 데 생성 모델이 끼지 않는 원래 역할 분리로 돌아왔다 |
| 실측 (키프레임 = 가짜 RTSP 컬러바) | 텍스트 질의 「컬러바 테스트 패턴 화면」 **0.48** · 「밤하늘의 별」 0.25 · 「제조현장 작업자와 지게차」 0.24 · 「바다에서 서핑」 0.23. 교차 모달 검색이 실제로 가른다. 서로 다른 키프레임 두 장은 0.91 |
| ⚠ **모델을 바꾸면 `normal_pool` 과 `events.embedding` 을 함께 비운다** | 벡터는 모델마다 다른 공간에 산다. `normal_pool` 을 안 비우면 새 모델의 첫 샘플들이 전부 「평소와 다르다」로 잡히고(k=5 이므로 다섯 주기), `events.embedding` 을 안 비우면 **옛 벡터를 가진 이벤트가 장면 검색에서 유사도 0 근처로 깔린다** — 실측으로 교체 직후 검색 결과에 옛 이벤트가 `0%` 로 섞여 나왔다. 텍스트 전용 모델이 설정되면 어댑터가 그 사실을 적어 올린다(`server/ai/gemini.py` `_embed`) |
| `.env` 의 키가 어댑터에 닿지 않았다 | `create_cloud()` 가 `os.environ` 을 직접 읽는데 pydantic-settings 는 `.env` 를 프로세스 환경에 넣지 않는다. **키를 적어도 조용히 「없다」로 떨어지고 사람은 키가 잘못된 줄 안다.** `ServerSettings.gemini_api_key` 로 옮겨 설정의 원천을 하나로 했다 |
| 보고서에 내부 라벨 `custom` 이 샜다 | 「금주 제조현장의 **custom 기준** 위반은 82건」이 나왔다. `MetricsSummary.period` 는 구간 지정 시 `"custom"` 이 되는 내부 값이라, 보고서는 자기 날짜 범위를 쓰게 했다 |

### 클라우드를 끊고 잰 것 (FN-SYS-03)

어댑터가 **붙어 있고 호출마다 2초 뒤 실패**하는 상황을 만들어 재측정했다. 지금까지의
실행은 「어댑터가 아예 없는」 경우였는데, 실제 장애는 이쪽이다 — 느린 실패가 루프를
잡아먹는지가 관건이기 때문이다.

| 항목 | 값 |
|---|---|
| 후보 → 확정·경고 (프레임 24장) | **1.0 ms** |
| 확정 → 해소 (프레임 110장 처리 포함) | **2.4 ms** |
| 클라우드 호출 | 1회 시도 · 전부 실패 (호출당 2초 지연) |
| 이벤트 최종 상태 | `resolved` · `resolution_sec` 10 |
| 규정 조항 | 2건 (사전 테이블 · 클라우드 무관) |
| `llm_analysis` | `None` — 실패가 **빈 칸으로만** 나타난다 |
| `cloud` 상태 | `available=false` · `last_error="연결 실패 (차단)"` |

**2초짜리 실패가 3건 걸렸는데도 확정과 해소가 밀리초 단위로 끝났다.** 분석이 배경
태스크이고 `EventService` 가 그것을 기다리지 않기 때문이다.

---

## 명세서 갱신 반영 (v12 · M5 에서 보고한 9건 전량)

| 항목 | 확정된 내용 | 반영 |
|---|---|---|
| **§4.4 클립 추출 타이밍** ★ | `confirmed_at + clip_post_roll_s + rec_segment_seconds + clip_extract_margin_s`. 세그먼트 길이가 **별도 항**이 됐고 그 값은 REC 의 `GET /status` 에서 읽는다 | `ClipService.set_segment_seconds` · `_watch_storage` 가 상태 폴링 응답에서 흘려보낸다(요청을 더 보내지 않는다) · 모르면 실행하지 않는다. DB 의 `clip_extract_margin_s` 를 12 → **2**(명세서 기본값)로 되돌렸다 |
| **§4.4 키프레임 · 스냅샷 버퍼** ★ | REC 이 초당 1장 · 최근 60초를 메모리에 유지. `GET /keyframe` 은 버퍼 안이면 즉시, 밖이면 세그먼트에서 | `recorder/snapshots.py`(순수 버퍼 + 샘플러) · `GET /keyframe` 이 버퍼를 먼저 본다. 확정 시각 요청이 500 → 200 |
| **§4.7 `recording` 절** | `segment_seconds` · `snapshot_fps` · `snapshot_window_s` 신설 | `RecRecordingStatus` · `RecorderService._recording()` |
| **§4.1 응답 3칸** | `clip_status` · `clip_error` · `alert_suppressed` 가 정식 계약이 됐다 | 「임시로 두었다」 주석을 지웠다 — 계약 자체는 그대로였다 |
| **§4.2 · §5.3 `suppressed`** | 둘 다에 실렸다 | `MetricMsg.suppressed` 신설 · 개요 화면이 `metric` 을 받고 **`GET /metrics/summary` 를 다시 부르던 것을 없앴다**(종결 전이마다 요청 하나) |
| **§3 `AlertCommand.type: manual`** | 수동 방송 전용 값이 생겼다 | `AlertCommandType = ViolationType \| "manual"` · 수동 방송이 `zone_intrusion` 을 빌려 쓰던 것을 없앴다 |
| **§3 `duration_s` 의 원천** | 정책 키 `alert_duration_s`(기본 5) | 서버 설정(`ALERT_DURATION_S`)에서 정책으로 옮겼다. `CLIP_MARGIN_S` 도 함께 서버 설정에서 사라졌다 |
| **§3 `fall` 등급 하한** ★ | 3 미만으로 설정할 수 없고 API 가 422 로 거부한다 | `server/domain/alerts.py`(`MINIMUM_LEVEL` · `check_level`) — 순수 함수 하나를 API 와 DB 읽기 경로가 함께 쓴다 |
| **§4.5 `GET`/`PUT /alert-sounds`** | 정의됐다 | `server/app/routes/sounds.py` · 저장 직후 캐시와 등급표를 즉시 갱신한다(주기 갱신 60초를 기다리지 않는다) |

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

#### M7 에서 새로 드러난 것

| 내용 | 상세 |
|---|---|
| ~~**★ `proximity` 해소 판정이 후보를 만든 거리와 다른 거리를 쓴다**~~ **해소됨** — §2.1 에 `frame.objects[].nearby[]`(`dist_m` · `basis` · `in_danger_zone`)가 신설됐다. 서버가 그 값으로 해소를 판정하고 오버레이 거리선도 같은 값을 쓴다. `proximity_forklift.yaml` 의 우회를 되돌렸고 실측 최근접 **1.55m** · 접지점 **2.90m** 로 경고 임계(2.0m)를 사이에 두고 갈리는 위치가 시나리오의 요점이 됐다 | 엣지는 **마스크 최근접**(`nearby[].dist_m` · §6.5)으로 후보를 올리는데, 서버의 해소 판정(§4.2 FN-EVT-03 「거리가 임계값 초과」)은 `frame` 의 **접지점↔`anchor` 거리**로 잰다. `frame`(§2.1)에 마스크 최근접이 실리지 않아서다. 두 값은 **FN-DET-09 가 존재하는 바로 그 상황**(포크가 뻗은 지게차)에서 갈린다 — 실측으로 최근접 1.55m · 접지점 거리 3.50m 였다. 그러면 엣지가 근접이라고 올린 순간에 서버는 「이미 해소」로 보아 확정에 도달하지 못한다. `sim/cases/proximity_forklift.yaml` 은 두 값이 함께 임계 안에 들도록 작업자를 더 가까이 세워 우회했다. **§2.1 `frame` 에 최근접 거리를 실을지, §4.2 해소 조건을 후보 기준으로 바꿀지 정해 달라** |
| ~~**§6 `zones` 에 `polygon`(픽셀) 칸이 없다**~~ **해소됨** — §6 `zones` 에 `polygon`(정규화 픽셀 원본)이 추가됐다 | §4.5 는 「두 표현을 모두 저장하고 반환한다」고 확정했는데 §6 테이블 목록에는 `polygon_m` 만 있다. 마이그레이션 `0007` 로 컬럼을 넣었고 `test_db_schema.py` 가 그 사실을 주석과 함께 잠갔다. §6 에 추가해 달라 |
| ~~**§6 `cameras` 에 `calib_points` · `reproj_error_m` 칸이 없다**~~ **해소됨** — 둘 다 §6 `cameras` 에 추가됐다 | §4.5 `GET /cameras` 는 둘 다 반환한다. 행렬만 남기면 설정 화면이 **어느 점을 찍었는지 복원할 수 없어** 한 점만 고치려 해도 네 점을 다시 찍어야 한다. 같은 마이그레이션으로 넣었다. §6 에 추가해 달라 |
| ~~**`ref_height_px_at_m` 이 응답에서는 스칼라인데 계산에는 두 값이 필요하다**~~ **해소됨** — §6 이 `ref_height`(jsonb · `{height_px, at_m}`)로 바꿨다. 마이그레이션 `0008` 이 컬럼 이름과 JSON 키를 함께 옮겼고, `GET /cameras` 가 객체를 그대로 반환하며, 설정 화면에 「기준 인물 찍기」(발끝·머리끝 두 점 + 실측 좌표)가 생겼다 | §4.5 `GET /cameras` 예시는 `"ref_height_px_at_m": 0.42` 로 **높이 하나**다. 그런데 기대 높이 곡선을 정하려면 「그 높이를 **어느 위치에서** 쟀는가」(`reference_person.at_m`)가 함께 있어야 한다. DB 는 `{px_height, at_m}` 을 통째로 들고 있고 응답에는 높이만 싣는다 — 설정 화면이 기준점 위치를 되그릴 수 없다. 응답에 위치를 함께 실을지 정해 달라 |
| ~~**정지 판정 임계 두 개의 자리**~~ **부분 해소** — `stillness_move_px`(0.008) · `stillness_window_s`(1.0)가 §4.5 정책 키로 승격됐다. 형태 변화 임계만 `edge/config.yaml` 에 남았다(카메라 설치에 종속). 창 방식으로 바뀌면서 쓰러짐 판정이 약 0.9초 늦어졌고(`fall_detected`: 7.5s → 8.375s) 시나리오 시각을 실제 게이지에 맞춰 옮겼다 | `stillness_move_max` · `stillness_shape_change_max` 는 §4.5 정책 키 목록에 없다. 카메라 화각·설치 높이에 종속되는 값이라 `edge/config.yaml` 의 `posture` 절에 두었다(지속 시간 `fall_stillness_s` 는 정책값 그대로다). 화면에서 조정할 값이라면 `policies` 로 옮겨야 한다 |

#### M8 에서 새로 드러난 것

| 내용 | 상세 |
|---|---|
| **★ §4.3 `SceneSearchItem.similarity` 가 필수인데 `mode:"sql"` 경로에는 유사도가 없다** | §4.3 은 세 경로(`sql` / `vector` / `hybrid`)를 정의하는데, `sql` 경로에는 질의 임베딩 자체가 없다 — 「지난주 1번 카메라 안전모」처럼 조건이 전부 구조화되면 벡터를 만들 이유가 없기 때문이다. 그런데 응답 항목의 `similarity` 는 필수 `float` 이라 **재지 않은 값을 채워야** 스키마를 만족한다. 계약을 `float \| None` 로 바꾸고 화면은 `null` 일 때 숫자를 그리지 않게 했다(`thumbnail_url` · `clip_url` 도 같은 이유로 nullable — 확정 직후에는 키프레임·클립이 아직 없다). **§4.3 예시가 `hybrid` 응답이라 이 칸이 채워져 있는 것이니, `sql` 경로의 표기를 정해 달라** |
| **§4.5 `GET /cameras` 예시가 아직 `ref_height_px_at_m` 스칼라다** | §6 은 `ref_height`(jsonb · `{height_px, at_m}`)로 바꿨는데 §4.5 응답 예시(773행 부근)는 옛 이름과 스칼라 그대로다. 구현은 **§6 을 따랐다**(사용자 지시). §4.5 예시도 함께 고쳐 달라 |
| **요청과 저장의 이름이 다르다 — `px_height` 대 `height_px`** | §4.5 `POST /cameras/{id}/calibration` 의 `reference_person.px_height` 와 §6 `cameras.ref_height.height_px` 가 같은 값인데 이름이 뒤집혀 있다. 라우터 경계에서 한 번만 바꾸고 그 사실을 주석에 적었다. 한쪽으로 통일할지 정해 달라 |
| **§4.4 에 보고서 조회 경로가 없다** | `POST /reports/weekly` 가 `report_id` 를 돌려주는데 그것으로 받아올 경로가 §4.4 에 없다. `GET /reports/{report_id}` 를 같은 이름 공간에 두었다(`status` · `body` · `stats`). 경로와 스키마를 정해 달라 |
| **이상 탐지 임계값이 명세서에 없다** | §6.8 은 「임계 초과 시 이상 플래그」라고만 적는다. 판정 임계(0.35) · k(5) · 최소 풀 크기(12) · 시간대 버킷(3시간)을 서버가 정했고 `server/ai/service.py` 상수로 두었다. 현장에서 조정할 값이라면 `policies` 로 올려야 한다 |
| **`anomaly.keyframe_url` 을 채우지 않는다** | §5.3 `anomaly` 는 `keyframe_url` 을 정의하지만, 이상 프레임을 `media/` 에 저장하는 규칙이 §4.4 에 없다(그쪽은 이벤트 클립·키프레임 전용이다). 지금은 `null` 로 보낸다 — 없는 URL 을 문자열로 내보내지 않는 §5.2 규약과 같은 처리다. 저장 위치를 정해 달라 |
| **§6 `normal_pool` 에 임베딩 모델 이름이 없다** | 벡터는 모델마다 다른 공간에 산다. 모델을 바꾸면 옛 벡터가 남아 새 모델의 첫 샘플들이 전부 「평소와 다르다」로 잡힌다 — **실측으로 4회 연속 오탐**이 났다(k=5 라 풀이 새 벡터로 채워질 때까지 이어진다). 지금은 사람이 `DELETE FROM normal_pool` 로 비운다. 서버가 알아서 비우게 하려면 행에 모델 이름을 함께 저장해야 하고, 그건 §6 에 칸을 늘리는 일이다. 추가할지 정해 달라 |
| **★ §4.4 에 대화 이력의 자리가 없다** | `session_id` 를 받는데 그것으로 무엇을 하는지 명세서에 없어서, 서버가 아무것도 기억하지 않고 있었다 — 그 결과 「이번 주 위반 몇 건」 다음의 「각각 무슨 위반이야?」가 장면 검색으로 새고 답변은 매번 같은 오늘치였다. 서버가 세션별 최근 8턴을 들고 프롬프트에 싣게 했고(상한 50세션), 비울 자리로 `DELETE /assistant/chat/{session_id}` 를 두었다. §4.4 에 이력 규약과 삭제 경로를 정해 달라 |
| **★ §4 에 `GET /anomalies` 가 없다** | §5.3 은 `anomaly` **발행**만 정의한다. 발행만으로는 새로고침한 화면과 서버가 죽어 있던 동안의 이상을 볼 수 없다 — 화면이 메시지를 놓친 것과 이상이 없었던 것이 같아 보인다. `GET /anomalies?days=&limit=`(`AnomalyListResponse`)를 지표 라우터에 두었고, 응답 원소는 §5.3 `anomaly` 에서 `type` 만 뺀 것과 같다. §4 에 추가할지 정해 달라 |

#### M6 에서 드러나 아직 열려 있는 것

M5 에서 보고한 9건은 **전부 명세서에 반영되어 해소됐다**(위 「명세서 갱신 반영 (v12)」).
아래는 M6 에서 새로 드러난 것들이며, 전부 **명세서가 요구하는 기능을 구현하려는데 둘
자리가 없어서** 서버가 임시로 정한 것이다. 코드에는 그 사실을 주석으로 표시해 두었다.

| 내용 | 상세 |
|---|---|
| ~~**§4.5 에 캘리브레이션 조회 경로가 없다**~~ **해소됨** — `GET`/`PATCH /cameras` 가 §4.5 에 정의됐다 | `POST /cameras/{cam_id}/calibration` 은 있는데 그 결과를 다시 읽을 곳이 없다. 설정 화면(FN-UI-07)은 저장된 구역을 영상 위에 다시 그려야 하는데 `zones.polygon_m` 은 지면 좌표라 **호모그래피 없이는 화면에 그릴 수 없다** — `POST` 응답만으로는 새로고침 뒤에 아무것도 그리지 못한다. `GET /cameras`(`cam_id` · `name` · `homography` · `ref_height_calibrated` · `calibrated_at`)를 만들어 두었다(`CameraCalibration`). §4.5 에 추가할지 정해 달라 |
| ~~**`POST /zones` 에 픽셀 폴리곤 자리가 없다**~~ **해소됨** — 요청이 정규화 픽셀 `polygon` 으로 확정됐고 `polygon_m` 은 클라이언트가 보내지 않는다 | §4.5 는 「화면에서 그린 픽셀 좌표를 **서버가** 호모그래피로 변환해 저장」한다고 적었는데, 요청 예시에는 `polygon_m`(미터)만 있다. 미터만 받으면 변환을 클라이언트가 해야 하고, 그러면 호모그래피 적용 코드가 `packages/vision` 과 프론트 두 곳에 생긴다. `ZoneUpsertRequest` 에 `polygon`(정규화 픽셀)을 두고 **둘 중 정확히 하나만** 받게 했다(§1.2 좌표 규약대로 접미사 없는 이름이 픽셀이다). §4.5 요청 스키마를 정해 달라 |
| ~~**`DELETE /zones/{zone_id}` 가 §4.5 에 없다**~~ **해소됨** — §4.5 에 정의됐다 | §5.4 는 `zone_updated.action: "delete"` 를 정의하는데 그 전이를 일으킬 REST 경로가 없다. 설정 화면에서 구역을 지울 수 없으면 잘못 그린 구역이 영구히 남는다. `DELETE /zones/{zone_id}?cam_id=` 로 두었다 — `cam_id` 는 §5.4 가 메시지 최상위에 요구하기 때문이다 |
| **카메라 표시 이름의 원천이 둘이다** | §6 `cameras.name` 이 있는데 프론트 `labels.ts` 에도 표가 박혀 있다(`CAMERA_NAMES`). 설정 화면만 `GET /cameras` 의 값을 쓰게 했고 나머지 화면은 아직 코드의 표를 쓴다 — 같은 카메라가 화면마다 다른 이름으로 보인다. 절대규칙 6 대로라면 전부 DB 값이어야 한다. `GET /cameras` 가 §4.5 에 확정되면 함께 정리하겠다 |
| ~~**§4.4 「초당 1장은 무시할 수준」이 소프트웨어 디코딩에서는 성립하지 않는다**~~ **해소됨(M7)** — 명세서가 비트스트림 보관 방식으로 재설계됐고 `REC_SNAPSHOT_KEYFRAMES_ONLY` 는 제거됐다. 스냅샷 CPU 66% → 2.4%. 아래는 그때의 기록이다 | 비용은 인코딩이 아니라 **디코딩**이다(실측: 1080p 한 대에 코어 33% · 카메라 2대면 66%). 젯슨은 NVDEC 이 있어 전제가 성립하지만 개발 노트북은 아니다. `REC_SNAPSHOT_KEYFRAMES_ONLY`(기본 끔)를 두었고 켜면 코어 7% 로 내려가되 **샘플 간격이 스트림 GOP 를 따른다** — §4.4 가 보장한 「최대 0.5초 차이」가 GOP 2초에서는 최대 1초가 된다. 개발 환경 기본값을 켬으로 바꿀지, §4.4 에 「하드웨어 디코딩 전제」를 명시할지 정해 달라 |
| `alert_sounds` 의 **표시 이름과 키를 화면이 자유롭게 바꾼다** | `PUT /alert-sounds/{violation_type}` 은 `file_path` 를 문자열로 받는다. 존재하지 않는 파일을 저장해도 API 는 성공하고, 그 사실은 **다음 경고 때** 로그로만 드러난다(`SoundLibrary` 가 파일 없음을 ERROR 로 남긴다). 저장 시점에 파일 존재를 검사해 422 로 막을지 정해 달라 — 막으면 파일을 먼저 올려야 하는 순서 제약이 생긴다 |

### B. 개발 환경에서 발견한 것 (명세서 사안 아님)

| 내용 | 상세 |
|---|---|
| `.env` 의 `REC_RETENTION_DAYS=0.0417` | 보존 정책 시험 때 1시간으로 줄여둔 값이 남아 있다. 화면의 「녹화 · 보존 **0일**」이 그래서 나온다. 운용값은 7 이다 |
| 이전 세션의 브라우저 탭이 살아 있었다 | 설정 화면만 열어 두었는데 `GET /alerts/mute` 가 60초에 3건씩 들어왔다. 다른 탭의 실시간 관제(FN-UI-02)가 120초마다 카메라 수 + 1 만큼 묻는 것이며, 현재 화면과는 무관하다 |

### C. 판단이 필요했던 타입

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
