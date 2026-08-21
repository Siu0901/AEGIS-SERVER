/**
 * 카메라 한 대의 라이브 타일 (FN-UI-02).
 *
 * 화면 구석의 **표시 시각**이 이 컴포넌트의 핵심이다.
 * `requestVideoFrameCallback` 은 "지금 화면에 나가는 프레임"의 표시 예정 시각을
 * 알려주는 유일한 수단이고, 그 값과 영상에 소성된 카메라 타임코드를 나란히 보면
 * 영상 경로의 지연을 눈으로 잴 수 있다. M2 에서 오버레이를 `ts` 기준 지연 버퍼에
 * 담아 그릴 때, 이 시각이 "재생 중인 프레임 시각"의 기준이 된다.
 */

import { useEffect, useRef, useState } from 'react'
import type { CameraStatus, OverlayPolicies, StreamState, Zone } from '../types/system'
import OverlayCanvas, { type OverlayDebug } from './OverlayCanvas'
import QuickControls from './QuickControls'
import {
  OVERLAY_BUFFER_POLICY_KEY,
  preferenceFromLocation,
  startPlayback,
  type PlaybackKind,
} from './player'

const WHEP_BASE = __MEDIAMTX_WHEP__
const HLS_BASE = __MEDIAMTX_HLS__

const STATE_LABEL: Record<StreamState, string> = {
  ok: '정상',
  reconnecting: '재연결 중',
  down: '끊김',
}

const STATE_TONE: Record<StreamState, string> = {
  ok: 'ok',
  reconnecting: 'warn',
  down: 'danger',
}

const KIND_LABEL: Record<PlaybackKind, string> = {
  webrtc: 'WebRTC',
  hls: 'HLS',
  none: '재생 불가',
}

type Props = {
  camera: CameraStatus
  /** 화면에 띄우는 이름. 시안의 건설현장 용어 대신 제조현장 기준으로 붙인다(부록 B). */
  name: string
  /** 이 채널만 확대해 보고 있는가 (FN-UI-02 단독 확대 보기). */
  solo: boolean
  /** 타일 클릭 — 확대 진입·복귀. */
  onToggleSolo: () => void
  /** 오버레이 지연 버퍼 정책값(§4.5). `null` 이면 오버레이를 그리지 않는다. */
  policies: OverlayPolicies | null
  /** 캐시된 금지구역(§4.5 · §5.4). 라벨의 구역 표시 이름에 쓴다. */
  zones: Zone[]
  /** 개발용 정합 진단 표시 (FN-UI-02). 꺼져 있으면 계산도 하지 않는다. */
  debug: boolean
}

