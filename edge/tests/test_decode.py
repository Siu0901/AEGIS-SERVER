"""`edge/main.py` 의 디코드 백엔드 분기.

**하드웨어 없이 검증할 수 있는 것만 덮는다.** NVDEC 로 실제 프레임을 푸는 것은
젯슨에서만 되지만, 그 앞의 판단 — 어떤 파이프라인을 만드는가, GStreamer 없는
OpenCV 에서 조용히 CPU 로 떨어지지 않는가 — 은 노트북에서 확인할 수 있고
틀렸을 때 대가가 큰 쪽도 그쪽이다.
"""

from __future__ import annotations

import pytest

from edge.config import ConfigError
from edge.main import _gstreamer_pipeline, _LatestFrame

URL = "rtsp://127.0.0.1:8554/cam1/sub"


def test_cpu_backend_needs_no_gstreamer() -> None:
    """노트북 경로는 GStreamer 없이도 만들어져야 한다."""
    reader = _LatestFrame(URL, "cpu")
    assert reader.connected is False


def test_unknown_decode_backend_is_rejected() -> None:
    """오타를 조용히 cpu 로 떨어뜨리면 하드웨어 디코더를 쓰는 줄 알고 CPU 로 돈다."""
    with pytest.raises(ConfigError, match="모르는 디코드 백엔드"):
        _LatestFrame(URL, "NVDEC")


def test_nvdec_without_gstreamer_fails_loudly() -> None:
    """PyPI 의 opencv-python-headless 는 GStreamer 없이 빌드돼 있다.

    이 환경에서 nvdec 를 켰다면 그 사실이 즉시 드러나야 한다 — 말없이 FFMPEG 로
    되돌리면 처리율이 안 나오는 원인을 엉뚱한 데서 찾게 된다(절대규칙 9).
    """
    import cv2

    if "GStreamer:                   YES" in cv2.getBuildInformation():
        pytest.skip("이 OpenCV 는 GStreamer 지원으로 빌드돼 있다 (젯슨 등)")
    with pytest.raises(ConfigError, match="GStreamer 지원이 없다"):
        _LatestFrame(URL, "nvdec")


def test_pipeline_takes_only_the_newest_frame() -> None:
    """파이프라인 쪽에서도 최신 프레임만 남겨야 좌표가 영상보다 뒤처지지 않는다."""
    pipeline = _gstreamer_pipeline(URL)
    assert "drop=true" in pipeline
    assert "max-buffers=1" in pipeline
    assert "latency=0" in pipeline
    assert "sync=false" in pipeline


def test_pipeline_uses_the_hardware_decoder() -> None:
    pipeline = _gstreamer_pipeline(URL)
    assert "nvv4l2decoder" in pipeline
    assert URL in pipeline


def test_pipeline_ends_in_bgr_for_opencv() -> None:
    """NVMM 메모리에서 한 번 내려와 OpenCV 가 기대하는 BGR 로 끝나야 한다."""
    pipeline = _gstreamer_pipeline(URL)
    assert pipeline.index("format=BGRx") < pipeline.index("format=BGR ")
    assert pipeline.rstrip().endswith("sync=false")


def test_pipeline_uses_tcp() -> None:
    """UDP 는 조용히 프레임을 흘린다 — 끊기면 끊긴 것이 드러나는 편이 낫다."""
    assert "protocols=tcp" in _gstreamer_pipeline(URL)
