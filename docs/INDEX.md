# AEGIS 진척표 · FN-ID 내비게이션

`docs/AEGIS_기능명세서.md` §4의 모든 기능(56개)을 코드 위치·마일스톤과 함께 묶은 표다.
**작업을 마칠 때마다 해당 행의 상태를 갱신한다.**

| 표기 | 뜻 |
|---|---|
| ⬜ | 미착수 |
| 🟡 | 진행 중 |
| ✅ | 완료 (`make verify` 통과 + 테스트 존재) |
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
| **M5** | 관제 화면 P0 | 개요 · 실시간 관제(오버레이 정합) · 이벤트 · `make types` |
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
| FN-DET-01 | 영상 수신 및 하드웨어 디코딩 (NVDEC) | P0 | EDGE | 기능 §4.1 | M9 (sim: M2) | `edge/capture.py` · `sim/edge_sim/` | ⬜ |
| FN-DET-02 | 1단계 객체 감지 (person·vehicle 단일 모델) | P0 | EDGE | 기능 §4.1 | M9 | `edge/detect.py` | ⬜ |
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
| FN-REC-01 | 라이브 재스트리밍 (1080p 메인) | P0 | SRV | 기능 §4.4 | M1 | `server/infra/stream/` · `deploy/mediamtx.yml` | ⬜ |
| FN-REC-02 | 7일 링버퍼 녹화 | P0 | SRV | 기능 §4.4 | M1 | `server/infra/stream/` · `media/` | ⬜ |
| FN-REC-03 | 이벤트 클립 · 키프레임 추출 | P0 | SRV | 기능 §4.4 | M3 | `server/infra/clip/` | ⬜ |
| FN-REC-04 | 이벤트 DB 저장 | P0 | SRV | 기능 §4.4 · §6 | M1 | `server/infra/db/repository.py` | ⬜ |
| FN-REC-05 | 저장 용량 관리 | P1 | SRV | 기능 §4.4 | M3 | `server/infra/stream/retention.py` | ⬜ |

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
| FN-UI-02 | 실시간 관제 — 2채널 라이브 + 오버레이 · 수동 방송 | P0 | WEB | 기능 §4.6 · API §5 | M5 | `front/src/pages/LivePage.tsx` | ⬜ |
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

## 4.8 시스템 (FN-SYS) · 5건

| FN-ID | 기능명 | 우선 | 계층 | 명세 위치 | 마일스톤 | 코드 위치(예정) | 상태 |
|---|---|---|---|---|---|---|---|
| FN-SYS-01 | 구성요소 상태 감시 (엣지·카메라·MCU·클라우드·저장소) | P0 | SRV | 기능 §4.8 · API §4.6 | M1 | `server/app/routes/system.py` | ⬜ |
| FN-SYS-02 | 시각 동기화 (NTP · 클립 정합의 전제) | P0 | SRV/EDGE | 기능 §4.8 | M1 | `server/app/routes/system.py` · `edge/` | ⬜ |
| FN-SYS-03 | 클라우드 장애 격리 | P1 | SRV | 기능 §4.8 | M7 | `server/ai/adapter.py` | ⬜ |
| FN-SYS-04 | 지표 집계 (시정률 · 평균 시정 시간 · 판정 불가율 · 분포) | P0 | SRV | 기능 §4.8 · API §4.2·§6.7 | M4 | `server/domain/metrics.py` | ⬜ |
| FN-SYS-05 | 판정 불가 집계 (`expired` 별도 집계) | P0 | SRV | 기능 §4.8 · API §6.7 | M4 | `server/domain/metrics.py` | ⬜ |

> `expired` 는 **시정률 분모·분자 모두에서 제외**하고 `undetermined_rate` 로 따로 집계한다.
> 두 숫자는 **항상 병기**한다 — `방송 후 시정률 87% (판정 불가 5%)`.
> `fall` 과 `is_false_positive` 도 시정률에서 전량 제외한다.

---

## M0 산출물 (계약·뼈대)

FN-ID가 붙지 않는 기반 작업이다. 전부 완료되었고 `make verify` 가 통과한다.

| 항목 | 위치 | 근거 | 상태 |
|---|---|---|---|
| 계약 스키마 (§2~§5 전량) | `packages/contracts/src/aegis_contracts/` | API명세서 전 절 | ✅ |
| 명세서 예시 JSON 회귀 테스트 | `packages/contracts/tests/test_spec_examples.py` | API §2·§3·§4.5·§5 | ✅ |
| `Clock` 프로토콜 · FakeClock | `packages/vision/src/aegis_vision/clock.py` | CLAUDE.md 절대규칙 1 | ✅ |
| DB 스키마 (7테이블) · 초기 마이그레이션 | `server/infra/db/` | 기능명세서 §6 | ✅ |
| 정책값 시드 | `scripts/seed_policies.py` | API §4.5 | ✅ |
| 리포지토리 프로토콜 | `server/domain/repository.py` | — | ✅ |
| 개발 스택 (postgres·redis·mosquitto·mediamtx) | `docker-compose.yml` · `deploy/` | — | ✅ |
| 가짜 엣지 · 가짜 MCU | `sim/` | API §2·§3 | ✅ |
| 검증 파이프라인 | `Makefile` · `scripts/verify.sh` | — | ✅ |
| 프론트 라우팅·레이아웃 뼈대 | `front/` | 기능 §4.6 · 부록 B | ✅ |