export default function CameraTile({
  camera,
  name,
  solo,
  onToggleSolo,
  policies,
  zones,
  debug,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [kind, setKind] = useState<PlaybackKind>('none')
  const [error, setError] = useState<string | null>(null)
  // 끊겨서 다시 붙는 중인가. **화면에 반드시 드러낸다** — 재연결 중에는 직전
  // 프레임이 그대로 남아 있어서, 표시하지 않으면 멈춘 그림이 살아 있는 영상으로
  // 보인다. 관제자는 그것을 「위반이 없다」로 읽는다.
  const [retrying, setRetrying] = useState(false)
  const [displayAt, setDisplayAt] = useState<string>('—')
  const [size, setSize] = useState<string>('—')
  const [probe, setProbe] = useState<OverlayDebug | null>(null)
  // **기본은 접힌 상태다.** 펼친 채로 두면 타일이 밀려 영상이 작아지는데, 이 화면의
  // 주역은 영상이다. 필요할 때만 열어 쓴다.
  const [controlsOpen, setControlsOpen] = useState(false)

  const path = `cam${camera.cam_id}/main`
  const live = camera.main_state === 'ok'

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    // 스트림이 죽어 있으면 붙지 않는다. 죽은 경로를 계속 두드리면 브라우저 콘솔이
    // 오류로 가득 차서 진짜 문제가 묻힌다. 살아나면 이 effect 가 다시 돈다.
    if (!live) {
      setKind('none')
      setRetrying(false)
      setDisplayAt('—')
      return
    }

    const handle = startPlayback(
      video,
      { whep: `${WHEP_BASE}/${path}/whep`, hls: `${HLS_BASE}/${path}/index.m3u8` },
      (state) => {
        setKind(state.kind)
        setError(state.error)
        setRetrying(state.retrying)
      },
      preferenceFromLocation(window.location.search),
    )
    return () => handle.stop()
  }, [live, path])

  // 해상도는 프레임 콜백과 따로 채운다. `requestVideoFrameCallback` 은 창이 실제로
  // 그려질 때만 불리므로(백그라운드 탭 등), 거기에만 기대면 재생 중인데도 해상도가
  // 비어 보인다. 해상도는 라이브 여부와 무관한 사실이라 메타데이터에서 바로 읽는다.
  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const update = () => {
      if (video.videoWidth) setSize(`${video.videoWidth}×${video.videoHeight}`)
    }
    update()
    video.addEventListener('loadedmetadata', update)
    video.addEventListener('resize', update)
    return () => {
      video.removeEventListener('loadedmetadata', update)
      video.removeEventListener('resize', update)
    }
  }, [kind])

  useEffect(() => {
    const video = videoRef.current
    if (!video || typeof video.requestVideoFrameCallback !== 'function') return

    let handle = 0
    let cancelled = false

    const onFrame: VideoFrameRequestCallback = (_now, metadata) => {
      if (cancelled) return
      // `expectedDisplayTime` 은 `performance.now()` 기준이다. `timeOrigin` 을 더하면
      // 그 프레임이 화면에 나가는 **벽시계 시각**이 된다. 영상에 소성된 카메라
      // 타임코드와 이 값의 차이가 곧 영상 경로 지연이다.
      const wall = performance.timeOrigin + metadata.expectedDisplayTime
      setDisplayAt(formatUtc(wall))
      handle = video.requestVideoFrameCallback(onFrame)
    }

    handle = video.requestVideoFrameCallback(onFrame)
    return () => {
      cancelled = true
      video.cancelVideoFrameCallback(handle)
    }
  }, [kind])

  const bufferKey = OVERLAY_BUFFER_POLICY_KEY[kind]

  return (
    <figure className={`tile tile--${STATE_TONE[camera.main_state]} ${solo ? 'tile--solo' : ''}`}>
      <div className="tile__frame">
        <video ref={videoRef} muted playsInline autoPlay className="tile__video" />

        {/* 오버레이는 정규화 좌표라 확대 여부와 무관하게 같은 자리에 붙는다(FN-UI-02). */}
        {live && (
          <OverlayCanvas
            camId={camera.cam_id}
            videoRef={videoRef}
            kind={kind}
            policies={policies}
            zones={zones}
            onDebug={debug ? setProbe : undefined}
          />
        )}

        {debug && live && <DebugPanel probe={probe} policies={policies} />}

        {/* 영상 위를 덮는 클릭 판. `video` 에 직접 걸면 브라우저 기본 컨트롤과 겹친다. */}
        <button
          type="button"
          className="tile__hit"
          onClick={onToggleSolo}
          aria-label={solo ? `${name} 분할 보기로` : `${name} 단독 확대`}
          title={solo ? '분할 보기로 (Esc)' : '이 채널만 확대'}
        />

        {!live && (
          <div className="tile__offline">
            <span className="tile__offline-title">{STATE_LABEL[camera.main_state]}</span>
            <span className="tile__offline-note">
              {camera.main_state === 'reconnecting'
                ? '메인 스트림 재연결을 시도하고 있다'
                : '메인 스트림이 끊겼다 — 이 시간대의 녹화·클립이 남지 않는다'}
            </span>
          </div>
        )}

        {live && (
          <div className="tile__clock" title="현재 재생 중인 프레임의 표시 시각 (UTC)">
            표시 {displayAt}
          </div>
        )}
      </div>

      <figcaption className="tile__bar">
        <span className={`dot dot--${STATE_TONE[camera.main_state]}`} />
        <span className="tile__name">{name}</span>
        <span className="tile__meta">{live ? size : '—'}</span>
        {/* 재생 경로를 계속 표시한다 — 경로마다 오버레이 지연 버퍼가 다르므로(§4.5),
            오버레이가 어긋날 때 원인을 가르는 첫 단서다(FN-UI-02). */}
        <span
          className="tile__meta"
          title={
            bufferKey
              ? `오버레이 지연 버퍼는 ${bufferKey}${
                  policies ? ` = ${policies[bufferKey]}ms` : ' (정책값 미수신)'
                }`
              : undefined
          }
        >
          {live ? KIND_LABEL[kind] : STATE_LABEL[camera.main_state]}
          {live && bufferKey && policies && ` +${Math.round(policies[bufferKey])}ms`}
        </span>
        {/* 재연결은 몇 초 만에 끝나기도 하지만, 끝나지 않을 수도 있다. 어느 쪽이든
            지금 화면이 실시간이 아니라는 사실은 그 동안 계속 보여야 한다. */}
        {live && retrying && (
          <span
            className="tile__meta tile__meta--warn"
            title="영상이 끊겨 다시 붙는 중이다. 지금 보이는 그림은 마지막으로 도착한 프레임이며 실시간이 아니다."
          >
            재연결 중
          </span>
        )}
        {/* 정책값을 못 읽으면 오버레이를 안 그린다. 조용히 비어 있으면 "위반이 없다"로
            읽히는데, 그 오해가 이 화면에서 가장 위험하다. */}
        {live && !policies && (
          <span
            className="tile__meta tile__meta--warn"
            title="GET /policies 를 읽지 못해 지연 버퍼를 모른다. 어긋난 박스는 없는 박스보다 나쁘므로 그리지 않는다."
          >
            오버레이 대기
          </span>
        )}
        <span className="tile__spacer" />
        {/* REC 표시는 REC 컴포넌트(§4.7)의 `cameras[].recording` 을 그대로 쓴다.
            라이브가 보인다고 녹화 중인 것이 아니다 — 둘은 다른 프로세스다.
            `null` 은 REC 미도달("알 수 없다")이라 켜지도 꺼지지도 않는다. */}
        <span
          className={`tile__rec ${camera.recording ? 'tile__rec--on' : ''} ${
            camera.recording === null ? 'tile__rec--unknown' : ''
          }`}
          title={
            camera.recording === null
              ? 'REC 에 닿지 못해 녹화 여부를 알 수 없다 (측정 불가)'
              : camera.recording
                ? 'REC 이 이 카메라를 녹화 중이다'
                : 'REC 은 살아 있으나 이 카메라를 녹화하고 있지 않다'
          }
        >
          REC{camera.recording === null ? ' ?' : ''}
        </span>
      </figcaption>

      {error && <p className="tile__error">{error}</p>}

      {/* 빠른 제어를 이 타일에 붙인다 — 대상 카메라를 고르는 단계를 없애려는 것이다.
          우측 패널에 하나만 두면 「지금 보고 있는 이 채널」과 「선택된 대상」이 어긋날 수
          있고, 방송은 잘못 나가면 되돌릴 수 없다. */}
      <details
        className="tile__controls"
        open={controlsOpen}
        onToggle={(event) => setControlsOpen((event.currentTarget as HTMLDetailsElement).open)}
      >
        <summary className="tile__controls-head">
          <span className="tile__controls-caret" aria-hidden="true" />
          빠른 제어
        </summary>
        <div className="tile__controls-body">
          <QuickControls camId={camera.cam_id} embedded />
        </div>
      </details>
    </figure>
  )
}

