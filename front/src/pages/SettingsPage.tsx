/**
 * 설정 (FN-UI-07 · 기능명세서 §4.7 · API명세서 §4.5).
 *
 * 시안 4페이지 — 캘리브레이션 · 구역 편집 · 음원 매핑 · 임계값 · 위험 반경 · 시스템 상태.
 *
 * **「위험요소 등록 · 자연어」 패널은 만들지 않는다**(부록 A-1). 제로샷/오픈보캐블러리
 * 감지는 채택되지 않았고 감지 클래스는 `person` · `vehicle` 2종 고정이다. 시안에 남아
 * 있어도 무시한다(CLAUDE.md 절대규칙 11).
 *
 * 이 화면의 판단들:
 *
 * · **캘리브레이션은 라이브 영상 위에서 찍는다.** 지면의 표식 네 곳을 실제로 보면서
 *   찍어야 줄자로 잰 값과 짝이 맞는다. 정지 화상을 따로 받아오는 경로를 만들면
 *   "그 사진을 찍은 시점의 카메라"와 지금 카메라가 같다는 보장이 없다
 * · **재투영 오차를 저장 직후 그대로 보여준다**(§4.5). 4점을 잘못 찍었는지 알 수 있는
 *   유일한 수단이고, 그것을 모르면 이후의 모든 거리·구역 판정이 조용히 틀어진다
 * · **픽셀 → 미터 변환을 여기서 하지 않는다.** 그린 폴리곤을 정규화 픽셀 그대로 보내고
 *   서버가 호모그래피로 바꾼다(§4.5) — 변환 코드가 두 벌이 되면 어느 쪽이 맞는지 알 수
 *   없다. 저장된 구역을 **되그릴 때만** 역행렬을 곱한다(행렬 곱이지 캘리브레이션이 아니다)
 * · **캘리브레이션이 없는 카메라에는 구역을 그릴 수 없다.** 서버가 422 로 거절하며,
 *   화면도 그 상태를 먼저 말한다 — 픽셀을 미터인 척 저장하면 판정이 통째로 틀린다
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  calibrate,
  deleteZone,
  fetchAlertSounds,
  fetchCameras,
  fetchPolicies,
  fetchVehicleClasses,
  fetchZones,
  groundToPixel,
  saveAlertSound,
  savePolicies,
  saveVehicleClass,
  saveZone,
  type AlertSound,
  type CameraCalibration,
  type VehicleClass,
} from '../api/settings'
import { useSystemStatus } from '../api/useSystemStatus'
import { startPlayback, type PlaybackKind } from '../live/player'
import { cameraFallbackName, retentionLabel, stamp, violationLabel } from '../types/labels'
import type { Policies, Zone } from '../types/system'
import './settings.css'

const WHEP_BASE = __MEDIAMTX_WHEP__
const HLS_BASE = __MEDIAMTX_HLS__

/** 캘리브레이션에 필요한 대응점 수(자유도 8 → 4쌍). API명세서 §4.5 */
const REQUIRED_POINTS = 4

/** 구역 폴리곤 최소 꼭짓점. 두 점은 선분이지 구역이 아니다. */
const MIN_VERTICES = 3

/** 이 값을 넘는 재투영 오차는 눈에 띄게 표시한다. 사람 어깨너비 정도의 오차다. */
const ERROR_WARN_M = 0.3

/** 화면이 노출하는 임계값. **값은 적지 않는다** — 서버에서 읽은 것만 보여준다(절대규칙 6). */
const POLICY_FIELDS: { key: keyof Policies; label: string; unit: string; hint: string }[] = [
  { key: 'confirm_duration_s', label: '확정 지속', unit: '초', hint: '후보 → 확정' },
  { key: 'resolve_duration_s', label: '해소 지속', unit: '초', hint: '위반 소멸 → 시정' },
  { key: 'cooldown_s', label: '재경고 쿨다운', unit: '초', hint: '재경고 최소 간격' },
  { key: 'resolve_window_s', label: '시정 인정 창', unit: '초', hint: '이 안이면 분자' },
  { key: 'proximity_threshold_m', label: '근접 임계', unit: 'm', hint: '즉시 경고 기준' },
  { key: 'track_lost_grace_s', label: '소실 유예', unit: '초', hint: '넘기면 판정 불가' },
  { key: 'reassoc_window_s', label: '재결합 창', unit: '초', hint: '끊긴 트랙 다시 잇기' },
  { key: 'clip_pre_roll_s', label: '클립 사전', unit: '초', hint: '확정 이전 구간' },
  { key: 'clip_post_roll_s', label: '클립 사후', unit: '초', hint: '확정 이후 구간' },
  { key: 'clip_extract_margin_s', label: '추출 여유', unit: '초', hint: '세그먼트가 닫힌 뒤' },
  { key: 'alert_duration_s', label: '경광등 지속', unit: '초', hint: 'AlertCommand.duration_s' },
  { key: 'mute_default_duration_s', label: '일시중지 기본', unit: '초', hint: '기한 없는 중지 금지' },
  { key: 'cls_min_conf', label: '분류 최소 신뢰도', unit: '', hint: '미달이면 채택 안 함' },
  { key: 'cls_min_crop_px', label: '분류 최소 크롭', unit: 'px', hint: '미달이면 추론 생략' },
  { key: 'fall_stillness_s', label: '쓰러짐 정지', unit: '초', hint: '조건 ③' },
  // ★ 명세서가 `edge/config.yaml` 에서 승격시킨 두 키(§4.5). 정지 판정은 오탐 억제의
  //   핵심이라 현장 튜닝이 잦은데, 장비 설정 파일에 있으면 조정이 곧 배포가 된다.
  //   둘은 **함께** 만져야 한다 — 창이 길면 짧은 움직임이 평균에 묻힌다.
  { key: 'stillness_move_px', label: '정지 이동 한계', unit: 'px', hint: '이하면 정지' },
  { key: 'stillness_window_s', label: '정지 평가 창', unit: '초', hint: '이동 평균 구간' },
  { key: 'fall_height_ratio_max', label: '쓰러짐 높이비', unit: '', hint: '조건 ①' },
  { key: 'fall_axis_angle_min_deg', label: '쓰러짐 주축각', unit: '°', hint: '조건 ②' },
  {
    key: 'overlay_buffer_webrtc_ms',
    label: '오버레이 버퍼 · WebRTC',
    unit: 'ms',
    hint: '영상 지연에 맞춘다',
  },
  { key: 'overlay_buffer_hls_ms', label: '오버레이 버퍼 · HLS', unit: 'ms', hint: '폴백 경로' },
  { key: 'overlay_stale_ms', label: '오버레이 노후', unit: 'ms', hint: '넘으면 흐리게' },
]

