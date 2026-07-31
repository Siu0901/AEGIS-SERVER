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
import { cameraName, retentionLabel, stamp, violationLabel } from '../types/labels'
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

type Mode = 'idle' | 'calibrate' | 'zone'

type PendingPoint = { px: [number, number]; x: string; y: string }

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
        camName={camera?.name ?? cameraName(camId)}
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
    setPolygon([])
    setResult(null)
  }, [camId])

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
    } else {
      setPolygon((current) => [...current, point])
    }
  }

  const submitCalibration = async () => {
    setBusy(true)
    try {
      const response = await calibrate(camId, {
        points: points.map((item) => ({
          px: item.px,
          m: [Number(item.x), Number(item.y)] as [number, number],
        })),
        reference_person: null,
      })
      setResult(response.reprojection_error_m)
      setMode('idle')
      setPoints([])
      onDone(
        `cam${camId} 캘리브레이션 저장 — 재투영 오차 ${response.reprojection_error_m.toFixed(3)} m`,
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

  const measured = points.every((item) => item.x !== '' && item.y !== '')
  const calibrated = camera?.homography ?? null

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
        </svg>
        <span className="settings__badge">{kind === 'none' ? '재생 불가' : kind.toUpperCase()}</span>
        {mode !== 'idle' && (
          <span className="settings__pick">
            {mode === 'calibrate'
              ? `지면의 표식을 클릭해라 (${points.length}/${REQUIRED_POINTS})`
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
            setPolygon([])
          }}
          disabled={busy || mode === 'idle'}
        >
          취소
        </button>
        <span className="settings__state">
          {calibrated
            ? `캘리브레이션 완료 · ${stamp(camera?.calibrated_at ?? null)}`
            : '캘리브레이션 없음 — 구역을 저장할 수 없다'}
        </span>
      </div>

      {mode === 'calibrate' && (
        <div className="settings__form">
          <p className="card__note">
            찍은 네 점의 <strong>실측 지면 좌표(m)</strong>를 입력해라. 첫 점을 원점(0, 0)으로
            두는 것이 편하다. 네 점이 한 직선 위에 있으면 서버가 거부한다.
          </p>
          {/* 기능명세서 §4.7 FN-CFG-01 「캘리브레이션과 축척」.
              현장에서 잘못 입력하면 M9 에서 임계값을 전부 다시 만져야 하므로,
              규칙을 입력란 바로 옆에 둔다. */}
          <ul className="settings__rules">
            <li>
              기준점 4개는 <strong>모두 같은 바닥 평면</strong> 위에 있어야 한다. 높이가 다른
              점을 섞으면 지면 대 지면 변환이 성립하지 않는다.
            </li>
            <li>
              모형 시연에서는 모형의 실측 치수가 아니라 <strong>환산 미터</strong>를 넣는다 —
              1:20 모형에서 15cm 떨어진 두 점이면 <code>0.15</code> 가 아니라{' '}
              <code>3.0</code> 이다.
            </li>
            <li>
              <strong>임계값을 축척에 맞춰 바꾸지 마라.</strong> 위험 반경 3.0m · 근접 2.0m ·
              보행 속도 1.5m/s 는 KOSHA 기준과 실제 보행 속도에서 나온 값이고, 축척 변환은
              캘리브레이션이 혼자 흡수한다. 실물 현장으로 옮길 때 다시 하는 것은
              캘리브레이션뿐이다.
            </li>
            <li>
              기준 인물 높이(<code>ref_height_px_at_m</code>)도 <strong>실제 작업자 신장
              (약 1.7m)</strong> 기준으로 입력해야 쓰러짐 판정이 명세서 임계값 그대로 돈다.
            </li>
            <li>카메라를 고정한 뒤에 찍어라. 이후 카메라를 움직이면 캘리브레이션은 무효다.</li>
          </ul>
          <table className="settings__table">
            <thead>
              <tr>
                <th>#</th>
                <th>화면 좌표</th>
                <th>실측 X (m)</th>
                <th>실측 Y (m)</th>
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