/**
 * 개발용 정합 진단 표시 (FN-UI-02).
 *
 * **버퍼 값은 실제로 적용된 것을 그대로 받아 적는다.** 화면에 따로 계산한 값을 적으면
 * 버퍼가 잘못 걸렸을 때 그 사실이 표시에 가려진다 — 실제로 그 착각 때문에 좌표 지연
 * 2.8초의 원인을 한 번 놓쳤다.
 *
 * `차이` 는 `표시 시각 − 그린 좌표 ts` 이고 **적용 버퍼와 같아야 한다.** 다르면 버퍼가
 * 의도한 대로 걸리지 않은 것이다. 영상과의 실제 정합 오차는 이 값이 아니라
 * marker 검증(`uv run tasks.py marker`)으로 잰다.
 */
function DebugPanel({
  probe,
  policies,
}: {
  probe: OverlayDebug | null
  policies: OverlayPolicies | null
}) {
  if (!policies) {
    return <div className="tile__debug">정책값 미수신 — 오버레이를 그리지 않는다</div>
  }
  if (!probe) {
    return <div className="tile__debug">프레임 콜백 대기 중…</div>
  }
  const matched = Math.abs((probe.deltaMs ?? 0) - probe.bufferMs) < 1
  return (
    <div className="tile__debug">
      <div>
        <span>표시 프레임</span>
        <b>{formatUtc(probe.displayAt)}</b>
      </div>
      <div>
        <span>그린 좌표 ts</span>
        <b>{probe.overlayTs === null ? '없음' : formatUtc(probe.overlayTs)}</b>
      </div>
      <div className={matched ? '' : 'tile__debug--bad'}>
        <span>차이</span>
        <b>{probe.deltaMs === null ? '—' : `${Math.round(probe.deltaMs)} ms`}</b>
      </div>
      <div>
        <span>적용 버퍼</span>
        <b>
          {Math.round(probe.bufferMs)} ms · {probe.bufferKey}
        </b>
      </div>
      <div>
        <span>재생 경로</span>
        <b>{probe.kind}</b>
      </div>
      <div className={(probe.arrivalLagMs ?? 0) > 1000 ? 'tile__debug--bad' : ''}>
        <span>좌표 도착 지연</span>
        <b>{probe.arrivalLagMs === null ? '수신 없음' : `${Math.round(probe.arrivalLagMs)} ms`}</b>
      </div>
      <div>
        <span>버퍼 적재 / 낡음</span>
        <b>
          {probe.buffered}건 · {probe.ageMs === null ? '—' : `${Math.round(probe.ageMs)} ms`}
        </b>
      </div>
      {/* ★ 고정 버퍼를 대체할 수 있는가 — 브라우저가 **프레임 촬영 시각**을 주는지 본다.
          `captureTime` 이 있으면 그 값으로 직접 정합할 수 있고, 지금 남아 있는 지터의
          원인(고정 버퍼)이 사라진다. 없으면 이 줄이 「없음」으로 남아 고정 버퍼를 쓰는
          이유가 화면에 드러난다(§5 구현 전제 · docs/INDEX.md M5 절). */}
      <div>
        <span>촬영 시각(rVFC)</span>
        <b>
          {probe.captureTimeMs === null ? '없음 — 고정 버퍼 사용' : formatUtc(probe.captureTimeMs)}
        </b>
      </div>
      {probe.captureLagMs !== null && (
        <div
          className={
            Math.abs(probe.captureLagMs - probe.bufferMs) > 100 ? 'tile__debug--bad' : ''
          }
        >
          {/* 이 값이 적용 버퍼와 100ms 이상 다르면 버퍼 기본값을 그만큼 고쳐야 한다. */}
          <span>실제 영상 지연</span>
          <b>
            {Math.round(probe.captureLagMs)} ms (버퍼 대비{' '}
            {Math.round(probe.captureLagMs - probe.bufferMs) >= 0 ? '+' : ''}
            {Math.round(probe.captureLagMs - probe.bufferMs)} ms)
          </b>
        </div>
      )}
      {probe.rtpTimestamp !== null && (
        <div>
          <span>rtpTimestamp</span>
          {/* 벽시계가 아니라 클럭레이트 카운터다. 단독으로는 정합에 쓸 수 없고,
              `captureTime` 이 함께 있는지 확인하는 표시로만 둔다. */}
          <b>{probe.rtpTimestamp}</b>
        </div>
      )}
    </div>
  )
}

function formatUtc(epochMs: number): string {
  const at = new Date(epochMs)
  const pad = (value: number, width = 2) => String(value).padStart(width, '0')
  return (
    `${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())}:${pad(at.getUTCSeconds())}` +
    `.${pad(at.getUTCMilliseconds(), 3)}`
  )
}