type Mode = 'idle' | 'calibrate' | 'zone' | 'reference'

type PendingPoint = { px: [number, number]; x: string; y: string }

/**
 * 기준 인물 입력 중인 값 (FN-CFG-01 · 기능명세서 §6 `cameras.ref_height`).
 *
 * ★ **높이만으로는 부족하다.** 저장 형태가 `{height_px, at_m}` 인 이유가 이것이다 —
 * 기준 높이를 **어느 지면 위치에서 쟀는지**가 없으면 다른 거리의 기대 높이를 구할 수
 * 없다. 같은 사람도 카메라에서 멀수록 화면상 픽셀 높이가 줄어들기 때문이다.
 *
 * 화면상 높이는 발끝·머리끝 두 점을 클릭해 얻고, 그 사람이 서 있던 지면 좌표는 4점과
 * 같은 줄자 실측으로 입력받는다. **저장되지 않은 호모그래피로 미리 환산하지 않는다** —
 * 같은 제출에서 만들어지는 행렬이라 아직 존재하지 않는다.
 */
type PendingReference = {
  foot: [number, number] | null
  head: [number, number] | null
  x: string
  y: string
}

const EMPTY_REFERENCE: PendingReference = { foot: null, head: null, x: '', y: '' }

/** 두 클릭 사이의 세로 거리 = 화면상 높이(정규화 픽셀). */
function referenceHeightPx(reference: PendingReference): number | null {
  if (!reference.foot || !reference.head) return null
  const height = Math.abs(reference.foot[1] - reference.head[1])
  return height > 0 ? Number(height.toFixed(4)) : null
}

