"""라이브 재스트리밍 감시 (FN-REC-01 · FN-SYS-01).

**녹화와 용량 관리는 여기 없다.** REC 컴포넌트(`recorder/`) 소관이다
(기능명세서 §4.4 「녹화 컴포넌트(REC) 분리」). 이 패키지가 하는 일은 하나다 —
mediamtx 제어 API 를 폴링해 **메인 스트림이 살아 있는지 관측**하고, 변화가 있을 때만
`/ws/dashboard` 로 알린다.

서브 스트림(`sub_state`)은 여기서 보지 않는다. 서브는 엣지가 구독하는 것이고,
서버는 `heartbeat`(§2.4)로 전해 듣는다. 관측 주체가 다르면 상태도 따로 둔다(§4.6).
"""

from server.infra.stream.mediamtx import MediaMtxClient, PathState
from server.infra.stream.watcher import StreamWatcher, main_path

__all__ = ["MediaMtxClient", "PathState", "StreamWatcher", "main_path"]
