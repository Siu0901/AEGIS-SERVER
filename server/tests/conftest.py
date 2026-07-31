"""서버 테스트 공용 도구.

바깥 프로세스(mediamtx · REC · NTP)에 실제로 붙지 않는다. 붙으면 테스트 결과가
그날 그 기계의 상태에 좌우되고, 그건 검증이 아니라 관측이다.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, cast

from aegis_contracts import (
    AlertCommand,
    AlertSound,
    EventDetail,
    EventListQuery,
    EventStatus,
    EventSummary,
    Policies,
    RecCameraStatus,
    RecRecordingStatus,
    RecStatusResponse,
    RecStorageStatus,
    VehicleClass,
    ViolationType,
    Zone,
)
from aegis_contracts.enums import AlertLevel, StreamState
from aegis_vision.clock import Clock
from server.app.alert_service import AlertService
from server.app.config import ServerSettings
from server.domain.alerts import SoundEntry
from server.domain.mcu_state import McuRuntime
from server.domain.metrics import MetricsRow
from server.infra.audio import SoundLibrary
from server.infra.rec_client import RecUnavailableError

__all__ = [
    "ASSETS_AUDIO",
    "REC_STATUS",
    "SOUND_MAP",
    "FakeCameraStore",
    "FakeEventStore",
    "FakeMqtt",
    "FakePlayer",
    "FakePolicyStore",
    "FakeRecClient",
    "FakeSoundStore",
    "FakeVehicleClassStore",
    "FakeWatcher",
    "FakeZoneStore",
    "make_alerts",
    "make_settings",
    "rec_status_with",
]

#: 종결되지 않은 상태. 기능명세서 §4.2 상태 전이표.
_OPEN_STATUSES = frozenset(
    {
        EventStatus.CANDIDATE,
        EventStatus.ACTIVE,
        EventStatus.ALERTED,
        EventStatus.RE_ALERTED,
        EventStatus.LOST,
    }
)

#: API명세서 §4.7 `GET /status` 예시 그대로.
REC_STATUS = RecStatusResponse(
    cameras=[
        RecCameraStatus(
            cam_id=1,
            recording=True,
            last_segment_at=datetime(2026, 8, 14, 5, 37, 10, tzinfo=UTC),
        ),
        RecCameraStatus(
            cam_id=2,
            recording=True,
            last_segment_at=datetime(2026, 8, 14, 5, 37, 10, tzinfo=UTC),
        ),
    ],
    storage=RecStorageStatus(
        total_gb=500,
        used_gb=378,
        free_gb=122,
        retention_days=7,
        oldest_segment_at=datetime(2026, 8, 7, 5, 37, 0, tzinfo=UTC),
    ),
    recording=RecRecordingStatus(segment_seconds=10, snapshot_window_s=60, snapshot_bytes=0),
)


def rec_status_with(*, recording: dict[int, bool]) -> RecStatusResponse:
    """카메라별 녹화 여부만 바꾼 §4.7 응답.

    REC 이 녹화하지 않는 카메라는 **목록에 아예 없다.** 그래서 `cam_id` 를 키로 받는다.
    """
    return RecStatusResponse(
        cameras=[
            RecCameraStatus(
                cam_id=cam_id,
                recording=is_recording,
                last_segment_at=datetime(2026, 8, 14, 5, 37, 10, tzinfo=UTC),
            )
            for cam_id, is_recording in sorted(recording.items())
        ],
        storage=REC_STATUS.storage,
        recording=REC_STATUS.recording,
    )


def make_settings(**overrides: object) -> ServerSettings:
    """개발자의 `.env` 를 읽지 않는 설정. NTP 확인도 끈다(네트워크 접근 금지)."""
    fields: dict[str, object] = {
        "cam_ids": [1, 2],
        "mediamtx_api": "http://127.0.0.1:59997",
        "recorder_base": "http://127.0.0.1:59100",
        "ntp_server": "",
        **overrides,
    }
    return ServerSettings(_env_file=None, **fields)  # type: ignore[arg-type]


class FakeWatcher:
    """`StreamObserver` 대역."""

    def __init__(self, states: dict[int, StreamState]) -> None:
        self._states = dict(states)
        self.started = False
        self.stopped = False

    def states(self) -> dict[int, StreamState]:
        return dict(self._states)

    def set(self, cam_id: int, state: StreamState) -> None:
        self._states[cam_id] = state

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class FakeRecClient:
    """`StorageReader` 대역. `available=False` 면 REC 이 죽은 상황을 흉내 낸다.

    `sequence` 를 주면 부를 때마다 **다른 응답**을 돌려준다(마지막 값이 이후 반복).
    한 요청 안에서 REC 을 두 번 부르면 값이 어긋난다는 것을 드러내기 위한 장치다.
    """

    def __init__(
        self,
        *,
        available: bool = True,
        payload: RecStatusResponse | None = None,
        sequence: list[RecStatusResponse] | None = None,
    ) -> None:
        self.available = available
        self.payload = payload or REC_STATUS
        self.sequence = list(sequence or [])
        self.calls = 0

    async def status(self) -> RecStatusResponse:
        self.calls += 1
        if not self.available:
            msg = "REC 에 닿지 못했다 (테스트)"
            raise RecUnavailableError(msg)
        if self.sequence:
            return self.sequence.pop(0) if len(self.sequence) > 1 else self.sequence[0]
        return self.payload

    async def aclose(self) -> None:
        return None


class FakeEventStore:
    """`EventStore` · `EventReader` 대역. 메모리 안의 이벤트 목록 하나다.

    DB 를 띄우지 않는 이유는 속도 때문만이 아니다 — FN-EVT-01 이 검증하는 것은
    "같은 트랙·같은 유형이면 새로 만들지 않는다"는 **판단**이고, 그 판단은 저장
    매체와 무관해야 한다.
    """

    def __init__(self, items: list[EventDetail] | None = None) -> None:
        self.items: list[EventDetail] = list(items or [])
        self.created: list[EventDetail] = []
        self.updates: list[tuple[str, dict[str, Any]]] = []
        self.notes: dict[str, str] = {}
        self.clip_status: dict[str, str] = {}
        """§6 `events.clip_status` 의 사본. 모델 필드이기도 하지만 "언제 무엇으로
        바뀌었는가"를 테스트가 바로 볼 수 있게 따로 든다."""
        self.clip_errors: dict[str, str] = {}
        """§6 `events.clip_error`. **`notes` 와 섞지 않는다** — 관리자 메모와 클립 실패
        사유가 한 칸을 쓰던 임시 처리가 사라졌다는 것을 이 분리가 잠근다."""
        self.keyframe_paths: dict[str, list[str]] = {}
        self.fail_with: Exception | None = None

    async def find_due_clip_jobs(self, now: datetime, delay_s: float) -> list[str]:
        """FN-REC-03 — 실행 시각이 지난 `pending` 예약. DB 질의와 같은 조건이다.

        **예약이 여기(저장소)에만 있다는 것이 요점이다.** 그래서 `ClipService` 를 새로
        만들어도(= 재시작) 같은 목록이 나온다.
        """
        return sorted(
            item.event_id
            for item in self.items
            if self.clip_status.get(item.event_id) == "pending"
            and item.confirmed_at is not None
            and item.confirmed_at + timedelta(seconds=delay_s) <= now
        )

    async def find_open_events(
        self, cam_id: int, track_id: int
    ) -> dict[ViolationType, EventSummary]:
        return {
            item.violation_type: EventSummary.model_validate(
                item.model_dump(include=set(EventSummary.model_fields))
            )
            for item in self.items
            if item.cam_id == cam_id and item.track_id == track_id and item.status in _OPEN_STATUSES
        }

    async def next_event_id(self, at: datetime) -> str:
        from server.domain.event_machine import format_event_id

        return format_event_id(at, len(self.items) + 1)

    async def create(self, event: EventDetail) -> None:
        self.items.append(event)
        self.created.append(event)

    async def update(self, event_id: str, changes: Mapping[str, Any]) -> None:
        self.updates.append((event_id, dict(changes)))
        patch = dict(changes)
        # 상태머신은 **DB 컬럼 값**으로 말한다(`status` 는 문자열). 실제 저장소는
        # 읽을 때 열거형으로 되돌리므로 가짜도 같은 일을 해야 한다 — 안 그러면
        # 응답에 날문자열이 실려도 테스트가 통과한다.
        if "status" in patch:
            patch["status"] = EventStatus(patch["status"])
        if (note := patch.get("note")) is not None:
            # §4.1 이 응답에 `note` 를 추가하면서 모델 필드가 됐다. 그대로 반영하되,
            # 저장소가 기억했는지를 테스트가 따로 볼 수 있게 사본도 남긴다.
            self.notes[event_id] = note
        if (status := patch.get("clip_status")) is not None:
            self.clip_status[event_id] = str(status)
        if (clip_error := patch.get("clip_error")) is not None:
            self.clip_errors[event_id] = str(clip_error)
        if (clip_path := patch.pop("clip_path", None)) is not None:
            # 실제 저장소는 경로를 URL 로 바꿔 내려준다(§5 「경로 규약」).
            patch["clip_url"] = f"/media/clips/{PurePosixPath(str(clip_path)).name}"
        if (keyframes := patch.pop("keyframe_paths", None)) is not None:
            self.keyframe_paths[event_id] = list(keyframes)
        # `dropped_at` 은 §6 컬럼이고 §4.1 응답에는 없다(종결 시각은 `timeline` 로 나간다).
        patch.pop("dropped_at", None)
        for index, item in enumerate(self.items):
            if item.event_id == event_id:
                self.items[index] = item.model_copy(update=patch)

    async def find_open_all(self) -> list[EventSummary]:
        return [
            EventSummary.model_validate(item.model_dump(include=set(EventSummary.model_fields)))
            for item in self.items
            if item.status in _OPEN_STATUSES
        ]

    async def metrics_rows(self, from_: datetime | None, to: datetime | None) -> list[MetricsRow]:
        return [
            MetricsRow(
                violation_type=item.violation_type,
                status=item.status,
                resolution_sec=item.resolution_sec,
                is_false_positive=False,
            )
            for item in self.items
            if (from_ is None or item.detected_at >= from_)
            and (to is None or item.detected_at <= to)
        ]

    async def list_events(self, query: EventListQuery) -> tuple[list[EventSummary], str | None]:
        if self.fail_with is not None:
            raise self.fail_with
        return [
            EventSummary.model_validate(item.model_dump(include=set(EventSummary.model_fields)))
            for item in self.items
        ], None

    async def get(self, event_id: str) -> EventDetail | None:
        if self.fail_with is not None:
            raise self.fail_with
        return next((item for item in self.items if item.event_id == event_id), None)