export default function SettingsPage() {
  const { status } = useSystemStatus()
  const [cameras, setCameras] = useState<CameraCalibration[]>([])
  const [zones, setZones] = useState<Zone[]>([])
  const [sounds, setSounds] = useState<AlertSound[]>([])
  const [vehicles, setVehicles] = useState<VehicleClass[]>([])
  const [policies, setPolicies] = useState<Policies | null>(null)
  const [camId, setCamId] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const reload = useCallback((signal?: AbortSignal) => {
    void Promise.all([
      fetchCameras(signal),
      fetchZones(signal),
      fetchAlertSounds(signal),
      fetchVehicleClasses(signal),
      fetchPolicies(signal),
    ])
      .then(([nextCameras, nextZones, nextSounds, nextVehicles, nextPolicies]) => {
        setCameras(nextCameras)
        setZones(nextZones)
        setSounds(nextSounds)
        setVehicles(nextVehicles)
        setPolicies(nextPolicies)
        setError(null)
      })
      .catch((cause: unknown) => {
        if (signal?.aborted) return
        setError(`설정을 읽지 못했다 — ${cause instanceof Error ? cause.message : String(cause)}`)
      })
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    reload(controller.signal)
    return () => controller.abort()
  }, [reload])

  const camera = cameras.find((item) => item.cam_id === camId) ?? null

  return (
    <div className="settings">
      {/* 읽기 실패와 저장 실패는 다른 사실이므로 문구를 부르는 쪽이 붙인다.
          한 문구로 뭉뚱그리면 저장이 거부됐는데 "읽지 못했다"고 뜬다. */}
      {error && <p className="settings__error">{error}</p>}
      {notice && <p className="settings__notice">{notice}</p>}

      <CameraPanel
        camId={camId}
        cameras={cameras}
        camera={camera}
        zones={zones.filter((zone) => zone.cam_id === camId)}
        onSelect={setCamId}
        onDone={(message) => {
          setNotice(message)
          reload()
        }}
        onError={setError}
      />

      <ZoneList
        zones={zones.filter((zone) => zone.cam_id === camId)}
        camName={camera?.name ?? cameraFallbackName(camId)}
        onDeleted={(zoneId) => {
          setNotice(`구역 ${zoneId} 을 삭제했다`)
          reload()
        }}
        onError={setError}
      />

      <SoundPanel sounds={sounds} onSaved={setNotice} onError={setError} />

      <PolicyPanel
        policies={policies}
        onSaved={(next, message) => {
          setPolicies(next)
          setNotice(message)
        }}
        onError={setError}
      />

      <VehiclePanel
        classes={vehicles}
        onSaved={(next, message) => {
          setVehicles((current) =>
            current.map((item) => (item.class_name === next.class_name ? next : item)),
          )
          setNotice(message)
        }}
        onError={setError}
      />

      <section className="card">
        <h2 className="card__title">시스템</h2>
        <dl className="settings__facts">
          <div>
            <dt>엣지</dt>
            <dd>{status?.edge.online ? '연결됨' : '끊김'}</dd>
          </div>
          <div>
            <dt>MCU</dt>
            <dd>{status?.mcu.online ? '연결됨' : '끊김'}</dd>
          </div>
          <div>
            <dt>거부된 엣지 메시지</dt>
            <dd>{status ? `${status.edge.msg_rejected_total}건` : '—'}</dd>
          </div>
          <div>
            <dt>녹화 보존</dt>
            <dd>{retentionLabel(status?.storage.retention_days ?? null)}</dd>
          </div>
        </dl>
        <p className="card__note">
          자세한 상태는 개요 화면에 있다. 여기에는 설정을 바꾸기 전에 확인할 것만 둔다.
        </p>
      </section>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* FN-CFG-01 · 02 — 캘리브레이션과 구역 그리기                          */
/* ------------------------------------------------------------------ */

function CameraPanel({
  camId,
  cameras,
  camera,
  zones,
  onSelect,
  onDone,
  onError,
}: {
  camId: number
  cameras: CameraCalibration[]
  camera: CameraCalibration | null
  zones: Zone[]
  onSelect: (camId: number) => void
  onDone: (message: string) => void
  onError: (message: string) => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [kind, setKind] = useState<PlaybackKind>('none')
  const [mode, setMode] = useState<Mode>('idle')
  const [points, setPoints] = useState<PendingPoint[]>([])
  // 「변 길이만 입력」 모드가 기본이다.
  //
  // 점마다 (x, y)를 손으로 넣게 하면 사람이 좌표계를 머릿속에서 세워야 한다 — 원점을
  // 어디로 둘지, 어느 축이 어느 방향인지. 정작 현장에서 손에 쥐고 있는 것은 줄자로 잰
  // **변의 길이 하나**다. 네 점을 순서대로 찍었다면 그 두 길이만으로 좌표 여덟 개가
  // 전부 결정되므로, 계산은 화면이 한다.
  const [rectMode, setRectMode] = useState(true)
  const [edgeA, setEdgeA] = useState('')
  const [edgeB, setEdgeB] = useState('')
  const [reference, setReference] = useState<PendingReference>(EMPTY_REFERENCE)
  const [polygon, setPolygon] = useState<[number, number][]>([])
  const [zoneId, setZoneId] = useState('')
  const [zoneName, setZoneName] = useState('')
  const [buffer, setBuffer] = useState('0.3')
  const [result, setResult] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const handle = startPlayback(
      video,
      {
        whep: `${WHEP_BASE}/cam${camId}/main/whep`,
        hls: `${HLS_BASE}/cam${camId}/main/index.m3u8`,
      },
      (state) => setKind(state.kind),
    )
    return () => handle.stop()
  }, [camId])

  // 카메라를 바꾸면 찍던 것을 버린다. 다른 화면에서 찍은 점을 그대로 두면 서로 다른
  // 두 카메라의 좌표가 한 행렬로 들어간다.
  useEffect(() => {
    setMode('idle')
    setPoints([])
    setEdgeA('')
    setEdgeB('')
    setReference(EMPTY_REFERENCE)
    setPolygon([])
    setResult(null)
  }, [camId])

  /**
   * 찍은 순서를 직사각형의 꼭짓점으로 읽어 네 점의 지면 좌표를 만든다.
   *
   *   1 → (0, 0)   2 → (a, 0)   3 → (a, b)   4 → (0, b)
   *
   * `a` 는 1→2 변, `b` 는 2→3 변의 실측 길이다. 원점은 1번 점이고 축은 찍은 방향을
   * 따라가므로, 사람은 좌표계를 세울 필요 없이 **줄자로 잰 숫자 두 개**만 넣으면 된다.
   *
   * 단위를 강제하지 않는다 — 실물 현장이면 m, 미니어처 시연이면 cm 를 그대로 넣는다.
   * 임계값(`policies`)이 같은 단위로 맞춰져 있기만 하면 된다(기능명세서 §4.7).
   */
  const rectCoords = (): [number, number][] | null => {
    const a = Number(edgeA)
    const b = Number(edgeB)
    if (edgeA.trim() === '' || edgeB.trim() === '') return null
    if (!Number.isFinite(a) || !Number.isFinite(b) || a <= 0 || b <= 0) return null
    return [
      [0, 0],
      [a, 0],
      [a, b],
      [0, b],
    ]
  }

  const handleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (mode === 'idle') return
    const box = event.currentTarget.getBoundingClientRect()
    const point: [number, number] = [
      Number(((event.clientX - box.left) / box.width).toFixed(4)),
      Number(((event.clientY - box.top) / box.height).toFixed(4)),
    ]
    // **함수형 갱신을 쓴다.** 클릭 두 번이 같은 렌더 주기에 들어오면(빠른 연속 클릭 ·
    // 더블클릭) 배열을 그대로 참조하는 방식은 앞의 점을 덮어써 하나만 남는다.
    if (mode === 'calibrate') {
      setPoints((current) =>
        current.length >= REQUIRED_POINTS ? current : [...current, { px: point, x: '', y: '' }],
      )
    } else if (mode === 'reference') {
      // 발끝 먼저, 머리끝 다음. 순서를 고정해야 어느 점이 지면 위치인지 알 수 있다.
      setReference((current) =>
        current.foot === null
          ? { ...current, foot: point }
          : current.head === null
            ? { ...current, head: point }
            : current,
      )
    } else {
      setPolygon((current) => [...current, point])
    }
  }

  const submitCalibration = async () => {
    setBusy(true)
    try {
      // 기준 인물은 **선택**이다(§4.5). 미입력이면 카메라 기하로 기대 높이를 추정한다.
      // 다만 넣는다면 높이와 위치가 **함께** 가야 한다 — 한쪽만으로는 곡선이 정해지지 않는다.
      const heightPx = referenceHeightPx(reference)
      const referencePerson =
        heightPx !== null && reference.x !== '' && reference.y !== ''
          ? {
              // 요청과 저장이 같은 이름이다(§4.5 · §6 모두 `height_px`).
              height_px: heightPx,
              at_m: [Number(reference.x), Number(reference.y)] as [number, number],
            }
          : null
      const derived = rectMode ? rectCoords() : null
      const response = await calibrate(camId, {
        points: points.map((item, index) => ({
          px: item.px,
          m: derived ? derived[index] : ([Number(item.x), Number(item.y)] as [number, number]),
        })),
        reference_person: referencePerson,
      })
      setResult(response.reprojection_error_m)
      setMode('idle')
      setPoints([])
      setEdgeA('')
      setEdgeB('')
      setReference(EMPTY_REFERENCE)
      onDone(
        `cam${camId} 캘리브레이션 저장 — 재투영 오차 ${response.reprojection_error_m.toFixed(3)} m` +
          (response.ref_height_calibrated
            ? ` · 기준 인물 높이 ${heightPx} @ (${reference.x}, ${reference.y}) m`
            : ' · 기준 인물 없음 (카메라 기하로 추정)'),
      )
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setBusy(false)
    }
  }

  const submitZone = async () => {
    setBusy(true)
    try {
      const saved = await saveZone({
        zone_id: zoneId.trim(),
        cam_id: camId,
        name: zoneName.trim() || zoneId.trim(),
        polygon,
        buffer_m: Number(buffer),
        active: true,
      })
      setMode('idle')
      setPolygon([])
      setZoneId('')
      setZoneName('')
      onDone(
        `구역 ${saved.zone_id} 저장 — 지면 좌표 ${saved.polygon_m
          .map(([x, y]) => `(${x}, ${y})`)
          .join(' ')}`,
      )
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setBusy(false)
    }
  }

  const measured = rectMode
    ? rectCoords() !== null
    : points.every((item) => item.x !== '' && item.y !== '')
  const calibrated = camera?.homography ?? null

  // 「적용됐는지 안 됐는지 모르겠다」를 없앤다.
  //
  // 행렬이 있다는 사실만으로는 부족하다 — 시드가 심어 둔 개발용 기본값도 행렬은 있다.
  // 그래서 **화면에서 저장한 것**(`calibrated_at` 이 있다)과 **시드 기본값**(없다)을
  // 갈라서 보여준다. 둘을 뭉뚱그리면 옛 캘리브레이션 위에서 거리를 재면서도
  // "완료"만 보게 된다.
  const calibState = calibrated ? (camera?.calibrated_at ? 'saved' : 'seed') : 'none'

  // 입력한 지면 좌표의 가로·세로 범위. **재투영 오차 대신 이것을 보여준다** —
  // 이 화면은 점을 정확히 4개만 받고, 4점은 언제나 정확히 맞아떨어져 오차가 늘 0 이다
  // (기능명세서 §4.7 「5점 이상 입력하면 오차가 의미를 갖는다」). 0.000 을 띄우면
  // 정확해서 0 인 것처럼 읽힌다. 반면 범위는 넣은 축척이 그대로 되비쳐 나오므로
  // 「6.8 × 10.88 m」를 보고 내 입력이 반영됐음을 바로 확인할 수 있다.
  const calibSpan = (() => {
    const saved = camera?.calib_points ?? []
    if (saved.length === 0) return null
    const xs = saved.map((item) => item.m[0])
    const ys = saved.map((item) => item.m[1])
    return `${(Math.max(...xs) - Math.min(...xs)).toFixed(2)} × ${(Math.max(...ys) - Math.min(...ys)).toFixed(2)} m`
  })()

  // 저장된 구역을 화면에 되그린다.
  //
  // **저장된 픽셀 폴리곤이 있으면 그것을 그대로 그린다**(§4.5). 사용자가 그린 위치가
  // 원본이고, 미터를 매번 역변환하면 캘리브레이션을 다시 할 때마다 도형이 미세하게
  // 움직인다. 픽셀이 없는 옛 구역(마이그레이션 0007 이전)만 역변환으로 대신한다.
  const drawnZones = useMemo(
    () =>
      zones.map((zone) => ({
        zone,
        shape:
          zone.polygon.length > 0
            ? zone.polygon.map((point) => point as [number, number] | null)
            : calibrated
              ? zone.polygon_m.map((point) => groundToPixel(calibrated, point))
              : [],
      })),
    [calibrated, zones],
  )

  return (
    <section className="card">
      <div className="settings__head">
        <h2 className="card__title">카메라 캘리브레이션 · 구역 그리기</h2>
        <div className="settings__tabs">
          {cameras.map((item) => (
            <button
              key={item.cam_id}
              type="button"
              className={item.cam_id === camId ? 'chip chip--on' : 'chip'}
              onClick={() => onSelect(item.cam_id)}
            >
              {/* **DB 가 들고 있는 이름을 쓴다**(§6 `cameras.name`). 다른 화면은 아직
                  `labels.ts` 의 표를 쓰는데, 설치 위치명은 코드가 아니라 설정에 있어야
                  한다 — `docs/INDEX.md` 「남아 있는 확인 필요」에 올려 두었다. */}
              {item.name}
            </button>
          ))}
        </div>
      </div>

      <div
        className={mode === 'idle' ? 'settings__stage' : 'settings__stage settings__stage--picking'}
        onClick={handleClick}
        role="presentation"
      >
        <video ref={videoRef} muted playsInline className="settings__video" />
        <svg className="settings__overlay" viewBox="0 0 100 100" preserveAspectRatio="none">
          {drawnZones.map(({ zone, shape }) =>
            shape.length > 0 && shape.every((point) => point !== null) ? (
              <polygon
                key={zone.zone_id}
                className="settings__zone"
                points={shape
                  .map((point) => `${(point as [number, number])[0] * 100},${(point as [number, number])[1] * 100}`)
                  .join(' ')}
              />
            ) : null,
          )}
          {polygon.length > 1 && (
            <polygon
              className="settings__drawing"
              points={polygon.map(([x, y]) => `${x * 100},${y * 100}`).join(' ')}
            />
          )}
          {points.map((item, index) => (
            <circle
              key={`p${index}`}
              className="settings__point"
              cx={item.px[0] * 100}
              cy={item.px[1] * 100}
              r={1}
            />
          ))}
          {polygon.map(([x, y], index) => (
            <circle
              key={`v${index}`}
              className="settings__vertex"
              cx={x * 100}
              cy={y * 100}
              r={0.8}
            />
          ))}
          {/* 기준 인물 — 발끝에서 머리끝까지의 세로 선. 그 길이가 `height_px` 다. */}
          {reference.foot && reference.head && (
            <line
              className="settings__reference"
              x1={reference.foot[0] * 100}
              y1={reference.foot[1] * 100}
              x2={reference.head[0] * 100}
              y2={reference.head[1] * 100}
            />
          )}
          {[reference.foot, reference.head].map((point, index) =>
            point ? (
              <circle
                key={`r${index}`}
                className="settings__point settings__point--ref"
                cx={point[0] * 100}
                cy={point[1] * 100}
                r={1}
              />
            ) : null,
          )}
        </svg>
        {/* 찍은 순서를 화면에도 숫자로 얹는다. 아래 입력표는 `#` 열로만 점을 구분하는데,
            화면의 점과 표의 줄을 눈으로 잇지 못하면 좌표를 엉뚱한 줄에 넣게 되고
            그러면 호모그래피가 조용히 뒤틀린다.
            SVG 는 `preserveAspectRatio="none"` 이라 글자가 가로로 늘어나므로 HTML 로 얹는다. */}
        {points.map((item, index) => (
          <span
            key={`pn${index}`}
            className="settings__point-no"
            style={{ left: `${item.px[0] * 100}%`, top: `${item.px[1] * 100}%` }}
          >
            {index + 1}
          </span>
        ))}
        <span className="settings__badge">{kind === 'none' ? '재생 불가' : kind.toUpperCase()}</span>
        {mode !== 'idle' && (
          <span className="settings__pick">
            {mode === 'calibrate'
              ? `지면의 표식을 클릭해라 (${points.length}/${REQUIRED_POINTS})`
              : mode === 'reference'
                ? reference.foot === null
                  ? '기준 인물의 **발끝**을 클릭해라'
                  : reference.head === null
                    ? '이제 **머리끝**을 클릭해라'
                    : '두 점을 찍었다 — 아래에 그 자리의 실측 좌표를 넣어라'
                : `구역 꼭짓점을 클릭해라 (${polygon.length}개)`}
          </span>
        )}
      </div>

      <div className="settings__actions">
        <button type="button" className="btn" onClick={() => setMode('calibrate')} disabled={busy}>
          4점 캘리브레이션
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => setMode('reference')}
          disabled={busy || points.length !== REQUIRED_POINTS}
          title={
            points.length === REQUIRED_POINTS
              ? ''
              : '기준 인물은 4점과 함께 저장된다 — 먼저 네 점을 찍어라'
          }
        >
          기준 인물 찍기
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => setMode('zone')}
          disabled={busy || !calibrated}
          title={calibrated ? '' : '먼저 캘리브레이션을 해야 미터로 저장할 수 있다'}
        >
          구역 그리기
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => {
            setMode('idle')
            setPoints([])
            setEdgeA('')
            setEdgeB('')
            setReference(EMPTY_REFERENCE)
            setPolygon([])
          }}
          disabled={busy || mode === 'idle'}
        >
          취소
        </button>
        <span className={`settings__state settings__state--${calibState}`}>
          {calibState === 'saved'
            ? `호모그래피 적용됨 · ${stamp(camera?.calibrated_at ?? null)}` +
              (calibSpan ? ` · 지면 범위 ${calibSpan}` : '')
            : calibState === 'seed'
              ? '호모그래피 있음 — 시드 기본값이다 (이 화면에서 저장한 적 없음)'
              : '호모그래피 없음 — 구역을 저장할 수 없다'}
          {camera?.ref_height
            ? ` · 기준 인물 ${camera.ref_height.height_px} @ (${camera.ref_height.at_m[0]}, ${camera.ref_height.at_m[1]}) m`
            : ' · 기준 인물 없음'}
        </span>
      </div>

      {mode === 'calibrate' && (
        <div className="settings__form">
          <p className="card__note">
            네 점이 한 직선 위에 있으면 서버가 거부한다. 바닥에 <strong>직사각형</strong>으로
            찍었다면 아래에서 <strong>변 길이 두 개</strong>만 넣으면 되고, 좌표는 화면이
            계산한다.
          </p>
          {/* 좌표를 손으로 넣는 길을 없애지는 않는다 — 사다리꼴로 찍어야 하는 현장이
              있고(기둥·설비가 직사각형을 가로막는다), 그때는 점마다 좌표가 필요하다. */}
          <div className="settings__modes">
            <button
              type="button"
              className={rectMode ? 'chip chip--on' : 'chip'}
              onClick={() => setRectMode(true)}
            >
              직사각형 · 변 길이만 입력
            </button>
            <button
              type="button"
              className={rectMode ? 'chip' : 'chip chip--on'}
              onClick={() => setRectMode(false)}
            >
              점마다 좌표 입력
            </button>
          </div>
          {/* 기능명세서 §4.7 FN-CFG-01 「캘리브레이션과 축척」.
              현장에서 잘못 입력하면 M9 에서 임계값을 전부 다시 만져야 하므로,
              규칙을 입력란 바로 옆에 둔다. */}
          <ul className="settings__rules">
            <li>
              기준점 4개는 <strong>모두 같은 바닥 평면</strong> 위에 있어야 한다. 높이가 다른
              점을 섞으면 지면 대 지면 변환이 성립하지 않는다.
            </li>
            <li>
              모형 시연에서는 <strong>자로 잰 값을 그대로</strong> 넣는다 — 16cm 면{' '}
              <code>16</code> 이다. 환산하지 마라.
            </li>
            <li>
              <strong>축척은 임계값 쪽에서 이미 환산해 두었다.</strong> 위험 반경 3.0m ·
              근접 2.0m · 보행 속도 1.5m/s 라는 현장 기준값을 모형 배율(인물 4cm ↔ 1.7m ·
              42.5배)로 나눈 값이 <code>policies</code> 에 심겨 있다. 여기서 또 환산하면
              이중 환산이 되어 거리 판정이 통째로 틀어진다.
            </li>
            <li>
              기준 인물(<code>ref_height</code>)의 지면 좌표도 <strong>4점과 같은 단위</strong>로
              넣는다. <strong>화면상 높이와 그 사람이 서 있던 지면 좌표를 함께</strong> 넣어야
              한다 — 같은 사람도 카메라에서 멀수록 화면상 높이가 줄어들므로, 위치 없는 높이
              하나로는 다른 거리의 기대 높이를 구할 수 없다.
            </li>
            <li>카메라를 고정한 뒤에 찍어라. 이후 카메라를 움직이면 캘리브레이션은 무효다.</li>
          </ul>
          {rectMode ? (
            <div className="settings__rect">
              <label className="settings__rect-field">
                <span>
                  <strong>1 → 2</strong> 변 길이
                </span>
                <input
                  value={edgeA}
                  inputMode="decimal"
                  placeholder="예: 25.6"
                  onChange={(event) => setEdgeA(event.target.value)}
                />
              </label>
              <label className="settings__rect-field">
                <span>
                  <strong>2 → 3</strong> 변 길이
                </span>
                <input
                  value={edgeB}
                  inputMode="decimal"
                  placeholder="예: 16"
                  onChange={(event) => setEdgeB(event.target.value)}
                />
              </label>
              {/* 무엇이 저장될지 저장 전에 보여준다 — 축척을 잘못 넣으면 거리 판정이
                  통째로 틀어지는데, 저장한 뒤에야 알아채면 이미 늦다. */}
              <p className="settings__rect-preview">
                {points.length < REQUIRED_POINTS
                  ? `네 점을 순서대로 찍어라 (${points.length}/${REQUIRED_POINTS})`
                  : rectCoords()
                    ? `저장될 좌표 — ${rectCoords()!
                        .map(([x, y], index) => `${index + 1}:(${x}, ${y})`)
                        .join('  ')}`
                    : '두 변의 길이를 넣어라 (0보다 큰 수)'}
              </p>
            </div>
          ) : (
          <table className="settings__table">
            <thead>
              <tr>
                <th>#</th>
                <th>화면 좌표</th>
                <th>실측 X</th>
                <th>실측 Y</th>
              </tr>
            </thead>
            <tbody>
              {points.map((item, index) => (
                <tr key={index}>
                  <td>{index + 1}</td>
                  <td>
                    {item.px[0].toFixed(3)}, {item.px[1].toFixed(3)}
                  </td>
                  <td>
                    <input
                      value={item.x}
                      inputMode="decimal"
                      onChange={(event) => {
                        const next = [...points]
                        next[index] = { ...item, x: event.target.value }
                        setPoints(next)
                      }}
                    />
                  </td>
                  <td>
                    <input
                      value={item.y}
                      inputMode="decimal"
                      onChange={(event) => {
                        const next = [...points]
                        next[index] = { ...item, y: event.target.value }
                        setPoints(next)
                      }}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          )}
          <ReferenceFields
            reference={reference}
            picking={false}
            onPick={() => setMode('reference')}
            onChange={setReference}
            onClear={() => setReference(EMPTY_REFERENCE)}
          />
          <button
            type="button"
            className="btn btn--primary"
            disabled={busy || points.length !== REQUIRED_POINTS || !measured}
            onClick={() => void submitCalibration()}
          >
            호모그래피 산출·저장
          </button>
        </div>
      )}

      {mode === 'reference' && (
        <div className="settings__form">
          <p className="card__note">
            기준 인물의 <strong>발끝 → 머리끝</strong> 순서로 두 점을 클릭한 뒤, 그 사람이
            서 있던 자리의 <strong>실측 지면 좌표(m)</strong>를 넣어라. 4점과 같은 줄자 ·
            같은 원점이어야 한다.
          </p>
          <ReferenceFields
            reference={reference}
            picking
            onPick={() => setReference(EMPTY_REFERENCE)}
            onChange={setReference}
            onClear={() => setReference(EMPTY_REFERENCE)}
          />
          <button
            type="button"
            className="btn btn--primary"
            disabled={busy || referenceHeightPx(reference) === null}
            onClick={() => setMode('calibrate')}
          >
            4점 입력으로 돌아가기
          </button>
        </div>
      )}

      {mode === 'zone' && (
        <div className="settings__form">
          <p className="card__note">
            폴리곤을 그린 뒤 저장하면 <strong>서버가 호모그래피로 지면 좌표(m)로 변환해</strong>{' '}
            저장한다(§4.5). 화면은 픽셀만 보내므로 변환 코드가 한 곳에만 있다.
          </p>
          <div className="settings__row">
            <label>
              구역 ID
              <input
                value={zoneId}
                placeholder="forklift_lane"
                onChange={(event) => setZoneId(event.target.value)}
              />
            </label>
            <label>
              표시 이름
              <input
                value={zoneName}
                placeholder="지게차 통행로"
                onChange={(event) => setZoneName(event.target.value)}
              />
            </label>
            <label>
              경계 여유 (m)
              <input
                value={buffer}
                inputMode="decimal"
                onChange={(event) => setBuffer(event.target.value)}
              />
            </label>
          </div>
          <button
            type="button"
            className="btn btn--primary"
            disabled={busy || polygon.length < MIN_VERTICES || zoneId.trim() === ''}
            onClick={() => void submitZone()}
          >
            구역 저장 ({polygon.length}각형)
          </button>
        </div>
      )}

      {result !== null && (
        <p className={result > ERROR_WARN_M ? 'settings__warn' : 'settings__ok'}>
          재투영 오차 <strong>{result.toFixed(3)} m</strong>
          {result > ERROR_WARN_M
            ? ' — 큰 편이다. 표식을 잘못 찍었거나 실측값이 어긋났을 수 있다'
            : ' — 이 값이 곧 거리·구역 판정의 오차 하한이다'}
        </p>
      )}
    </section>
  )
}

/**
 * 기준 인물 입력란 (FN-CFG-01 · 기능명세서 §6 `cameras.ref_height`).
 *
 * 높이와 위치를 **한 칸에 묶어** 보여준다. 둘을 따로 두면 높이만 넣고 위치를 빠뜨린
 * 채 저장하기 쉬운데, 그렇게 저장된 기준은 다른 거리에서 쓸 수 없다.
 */
function ReferenceFields({
  reference,
  picking,
  onPick,
  onChange,
  onClear,
}: {
  reference: PendingReference
  picking: boolean
  onPick: () => void
  onChange: (next: PendingReference) => void
  onClear: () => void
}) {
  const heightPx = referenceHeightPx(reference)
  return (
    <div className="settings__reference-form">
      <div className="settings__row">
        <span className="settings__reference-label">
          기준 인물 <em>(선택)</em>
        </span>
        <span className="settings__reference-value">
          {heightPx === null
            ? picking
              ? '영상에서 발끝 · 머리끝을 클릭해라'
              : '찍지 않음 — 카메라 기하로 기대 높이를 추정한다'
            : `화면상 높이 ${heightPx}`}
        </span>
        <button type="button" className="btn btn--ghost" onClick={onPick}>
          {picking ? '다시 찍기' : '영상에서 찍기'}
        </button>
        {heightPx !== null && (
          <button type="button" className="btn btn--ghost" onClick={onClear}>
            지우기
          </button>
        )}
      </div>
      <div className="settings__row">
        <label>
          기준 인물 실측 X (m)
          <input
            value={reference.x}
            inputMode="decimal"
            placeholder="6.0"
            onChange={(event) => onChange({ ...reference, x: event.target.value })}
          />
        </label>
        <label>
          기준 인물 실측 Y (m)
          <input
            value={reference.y}
            inputMode="decimal"
            placeholder="9.0"
            onChange={(event) => onChange({ ...reference, y: event.target.value })}
          />
        </label>
      </div>
      {heightPx !== null && (reference.x === '' || reference.y === '') && (
        <p className="card__note">
          위치를 넣지 않으면 <strong>기준 인물이 저장되지 않는다.</strong> 높이 하나만으로는
          다른 거리의 기대 높이를 구할 수 없다(기능명세서 §6).
        </p>
      )}
    </div>
  )
}

function ZoneList({
  zones,
  camName,
  onDeleted,
  onError,
}: {
  zones: Zone[]
  camName: string
  onDeleted: (zoneId: string) => void
  onError: (message: string) => void
}) {
  return (
    <section className="card">
      <h2 className="card__title">금지구역 · {camName}</h2>
      {zones.length === 0 ? (
        <p className="card__note">등록된 구역이 없다. 위에서 폴리곤을 그려 저장해라.</p>
      ) : (
        <table className="settings__table">
          <thead>
            <tr>
              <th>ID</th>
              <th>이름</th>
              <th>꼭짓점 (지면 m)</th>
              <th>여유</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {zones.map((zone) => (
              <tr key={zone.zone_id}>
                <td>
                  <code>{zone.zone_id}</code>
                </td>
                <td>{zone.name}</td>
                <td className="settings__polygon">
                  {zone.polygon_m.map(([x, y]) => `(${x}, ${y})`).join(' ')}
                </td>
                <td>{zone.buffer_m} m</td>
                <td>
                  <button
                    type="button"
                    className="btn btn--ghost"
                    onClick={() => {
                      void deleteZone(zone.zone_id, zone.cam_id)
                        .then(() => onDeleted(zone.zone_id))
                        .catch((cause: unknown) =>
                          onError(cause instanceof Error ? cause.message : String(cause)),
                        )
                    }}
                  >
                    삭제
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

/* ------------------------------------------------------------------ */
/* FN-CFG-03 — 경고 음원 매핑                                           */
/* ------------------------------------------------------------------ */

function SoundPanel({
  sounds,
  onSaved,
  onError,
}: {
  sounds: AlertSound[]
  onSaved: (message: string) => void
  onError: (message: string) => void
}) {
  const [draft, setDraft] = useState<Record<string, AlertSound>>({})

  const value = (item: AlertSound): AlertSound => draft[item.violation_type] ?? item
  const edit = (item: AlertSound, patch: Partial<AlertSound>) =>
    setDraft({ ...draft, [item.violation_type]: { ...value(item), ...patch } })

  const commit = (item: AlertSound) => {
    const next = value(item)
    void saveAlertSound(item.violation_type, {
      file_path: next.file_path,
      level: next.level,
      label: next.label,
      active: next.active,
    })
      .then((saved) => {
        setDraft((current) => {
          const copy = { ...current }
          delete copy[item.violation_type]
          return copy
        })
        onSaved(`${violationLabel(saved.violation_type)} 음원을 저장했다`)
      })
      .catch((cause: unknown) => onError(cause instanceof Error ? cause.message : String(cause)))
  }

  return (
    <section className="card">
      <h2 className="card__title">경고 음원 매핑</h2>
      <p className="card__note">
        위반 유형별 <strong>사전 녹음 wav</strong> 다(TTS 가 아니다 · FN-ALM-01). 등급은 §3{' '}
        <code>AlertCommand.level</code> 과 §5.2 <code>severity</code> 의 원천이며,{' '}
        <strong>쓰러짐은 3 미만으로 내릴 수 없다</strong> — 스스로 시정할 수 없는 유일한
        유형이라 등급을 낮추면 긴급 상황에서 부저가 울리지 않는다.
      </p>
      <table className="settings__table">
        <thead>
          <tr>
            <th>유형</th>
            <th>표시 이름</th>
            <th>파일</th>
            <th>등급</th>
            <th>사용</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {sounds.map((item) => {
            const current = value(item)
            const dirty = draft[item.violation_type] !== undefined
            return (
              <tr key={item.violation_type}>
                <td>
                  <code>{item.violation_type}</code>
                </td>
                <td>
                  <input
                    value={current.label ?? ''}
                    onChange={(event) => edit(item, { label: event.target.value || null })}
                  />
                </td>
                <td>
                  <input
                    value={current.file_path}
                    onChange={(event) => edit(item, { file_path: event.target.value })}
                  />
                </td>
                <td>
                  <select
                    value={current.level}
                    onChange={(event) =>
                      edit(item, { level: Number(event.target.value) as AlertSound['level'] })
                    }
                  >
                    <option value={1}>1 · 주의</option>
                    <option value={2}>2 · 경고</option>
                    <option value={3}>3 · 긴급</option>
                  </select>
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={current.active}
                    onChange={(event) => edit(item, { active: event.target.checked })}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="btn btn--ghost"
                    disabled={!dirty}
                    onClick={() => commit(item)}
                  >
                    저장
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </section>
  )
}

/* ------------------------------------------------------------------ */
/* FN-CFG-04 — 임계값                                                   */
/* ------------------------------------------------------------------ */

function PolicyPanel({
  policies,
  onSaved,
  onError,
}: {
  policies: Policies | null
  onSaved: (next: Policies, message: string) => void
  onError: (message: string) => void
}) {
  const [draft, setDraft] = useState<Partial<Record<keyof Policies, string>>>({})

  if (!policies) {
    return (
      <section className="card">
        <h2 className="card__title">임계값 · 타이머</h2>
        <p className="card__note">정책값을 읽지 못했다. 서버와 DB 가 떠 있는지 확인해라.</p>
      </section>
    )
  }

  const changed = Object.entries(draft).filter(
    ([key, text]) => text !== undefined && Number(text) !== policies[key as keyof Policies],
  )

  const commit = () => {
    const patch = Object.fromEntries(changed.map(([key, text]) => [key, Number(text)]))
    void savePolicies(patch)
      .then((next) => {
        setDraft({})
        onSaved(next, `임계값 ${Object.keys(patch).length}개를 저장했다 — 재시작 없이 반영된다`)
      })
      .catch((cause: unknown) => onError(cause instanceof Error ? cause.message : String(cause)))
  }

  return (
    <section className="card">
      <h2 className="card__title">임계값 · 타이머</h2>
      <p className="card__note">
        원본은 DB <code>policies</code> 하나이며 <strong>저장 즉시 상태머신에 반영된다</strong>
        (재시작하지 않는다 · FN-CFG-04). 진행 중인 이벤트도 새 값으로 판정된다.
      </p>
      <div className="settings__grid">
        {POLICY_FIELDS.map(({ key, label, unit, hint }) => (
          <label key={key} className="settings__field">
            <span className="settings__label">
              {label}
              {unit && <em> ({unit})</em>}
            </span>
            <input
              value={draft[key] ?? String(policies[key])}
              inputMode="decimal"
              onChange={(event) => setDraft({ ...draft, [key]: event.target.value })}
            />
            <span className="settings__hintline">{hint}</span>
          </label>
        ))}
      </div>
      <button
        type="button"
        className="btn btn--primary"
        disabled={changed.length === 0}
        onClick={commit}
      >
        변경한 {changed.length}개 저장
      </button>
    </section>
  )
}

/* ------------------------------------------------------------------ */
/* FN-CFG-05 — 위험 반경                                                */
/* ------------------------------------------------------------------ */

function VehiclePanel({
  classes,
  onSaved,
  onError,
}: {
  classes: VehicleClass[]
  onSaved: (next: VehicleClass, message: string) => void
  onError: (message: string) => void
}) {
  const [draft, setDraft] = useState<Record<string, string>>({})

  const fail = (cause: unknown) => onError(cause instanceof Error ? cause.message : String(cause))

  return (
    <section className="card">
      <h2 className="card__title">위험 반경</h2>
      <p className="card__note">
        지게차를 따라다니는 <strong>동적 위험 영역</strong>이다(기본 3.0m). 즉시 경고 기준인
        근접 임계값(<code>proximity_threshold_m</code>)과 2단계로 동작한다 — 둘은 다른 값이다.
      </p>
      <table className="settings__table">
        <thead>
          <tr>
            <th>클래스</th>
            <th>위험 반경 (m)</th>
            <th>사용</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {classes.map((item) => {
            const text = draft[item.class_name] ?? String(item.danger_radius_m)
            return (
              <tr key={item.class_name}>
                <td>
                  <code>{item.class_name}</code>
                </td>
                <td>
                  <input
                    value={text}
                    inputMode="decimal"
                    onChange={(event) =>
                      setDraft({ ...draft, [item.class_name]: event.target.value })
                    }
                  />
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={item.active}
                    onChange={(event) => {
                      void saveVehicleClass(item.class_name, { active: event.target.checked })
                        .then((next) => onSaved(next, `${next.class_name} 사용 여부를 바꿨다`))
                        .catch(fail)
                    }}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="btn btn--ghost"
                    disabled={Number(text) === item.danger_radius_m}
                    onClick={() => {
                      void saveVehicleClass(item.class_name, { danger_radius_m: Number(text) })
                        .then((next) => {
                          setDraft((current) => {
                            const copy = { ...current }
                            delete copy[item.class_name]
                            return copy
                          })
                          onSaved(next, `${next.class_name} 위험 반경 ${next.danger_radius_m}m`)
                        })
                        .catch(fail)
                    }}
                  >
                    저장
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </section>
  )
}
