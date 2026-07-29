"""확정 → 경고 방송 시작 실측. FN-ALM-01 (요구: **1초 이내**)

    uv run python -m scripts.measure_alert_latency
    uv run python -m scripts.measure_alert_latency --rounds 50 --backend none

무엇을 재는가:

```
candidate.ts (관측 시각)  ──서버 전 구간──▶  재생 시작
   └ 상태머신 확정 판정 · 저장 · §5.2 발행 · 음원 조회 · 장치 열기
```

**기준점은 관측 시각이다**(`candidate.ts`). 서버가 메시지를 받은 시각을 쓰면 네트워크
지연이 예산에서 빠져 실제보다 좋아 보인다 — 현장에서 사람이 겪는 것은 "위반이 3초
지속된 순간부터 스피커가 울릴 때까지"이므로 그쪽을 재야 한다.

**실시간으로 돈다.** `FakeClock` 을 쓰면 잰 값이 0 이 되어 아무 의미가 없다. 다만
확정 지속시간(`confirm_duration_s`)만 짧게 줄인다 — 재는 구간은 확정 **이후**이므로
3초를 실제로 기다릴 이유가 없고, 그 3초는 요구 예산에 포함되지도 않는다.

`--backend` 는 `.env` 의 `AUDIO_BACKEND` 와 같은 값이며, 기본은 실제 재생기다.
사운드 장치가 없는 기계에서 `none` 으로 재면 **재생 시작 비용이 빠진 숫자**가 나오므로
보고할 때 그 사실을 함께 적는다.

`--store db` 를 주면 메모리 대신 **실제 PostgreSQL** 에 쓴다. 경고 발행 앞에 DB 쓰기가
있으므로(`EventService._apply` — 저장 · 발행 · 경고 순), 그 비용까지 포함한 값이 현장에서
실제로 겪는 숫자다. 기본값(`memory`)은 DB 없이도 재생 경로만 재기 위한 것이다.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import statistics
import sys
from datetime import datetime
from typing import Any

from aegis_contracts import CandidateMsg, Policies, SpecModel
from aegis_vision.clock import RealClock
from server.app.alert_service import LATENCY_BUDGET_MS, AlertService
from server.app.config import get_server_settings
from server.app.event_service import EventService
from server.domain.event_machine import EventMachine
from server.domain.mcu_state import McuRuntime
from server.domain.overlay import LiveTracks
from server.infra.audio import SoundLibrary, resolve_player
from sim.case_check import CaseSounds, CaseStore

if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 확정 판정에 쓰는 지속시간(초). **재는 구간 밖이다** — 짧게 줄여 반복 횟수를 벌기 위한
#: 값이며, 이 값이 결과에 들어가지 않는다는 것이 이 스크립트의 전제다.
CONFIRM_S = 0.05

#: 라운드 사이 간격(초). 앞 라운드의 재생이 끝날 시간을 준다. 겹쳐 틀면 장치가 앞
#: 소리를 끊고 다음 것을 트는데, 그때의 열기 비용은 평소와 다르다.
GAP_S = 0.3


def _candidate(track_id: int, at: datetime) -> CandidateMsg:
    """§2.2 후보 하나. 시각만 바꿔 두 번 보내면 확정 조건이 찬다."""
    body: dict[str, Any] = {
        "type": "candidate",
        "cam_id": 1,
        "ts": at,
        "track_id": track_id,
        "violation_type": "no_helmet",
        "zone_id": "forklift_lane",
        "bbox": [0.197, 0.364, 0.273, 0.764],
        "conf": 0.91,
        "foot_point_m": [4.21, 7.85],
        "foot_conf": 0.88,
        "helmet": "off",
        "helmet_conf": 0.88,
        "posture": "standing",
        "observed_ms": 500,
        "nearby": [],
    }
    return CandidateMsg.model_validate(body)


async def measure(rounds: int, backend: str, store_kind: str) -> tuple[list[float], str]:
    """`rounds` 번 확정시켜 방송 시작까지의 지연을 모은다."""
    clock = RealClock()
    settings = get_server_settings()
    player = resolve_player(backend)
    store: Any = CaseStore()
    if store_kind == "db":
        from server.infra.db.repository import DbEventRepository
        from server.infra.db.session import create_db_engine

        store = DbEventRepository(create_db_engine())

    async def publish(message: SpecModel) -> None:
        # 대시보드 전송 자리다. 실서버에서는 소켓 쓰기가 여기 들어가지만, 그것은
        # 경고 발행보다 **뒤에** 일어나므로 이 측정에 포함되지 않는다.
        del message

    alerts = AlertService(
        library=SoundLibrary(settings.audio_dir, CaseSounds()),
        player=player,
        clock=clock,
        mcu=McuRuntime(),
        mqtt=None,
        publish=publish,
    )
    await alerts.start()

    service = EventService(
        machine=EventMachine(
            clock=clock,
            policies=Policies(confirm_duration_s=CONFIRM_S),
        ),
        tracks=LiveTracks(),
        publish=publish,
        clock=clock,
        store=store,
        policies=None,
        alerts=alerts,
    )

    for index in range(rounds):
        # 트랙을 매번 바꾼다. 같은 트랙이면 두 번째부터 진행 중 이벤트에 병합되어
        # 확정이 일어나지 않는다(FN-EVT-01).
        track = 100 + index
        await service.on_candidate(_candidate(track, clock.now()))
        await asyncio.sleep(CONFIRM_S + 0.01)
        await service.on_candidate(_candidate(track, clock.now()))
        await asyncio.sleep(GAP_S)

    return alerts.latencies_ms, player.name


def _report(samples: list[float], backend: str, rounds: int, store_kind: str) -> int:
    if not samples:
        print("측정된 방송이 없다. 음원이 없거나 재생기가 실패했다 — 위 ERROR 로그를 봐라.")
        return 1

    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    print()
    print(
        f"확정 → 방송 시작 실측  ({len(samples)}/{rounds} 회 · "
        f"재생기 {backend} · 저장소 {store_kind})"
    )
    print(f"  중앙값   {statistics.median(ordered):7.2f} ms")
    print(f"  평균     {statistics.fmean(ordered):7.2f} ms")
    print(f"  최소     {ordered[0]:7.2f} ms")
    print(f"  p95      {p95:7.2f} ms")
    print(f"  최대     {ordered[-1]:7.2f} ms")
    print(f"  요구     {LATENCY_BUDGET_MS:7.0f} ms 이내 (FN-ALM-01)")

    over = [value for value in ordered if value > LATENCY_BUDGET_MS]
    if over:
        # 넘긴 것을 평균 뒤에 숨기지 않는다. 한 번이라도 넘겼으면 넘긴 것이다.
        print(f"  ★ 요구 초과 {len(over)}회 (최대 {max(over):.2f} ms)")
        return 1
    print("  ★ 전 구간 요구 이내")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="확정 → 방송 시작 지연 실측 (FN-ALM-01)")
    parser.add_argument("--rounds", type=int, default=30)
    parser.add_argument(
        "--store",
        default="memory",
        choices=("memory", "db"),
        help="db 를 주면 실제 PostgreSQL 쓰기 비용까지 포함해 잰다",
    )
    parser.add_argument(
        "--backend",
        default="auto",
        help="auto(기본) · winsound · ffplay/aplay/paplay · none. `none` 은 재생 비용이 빠진다",
    )
    args = parser.parse_args(argv)

    samples, backend = asyncio.run(measure(args.rounds, args.backend, args.store))
    return _report(samples, backend, args.rounds, args.store)


if __name__ == "__main__":
    sys.exit(main())
