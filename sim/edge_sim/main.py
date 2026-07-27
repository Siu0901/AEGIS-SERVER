"""가짜 젯슨 — `/ws/edge` WebSocket 클라이언트.

    uv run python -m sim.edge_sim.main --case no_helmet_resolved
    uv run python -m sim.edge_sim.main --case no_helmet_resolved --speed 4
    uv run python -m sim.edge_sim.main --mode logreplay --case run-2026-08-14.jsonl

**엣지는 판단하지 않는다.** 여기서 하는 일은 시나리오에 적힌 메시지를 시각에 맞춰
`aegis_contracts` 스키마로 보내는 것뿐이고, 확정·경고·시정판정은 전부 서버가 한다.

시각은 `Clock` 에서만 얻는다(CLAUDE.md 절대규칙 1).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import websockets

from aegis_vision.clock import Clock, RealClock

from .logreplay import load_log
from .scripted import ScheduledMessage, load_case

__all__ = ["main", "run"]

DEFAULT_URL = "ws://localhost:8000/ws/edge"


def _build_timeline(mode: str, case: str, clock: Clock) -> list[ScheduledMessage]:
    start = clock.now()
    if mode == "scripted":
        return load_case(case, start)
    return load_log(case, start)


async def run(
    *,
    url: str,
    mode: str,
    case: str,
    speed: float,
    clock: Clock,
) -> None:
    timeline = _build_timeline(mode, case, clock)
    print(f"[edge_sim] {mode}:{case} — 메시지 {len(timeline)}건, 배속 {speed}x → {url}")

    async with websockets.connect(url) as socket:
        origin = clock.monotonic()
        for item in timeline:
            due = origin + item.at_s / speed
            delay = due - clock.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)

            # exclude_unset: 시나리오가 적지 않은 필드는 보내지 않는다. "게이트 미통과 시
            # `helmet` 필드 자체를 생략"하는 규약(§6.3)이 이 방식으로 표현된다.
            payload = item.message.model_dump_json(by_alias=True, exclude_unset=True)
            await socket.send(payload)
            print(f"[edge_sim] +{item.at_s:>6.2f}s  {item.message.type}")

    print("[edge_sim] 시나리오 종료")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="가짜 젯슨 — /ws/edge 로 엣지 메시지를 보낸다")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"기본 {DEFAULT_URL}")
    parser.add_argument(
        "--mode",
        choices=("scripted", "logreplay"),
        default="scripted",
        help="scripted=시나리오 yaml / logreplay=JSONL 로그 재생",
    )
    parser.add_argument("--case", required=True, help="시나리오 이름 또는 파일 경로")
    parser.add_argument("--speed", type=float, default=1.0, help="재생 배속 (기본 1.0)")
    args = parser.parse_args(argv)

    if args.speed <= 0:
        parser.error("--speed 는 0보다 커야 한다")

    try:
        asyncio.run(
            run(
                url=args.url,
                mode=args.mode,
                case=args.case,
                speed=args.speed,
                clock=RealClock(),
            )
        )
    except KeyboardInterrupt:
        print("\n[edge_sim] 중단")
        return 130
    except (FileNotFoundError, NotImplementedError, ValueError) as exc:
        print(f"[edge_sim] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