---

## 명세서 확인 필요

명세서를 SSOT로 두고 **코드에서 임의로 채우지 않은** 항목이다. 사람이 판단해
명세서를 갱신하면 그때 코드에 반영한다(CLAUDE.md 절대규칙 8).

### A. §6 데이터 모델에 컬럼이 없어 §4 응답을 채울 수 없는 값

| 값 | 요구하는 곳 | 문제 |
|---|---|---|
| `zones.name` | API §4.5 `GET /zones` 응답 | §6 `zones` 에 `name` 컬럼이 없다. 화면에 "지게차 통행로"를 표시할 근거가 저장되지 않는다 |
| `events.height_ratio` | API §4.1 `GET /events/{id}` | §6 `events` 에 컬럼이 없다(`stillness_s` · `posture` 는 있다) |
| `events.nearby_snapshot` | API §4.1 `GET /events/{id}` | 확정 시점 주변 지게차 스냅샷을 저장할 컬럼이 §6에 없다 |
| `events.similar_incidents` | API §4.1 | 조회 시 임베딩으로 매번 계산하는 것인지, 저장하는 것인지 불명확 |
| `events.confirmed_at` 대응 REST 필드 | §6에는 있으나 API §4.1 응답에는 없다 | 타임라인에는 상태만 있고 확정 시각이 응답에 노출되지 않는다 |

### B. 타입·필수 여부가 불명확했던 필드 (contracts 작성 중)

| 필드 | 위치 | 판단한 내용과 근거 |
|---|---|---|
| `events.keyframe_paths` | 기능 §6 | 타입이 `text` 인데 이름은 복수형이고 API §4.1은 `keyframe_urls` **배열**을 반환한다. **§6대로 `text` 로 두었다.** 배열이 맞다면 `jsonb` 로 바꿔야 한다 |
| `frame.objects[].helmet_conf` · `helmet_checked_at` | API §2.1 | `helmet` 은 "생략" 표기가 있으나 이 둘에는 없다. `helmet` 에 종속된 값이므로 **선택**으로 두었다 |
| person 전용 필드 전반 (`foot_point` 등) | API §2.1 | 표에 필수 표시가 없다. `helmet`(생략) · `in_zone`(null) 만 명시적 표기가 있으므로 **나머지는 필수**로 해석했다 |
| vehicle 전용 필드 (`anchor_m` · `moving` · `danger_radius_m`) | API §2.1 | 같은 이유로 **필수**로 해석했다 |
| `candidate` 의 `cam_id` · `ts` · `bbox` · `conf` · `foot_conf` | API §2.2 | 필드 설명표에는 없고 예시 JSON에만 있다. 예시대로 **필수**로 두었다 |
| `GET /events` 의 `from` · `to` | API §4.1 | 날짜인지 시각인지 불명확. `POST /search/scenes` 는 날짜(`2026-08-05`)를 쓴다. 이벤트는 **시각(datetime)** 으로 해석했다 |
| `metrics/timeseries` · `distribution` · `repeat` 응답 | API §4.2 | **응답 스키마가 없다.** 창작하지 않고 쿼리 모델만 정의했다 |
| `assistant/chat` 의 `attachments[]` | API §4.4 | 원소 스키마가 없다. `dict` 로 열어 두었다 |
| WS `overlay` · `event_created` · `metric` · `anomaly` · `system` | API §5 | `event_updated` 외에는 전체 JSON이 없다. 한 줄 설명이 가리키는 기존 스키마를 재사용했다(예: `metric` → `MetricsSummary`) |
| `AlertCommand.level` | API §3 | 값 범위가 1·2·3 이라고 산문에 적혀 있으나 타입은 `int` 다. `int` 로 두었다 |

### C. 문서 간 표기 불일치

| 내용 | 상세 |
|---|---|
| FN-DET 개수 | `CLAUDE.md` 문서 지도는 **FN-DET-01~13**, 기능명세서 §4.1은 **01~12** 까지만 정의한다. 이 표는 명세서를 따라 12건으로 만들었다 |
| FN-SYS 순서 | 기능명세서 §4.8 표가 `01·02·03·**05**·04` 순서로 적혀 있다 |
| 디자인 시안 파일명 | `CLAUDE.md` · 부록 A-1 은 `docs/front_design.pdf`, 실제 파일은 `docs/AEGIS_front_design.pdf` |
| `sub` 스트림 해상도 | "640p" 로만 적혀 있어 640×360인지 640×480인지 불명확하다. 메인이 16:9 1080p이므로 `deploy/fake_cams.sh` 는 **640×360** 을 기본으로 두었다(`SUB_SIZE` 로 변경 가능) |
| 카메라 송출 fps | 엣지 처리 목표는 8fps 이상인데 카메라 자체 fps는 명시가 없다. `fake_cams.sh` 는 **15fps** 를 기본으로 둔다(`FPS` 로 변경 가능) |
