"""파이프라인 통합 — 실제 모델로 메시지를 만들어 **전선에 나가는 형태**를 검증한다.

가중치가 있어야 돌기 때문에 `requires_weights` 가 붙는다. 건너뛰면 pytest 가
skipped 로 따로 세므로 「검증하지 못했다」는 사실이 결과에 남는다(절대규칙 9).

여기서 잡는 것은 **단위 테스트로는 안 잡히는 것**이다 — 모델 입출력 형태, 설정과
모델의 불일치, 직렬화 규약. 실제로 이 경로에서 두 가지가 드러났다.

1. 분류 ONNX 의 배치 축이 1로 고정돼 있어 사람이 둘 이상이면 죽었다.
2. `exclude_unset` 이 판별자 `type` 을 빼서 서버가 전량 거부했다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
import pytest

from aegis_contracts import Policies
from aegis_vision import Correspondence, Homography, ReferenceHeight
from edge.client import CameraSetup, Setup
from edge.config import load_config
from edge.detect import Detector
from edge.letterbox import Letterbox
from edge.pipeline import CameraPipeline

from .conftest import LIVE_CONFIG, requires_weights

pytestmark = requires_weights

TS = datetime(2026, 8, 4, 12, 0, 0, tzinfo=UTC)

#: 합성 대응 4점. 영상이 없어도 좌표계를 만들 수 있다(`packages/vision` 순수 계산).
POINTS: list[Correspondence] = [
    ((0.21, 0.83), (0.0, 0.0)),
    ((0.68, 0.80), (5.0, 0.0)),
    ((0.75, 0.55), (5.0, 5.0)),
    ((0.28, 0.57), (0.0, 5.0)),
]


@pytest.fixture
def pipeline() -> CameraPipeline:
    from edge.classify import HelmetClassifier

    config = load_config(LIVE_CONFIG)
    stream = config.streams[0]
    letterbox = Letterbox(
        source_width=stream.width,
        source_height=stream.height,
        model_width=config.detect.imgsz[1],
        model_height=config.detect.imgsz[0],
    )
    built = CameraPipeline(
        cam_id=stream.cam_id,
        config=config,
        letterbox=letterbox,
        detector=Detector(config.detect, config.runtime, letterbox),
        classifier=HelmetClassifier(config.classify, config.runtime),
        depth=None,
    )
    setup = Setup(policies=Policies())
    setup.cameras[stream.cam_id] = CameraSetup(
        homography=Homography.from_correspondences(POINTS),
        reference=ReferenceHeight(px_height=0.42, at_m=(2.5, 2.5)),
    )
    built.apply(setup)
    return built


def _blank() -> np.ndarray:
    """640×360 회색 프레임. 감지가 0건이어도 `frame` 은 나가야 한다."""
    return np.full((360, 640, 3), 128, dtype=np.uint8)


def test_pipeline_is_ready_with_a_homography(pipeline: CameraPipeline) -> None:
    assert pipeline.ready


def test_frame_message_carries_the_discriminator(pipeline: CameraPipeline) -> None:
    """★ `exclude_unset` 로 직렬화해도 `type` 이 살아 있어야 한다.

    빠지면 서버가 `union_tag_not_found` 로 **전량 거부**한다.
    """
    output = pipeline.process(_blank(), ts=TS, at_s=0.0)
    assert output.frame is not None
    wire = json.loads(output.frame.model_dump_json(by_alias=True, exclude_unset=True))
    assert wire["type"] == "frame"
    assert wire["cam_id"] == 1


def test_no_homography_produces_no_frame() -> None:
    """호모그래피가 없으면 **좌표를 만들어 내지 않는다.**

    박스만 올리면 화면에는 뭔가 도는 것처럼 보이지만 거리도 구역도 없는 상태다.
    """
    from edge.classify import HelmetClassifier

    config = load_config(LIVE_CONFIG)
    stream = config.streams[0]
    letterbox = Letterbox(
        source_width=stream.width,
        source_height=stream.height,
        model_width=config.detect.imgsz[1],
        model_height=config.detect.imgsz[0],
    )
    bare = CameraPipeline(
        cam_id=stream.cam_id,
        config=config,
        letterbox=letterbox,
        detector=Detector(config.detect, config.runtime, letterbox),
        classifier=HelmetClassifier(config.classify, config.runtime),
        depth=None,
    )
    assert not bare.ready
    assert bare.process(_blank(), ts=TS, at_s=0.0).frame is None


def test_classifier_batches_many_crops(pipeline: CameraPipeline) -> None:
    """★ 사람이 여러 명이면 크롭을 묶어 넣는다.

    분류 ONNX 를 `dynamic=False` 로 내보내면 배치 축이 1로 고정되어 이 호출에서
    `Got: 4 Expected: 1` 로 죽는다. `scripts/export_onnx.py` 가 분류만 동적으로
    내보내는 이유이며, 러너는 불일치를 감지해 한 장씩으로 내린다(로그에 남는다).
    """
    from edge.classify import HelmetClassifier
    from edge.detect import Detection

    config = load_config(LIVE_CONFIG)
    classifier = HelmetClassifier(config.classify, config.runtime)
    box = (0.2, 0.2, 0.4, 0.9)
    crops = {
        index: Detection(
            object_class="person",
            conf=0.9,
            bbox=box,
            contour=((0.2, 0.2), (0.4, 0.2), (0.4, 0.9), (0.2, 0.9)),
            box_height_px=252.0,
        )
        for index in range(4)
    }
    readings = classifier.classify(
        _blank(), crops, at_s=0.0, min_crop_px=20, min_conf=0.0, cache_ms=0.0
    )
    assert len(readings) == 4
    assert {reading.helmet for reading in readings.values()} <= {"on", "off"}