class FakeZoneStore:
    """`ZoneRepository` 대역 — 조회와 편집(FN-CFG-02) 양쪽."""

    def __init__(self, zones: list[Zone] | None = None) -> None:
        self.zones = list(zones or [])
        self.fail_with: Exception | None = None

    async def list_zones(self, cam_id: int | None = None) -> list[Zone]:
        if self.fail_with is not None:
            raise self.fail_with
        return [zone for zone in self.zones if cam_id is None or zone.cam_id == cam_id]

    async def upsert(self, zone: Zone) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.zones = [item for item in self.zones if item.zone_id != zone.zone_id]
        self.zones.append(zone)

    async def delete(self, zone_id: str) -> bool:
        if self.fail_with is not None:
            raise self.fail_with
        before = len(self.zones)
        self.zones = [item for item in self.zones if item.zone_id != zone_id]
        return len(self.zones) < before


class FakeCameraStore:
    """`CameraRepository` 대역. 캘리브레이션 전에는 `homography` 가 `None` 이다."""

    def __init__(self, cameras: dict[int, str] | None = None) -> None:
        self.names = dict(cameras or {1: "1번 카메라", 2: "2번 카메라"})
        self.homography: dict[int, list[list[float]]] = {}
        self.reference: dict[int, dict[str, Any] | None] = {}
        self.calibrated_at: dict[int, datetime] = {}
        self.calib_points: dict[int, list[dict[str, Any]] | None] = {}
        self.reproj_error_m: dict[int, float | None] = {}
        self.fail_with: Exception | None = None

    async def list_cameras(self) -> list[dict[str, Any]]:
        if self.fail_with is not None:
            raise self.fail_with
        return [
            {
                "cam_id": cam_id,
                "name": name,
                "rtsp_main": f"rtsp://127.0.0.1:8554/cam{cam_id}/main",
                "rtsp_sub": f"rtsp://127.0.0.1:8554/cam{cam_id}/sub",
                "homography": self.homography.get(cam_id),
                "ref_height": self.reference.get(cam_id),
                "calib_points": self.calib_points.get(cam_id),
                "reproj_error_m": self.reproj_error_m.get(cam_id),
                "calibrated_at": self.calibrated_at.get(cam_id),
            }
            for cam_id, name in sorted(self.names.items())
        ]

    async def get_homography(self, cam_id: int) -> list[list[float]] | None:
        if self.fail_with is not None:
            raise self.fail_with
        return self.homography.get(cam_id)

    async def save_calibration(
        self,
        cam_id: int,
        homography: list[list[float]],
        ref_height: dict[str, Any] | None,
        calibrated_at: datetime,
        calib_points: list[dict[str, Any]] | None = None,
        reproj_error_m: float | None = None,
    ) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        if cam_id not in self.names:
            msg = f"등록되지 않은 카메라다: {cam_id}"
            raise LookupError(msg)
        self.homography[cam_id] = homography
        self.reference[cam_id] = ref_height
        self.calibrated_at[cam_id] = calibrated_at
        self.calib_points[cam_id] = calib_points
        self.reproj_error_m[cam_id] = reproj_error_m

    async def patch_camera(self, cam_id: int, changes: dict[str, Any]) -> dict[str, Any] | None:
        if self.fail_with is not None:
            raise self.fail_with
        if cam_id not in self.names:
            return None
        if "name" in changes:
            self.names[cam_id] = str(changes["name"])
        rows = await self.list_cameras()
        return next(row for row in rows if row["cam_id"] == cam_id)


