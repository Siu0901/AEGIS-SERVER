"""구간 추출 (API명세서 §4.7 `POST /clips` · `GET /keyframe`).

여기서 검증하는 것은 "파일이 만들어졌는가"가 아니라 **`actual_from` / `actual_to` 가
실제로 잘라낸 구간과 일치하는가**다. 서버는 이 값을 이벤트 증거 구간으로 기록하므로,
계산이 맞지 않으면 나중에 엉뚱한 10초를 증거로 들고 있게 된다.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import pytest

from recorder.clips import ClipError, extract_clip, extract_keyframe
from recorder.config import RecSettings
from recorder.ffmpeg import probe_duration

from .conftest import BASE_AT, TEST_GOP, make_settings, write_run

#: 키프레임 1초 간격이므로 절단점이 최대 1초 앞으로 밀린다. 그만큼 여유를 준다.
_KEYFRAME_SLACK = timedelta(seconds=TEST_GOP / 15.0 + 0.3)


def test_clip_joins_segments_and_reports_actual_range(rec_settings: RecSettings) -> None:
    write_run(rec_settings.rec_media_root, 1, BASE_AT, 4)  # 0~16초
    start = BASE_AT + timedelta(seconds=5)
    end = BASE_AT + timedelta(seconds=13)

    response = asyncio.run(
        extract_clip(rec_settings, cam_id=1, start=start, end=end, event_id="EV-TEST-0001")
    )

    assert response.status == "ready"
    assert response.download_url == "/clips/EV-TEST-0001.mp4"
    assert response.size_bytes is not None and response.size_bytes > 0
    assert response.actual_from is not None and response.actual_to is not None

    # 요청 구간을 빠짐없이 담아야 한다. 앞은 키프레임만큼 더 담길 수 있다.
    assert response.actual_from <= start
    assert response.actual_from >= start - _KEYFRAME_SLACK
    assert response.actual_to >= end - timedelta(seconds=0.5)

    # 보고한 구간이 실제 파일 길이와 맞는가 — 이것이 이 테스트의 핵심이다.
    path = rec_settings.rec_media_root / "clips" / "EV-TEST-0001.mp4"
    measured = asyncio.run(probe_duration(path))
    reported = (response.actual_to - response.actual_from).total_seconds()
    assert abs(measured - reported) < 0.2


def test_clip_works_when_media_root_is_configured_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.env` 에 `REC_MEDIA_ROOT=./media/rec` 처럼 상대경로를 적어도 동작해야 한다.

    concat 목록 파일은 임시 디렉토리에 만들어지고 concat demuxer 는 그 안의 상대경로를
    **목록 파일 기준**으로 푼다. 상대경로를 그대로 쓰면 `%TEMP%/aegis-rec-xxxx/media/...`
    를 찾다가 실패한다. 실제로 겪은 회귀라 경로를 굳히는 규칙을 여기서 잠근다.
    """
    monkeypatch.chdir(tmp_path)
    settings = make_settings(Path("./media/rec"))
    assert settings.rec_media_root.is_absolute()

    write_run(settings.rec_media_root, 1, BASE_AT, 3)
    response = asyncio.run(
        extract_clip(
            settings,
            cam_id=1,
            start=BASE_AT + timedelta(seconds=2),
            end=BASE_AT + timedelta(seconds=10),
            event_id="EV-TEST-REL",
        )
    )

    assert response.status == "ready"


def test_clip_outside_retention_is_not_found(rec_settings: RecSettings) -> None:
    write_run(rec_settings.rec_media_root, 1, BASE_AT, 2)

    response = asyncio.run(
        extract_clip(
            rec_settings,
            cam_id=1,
            start=BASE_AT - timedelta(days=30),
            end=BASE_AT - timedelta(days=30) + timedelta(seconds=20),
            event_id="EV-TEST-0002",
        )
    )

    assert response.status == "not_found"
    assert response.size_bytes is None
    assert response.download_url is None
    assert response.actual_from is None
    assert response.actual_to is None
    # §4.7 비-ready 응답 — 왜 없는지 알려준다. 서버가 clip_status=failed 의 원인으로 남긴다.
    assert response.reason is not None
    assert "보존 기간 경과" in response.reason


def test_not_found_distinguishes_expired_from_never_recorded(
    rec_settings: RecSettings,
) -> None:
    """지워진 것과 찍은 적이 없는 것은 대응이 다르므로 같은 문구로 뭉뚱그리지 않는다.

    보존 경과는 정상 동작이지만, 녹화 구간 한가운데가 비었다면 그 시간대에 카메라가
    끊겼거나 REC 이 멈춘 것이다 — 그건 조사해야 할 사고다.
    """
    root = rec_settings.rec_media_root
    write_run(root, 1, BASE_AT, 2)  # 0~8초
    write_run(root, 1, BASE_AT + timedelta(seconds=120), 2)  # 120~128초

    response = asyncio.run(
        extract_clip(
            rec_settings,
            cam_id=1,
            start=BASE_AT + timedelta(seconds=60),
            end=BASE_AT + timedelta(seconds=70),
            event_id="EV-TEST-GAP",
        )
    )

    assert response.status == "not_found"
    assert response.reason is not None
    assert "보존 기간" not in response.reason
    assert "녹화가 없다" in response.reason


