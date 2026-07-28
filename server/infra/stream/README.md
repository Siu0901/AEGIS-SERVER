# server/infra/stream

1080p 메인 스트림의 **연결 상태 관측**(FN-REC-01 · FN-SYS-01).

mediamtx 제어 API(`MEDIAMTX_API`, 기본 `http://localhost:9997`)를 폴링해
`cam{N}/main` 경로가 살아 있는지 보고, 상태가 **변할 때만** `/ws/dashboard` 로
`system` 메시지를 보낸다(API명세서 §5.3, `component == "camera"`).

| 파일 | 역할 |
|---|---|
| `mediamtx.py` | 제어 API 클라이언트. 경로별 `ready` 여부만 읽는다 |
| `watcher.py` | 폴링 루프와 `StreamState` 전이. 변화분만 발행한다 |

**여기에 녹화와 용량 관리를 넣지 않는다.** 7일 링버퍼(FN-REC-02)와 저장 용량
관리(FN-REC-05)는 REC 컴포넌트(`recorder/`) 소관이다 — 운용 시 녹화 디스크는
서버가 아니라 엣지 NVMe SSD 에 있고, 서버는 HTTP(§4.7)로만 접근한다
(기능명세서 §4.4 「녹화 컴포넌트(REC) 분리」).

**서브 스트림은 여기서 보지 않는다.** 서브(640×360, 추론용)를 구독하는 것은
엣지이고 서버는 `heartbeat`(§2.4)로 전해 듣는다. 메인이 끊겨도 추론은 계속되고
서브가 끊겨도 녹화는 계속되므로, 관측 주체가 다른 두 값을 합치지 않는다(§4.6).