class FakeVehicleClassStore:
    """`VehicleClassRepository` 대역. FN-CFG-05"""

    def __init__(self, classes: list[VehicleClass] | None = None) -> None:
        self.classes = list(
            classes or [VehicleClass(class_name="vehicle", danger_radius_m=3.0, active=True)]
        )

    async def list_vehicle_classes(self) -> list[VehicleClass]:
        return list(self.classes)

    async def patch(self, class_name: str, changes: dict[str, Any]) -> VehicleClass | None:
        for index, item in enumerate(self.classes):
            if item.class_name == class_name:
                updated = item.model_copy(update=changes)
                self.classes[index] = updated
                return updated
        return None


class FakePolicyStore:
    """`PolicyRepository` 대역 — 조회와 갱신(FN-CFG-04) 양쪽."""

    def __init__(self, policies: Policies | None = None) -> None:
        self.policies = policies or Policies()
        self.fail_with: Exception | None = None

    async def load(self) -> Policies:
        if self.fail_with is not None:
            raise self.fail_with
        return self.policies

    async def patch(self, changes: dict[str, Any]) -> Policies:
        if self.fail_with is not None:
            raise self.fail_with
        self.policies = self.policies.model_copy(update=changes)
        return self.policies


# --------------------------------------------------------------------------
# 경고 (FN-ALM-01 · 02)
# --------------------------------------------------------------------------
# **테스트는 소리를 내지도 브로커에 붙지도 않는다.** 재생기와 MQTT 를 가짜로 바꿔
# "무엇을 틀었고 무엇을 발행했는가"만 기록한다. 실물을 쓰면 사운드 장치가 없는 CI 와
# 브로커가 떠 있는 개발 기계에서 결과가 달라진다.

