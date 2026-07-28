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
import io
import sys

import websockets

from aegis_vision.clock import Clock, RealClock

from .logreplay import load_log
from .scripted import ScheduledMessage, load_case

__all__ = ["main", "run"]

# `tasks.py sim` 이 이 모듈을 자식으로 돌리면 출력이 파이프가 되고, 그때 파이썬은
# 콘솔 코드페이지가 아니라 로케일 인코딩(한글 Windows 는 cp949)을 쓴다. 그러면 '—'
# 하나에 UnicodeEncodeError 로 죽어서 **시나리오가 시작도 못 한 채 실패**한다.
# tasks.py · scripts/seed_policies.py 와 같은 처리다.
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_URL = "ws://localhost:8000/ws/edge"


def _build_timeline(mode: str, case: str, speed: float, clock: Clock) -> list[ScheduledMessage]:
    start = clock.now()
    if mode == "scripted":
        return load_case(case, start, speed)
    return load_log(case, start)


async def run(
    *,
    url: str,
    mode: str,
    case: str,
    speed: float,
    clock: Clock,
) -> None:
    timeline = _build_timeline(mode, case, speed, clock)
    print(f"[edge_sim] {mode}:{case} — 메시지 {len(timeline)}건, 배속 {speed}x → {url}")

    async with websockets.connect(url) as socket:
        origin = clock.monotonic()
        frames = 0
        for item in timeline:
            # `at_s` 는 이미 배속이 반영된 값이다 — `ts` 와 같은 축이어야 한다.
            due = origin + item.at_s
            delay = due - clock.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)

            # exclude_unset: 시나리오가 적지 않은 필드는 보내지 않는다. "게이트 미통과 시
            # `helmet` 필드 자체를 생략"하는 규약(§6.3)이 이 방식으로 표현된다.
            payload = item.message.model_dump_json(by_alias=True, exclude_unset=True)
            await socket.send(payload)

            # `frame` 은 8fps 로 흐르므로 전부 찍으면 후보·소실이 묻힌다. 흐름이 보일
            # 만큼만 남기고, 사람이 실제로 봐야 하는 메시지는 매번 찍는다.
            if item.message.type == "frame":
                frames += 1
                if frames % 8:
                    continue
            print(f"[edge_sim] +{item.at_s:>6.2f}s  {item.message.type}")

    print(f"[edge_sim] 시나리오 종료 — frame {frames}건 포함 총 {len(timeline)}건")


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