def test_clip_with_missing_tail_is_partial(rec_settings: RecSettings) -> None:
    """녹화가 12초까지만 있는데 20초를 달라고 한 경우."""
    write_run(rec_settings.rec_media_root, 1, BASE_AT, 3)  # 0~12초

    response = asyncio.run(
        extract_clip(
            rec_settings,
            cam_id=1,
            start=BASE_AT + timedelta(seconds=4),
            end=BASE_AT + timedelta(seconds=24),
            event_id="EV-TEST-0003",
        )
    )

    assert response.status == "partial"
    assert response.actual_to is not None
    # 없는 시간을 만들어내지 않았는가.
    assert response.actual_to <= BASE_AT + timedelta(seconds=12.5)
    # 어느 쪽이 모자랐는지 말해준다 — 앞이 잘린 것과 뒤가 잘린 것은 원인이 다르다.
    assert response.reason is not None
    assert "뒤" in response.reason


def test_longer_than_requested_is_still_ready(rec_settings: RecSettings) -> None:
    """§4.7 — 세그먼트 경계 때문에 클립이 요청보다 길어지는 것은 **정상 동작이다**.

    요청 시각이 세그먼트 중간에 걸치면 그 세그먼트 시작부터 담기므로 앞이 늘어난다.
    이벤트 클립에서는 앞뒤 맥락이 붙는 것이라 문제가 되지 않는다. 이걸 `partial` 로
    보고하면 서버가 멀쩡한 증거 영상을 실패로 기록하게 된다.
    """
    write_run(rec_settings.rec_media_root, 1, BASE_AT, 3)  # 0~12초
    start = BASE_AT + timedelta(seconds=5.5)  # 세그먼트 한가운데
    end = BASE_AT + timedelta(seconds=9)

    response = asyncio.run(
        extract_clip(rec_settings, cam_id=1, start=start, end=end, event_id="EV-TEST-LONGER")
    )

    assert response.status == "ready"
    assert response.reason is None
    assert response.actual_from is not None and response.actual_from <= start


def test_clip_does_not_bridge_recording_gaps(rec_settings: RecSettings) -> None:
    """공백을 무시하고 붙이면 클립 안에 존재하지 않는 시간이 생긴다."""
    root = rec_settings.rec_media_root
    write_run(root, 1, BASE_AT, 2)  # 0~8초
    write_run(root, 1, BASE_AT + timedelta(seconds=60), 2)  # 60~68초

    response = asyncio.run(
        extract_clip(
            rec_settings,
            cam_id=1,
            start=BASE_AT + timedelta(seconds=2),
            end=BASE_AT + timedelta(seconds=64),
            event_id="EV-TEST-0004",
        )
    )

    assert response.status == "partial"
    assert response.actual_from is not None and response.actual_to is not None
    # 앞쪽 묶음(0~8초) 안에서만 잘렸어야 한다.
    assert response.actual_to <= BASE_AT + timedelta(seconds=8.5)


def test_clip_does_not_mix_cameras(rec_settings: RecSettings) -> None:
    write_run(rec_settings.rec_media_root, 1, BASE_AT, 3)

    response = asyncio.run(
        extract_clip(
            rec_settings,
            cam_id=2,
            start=BASE_AT + timedelta(seconds=2),
            end=BASE_AT + timedelta(seconds=8),
            event_id="EV-TEST-0005",
        )
    )

    assert response.status == "not_found"


def test_event_id_cannot_escape_media_root(rec_settings: RecSettings) -> None:
    write_run(rec_settings.rec_media_root, 1, BASE_AT, 2)

    for bad in ("../escape", "a/b", "..", r"..\escape"):
        try:
            asyncio.run(
                extract_clip(
                    rec_settings,
                    cam_id=1,
                    start=BASE_AT,
                    end=BASE_AT + timedelta(seconds=4),
                    event_id=bad,
                )
            )
        except ClipError:
            continue
        raise AssertionError(f"막지 못했다: {bad!r}")


def test_reversed_range_is_rejected(rec_settings: RecSettings) -> None:
    write_run(rec_settings.rec_media_root, 1, BASE_AT, 2)

    try:
        asyncio.run(
            extract_clip(
                rec_settings,
                cam_id=1,
                start=BASE_AT + timedelta(seconds=8),
                end=BASE_AT,
                event_id="EV-TEST-0006",
            )
        )
    except ClipError:
        return
    raise AssertionError("to < from 을 통과시켰다")


def test_keyframe_returns_single_jpeg(rec_settings: RecSettings) -> None:
    write_run(rec_settings.rec_media_root, 1, BASE_AT, 2)

    payload = asyncio.run(
        extract_keyframe(rec_settings, cam_id=1, at=BASE_AT + timedelta(seconds=5))
    )

    assert payload.startswith(b"\xff\xd8")  # JPEG SOI
    assert payload.endswith(b"\xff\xd9")  # JPEG EOI


def test_keyframe_without_recording_is_an_error(rec_settings: RecSettings) -> None:
    write_run(rec_settings.rec_media_root, 1, BASE_AT, 2)

    try:
        asyncio.run(extract_keyframe(rec_settings, cam_id=1, at=BASE_AT - timedelta(days=1)))
    except ClipError:
        return
    raise AssertionError("없는 시각인데 프레임을 돌려줬다")