#: 레포의 음원 디렉토리. `assets/` 는 사람이 관리하는 자산 자리다(CLAUDE.md 디렉토리 표).
ASSETS_AUDIO = Path(__file__).resolve().parent.parent.parent / "assets" / "audio"

#: 기본 음원 매핑. `scripts/seed_sounds.py` 가 DB 에 넣는 것과 같은 모양이다.
#: **등급도 함께 온다**(§6 `alert_sounds.level`) — `fall` 만 3 이다(§3).
SOUND_MAP: dict[str, SoundEntry] = {
    "no_helmet": SoundEntry(file_path="no_helmet.wav", level=2, label="안전모 미착용 안내"),
    "zone_intrusion": SoundEntry(
        file_path="zone_intrusion.wav", level=2, label="금지구역 이탈 안내"
    ),
    "proximity": SoundEntry(file_path="proximity.wav", level=2, label="지게차 근접 경고"),
    "fall": SoundEntry(file_path="fall.wav", level=3, label="쓰러짐 구조 안내"),
    "custom_notice": SoundEntry(file_path="custom_notice.wav", level=2, label="일반 안내 방송"),
}


class FakeSoundStore:
    """`SoundReader` + 설정 API(§4.5) 대역 — `alert_sounds` 테이블 대신 dict 하나.

    두 역할을 한 대역이 맡는 이유는 **실제로도 한 테이블**이기 때문이다. 경고 경로는
    켜진 것만 읽고(`load_sounds`), 설정 화면은 꺼진 것까지 읽어 고친다.
    """

    def __init__(self, mapping: dict[str, SoundEntry] | None = None) -> None:
        self.mapping = dict(SOUND_MAP if mapping is None else mapping)
        self.inactive: set[str] = set()
        self.calls = 0

    async def load_sounds(self) -> dict[str, SoundEntry]:
        self.calls += 1
        return {key: entry for key, entry in self.mapping.items() if key not in self.inactive}

    async def list_sounds(self) -> list[AlertSound]:
        return [
            AlertSound(
                violation_type=key,
                file_path=entry.file_path,
                level=entry.level,
                label=entry.label,
                active=key not in self.inactive,
            )
            for key, entry in sorted(self.mapping.items())
        ]

    async def patch_sound(self, violation_type: str, changes: dict[str, Any]) -> AlertSound | None:
        entry = self.mapping.get(violation_type)
        if entry is None:
            return None
        self.mapping[violation_type] = SoundEntry(
            file_path=str(changes.get("file_path", entry.file_path)),
            level=cast("AlertLevel", changes.get("level", entry.level)),
            label=cast("str | None", changes.get("label", entry.label)),
        )
        if "active" in changes:
            self.inactive.discard(violation_type)
            if not changes["active"]:
                self.inactive.add(violation_type)
        found = [item for item in await self.list_sounds() if item.violation_type == violation_type]
        return found[0]


class FakePlayer:
    """`SoundPlayer` 대역. 판 파일을 순서대로 기억한다."""

    name = "fake"

    def __init__(self, *, fail: bool = False) -> None:
        self.played: list[Path] = []
        self.fail = fail

    def play(self, path: Path) -> None:
        if self.fail:
            msg = f"재생 장치가 없다 (테스트): {path.name}"
            raise RuntimeError(msg)
        self.played.append(path)


class FakeMqtt:
    """`MqttSender` 대역. 발행한 `AlertCommand` 를 순서대로 기억한다."""

    def __init__(self, *, fail: bool = False) -> None:
        self.published: list[AlertCommand] = []
        self.fail = fail

    async def publish_alert(self, command: AlertCommand) -> None:
        if self.fail:
            msg = "브로커에 닿지 못했다 (테스트)"
            raise RuntimeError(msg)
        self.published.append(command)


def make_alerts(
    clock: Clock,
    *,
    player: FakePlayer | None = None,
    mqtt: FakeMqtt | None = None,
    sounds: FakeSoundStore | None = None,
    audio_dir: Path | None = None,
) -> AlertService:
    """가짜 장치로 묶은 `AlertService`.

    음원 파일은 레포의 `assets/audio/` 를 그대로 본다 — `scripts/seed_sounds.py` 가
    무음 wav 를 깔아 두므로 파일 존재 검사까지 실제와 같은 경로로 돈다.
    """
    return AlertService(
        library=SoundLibrary(audio_dir or ASSETS_AUDIO, sounds or FakeSoundStore()),
        player=player or FakePlayer(),
        clock=clock,
        mcu=McuRuntime(),
        mqtt=mqtt or FakeMqtt(),
    )
