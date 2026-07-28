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
import type { CameraStatus, StreamState } from '../types/system'
import { preferenceFromLocation, startPlayback, type PlaybackKind } from './player'

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
  recording: boolean
}

export default function CameraTile({ camera, name, recording }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [kind, setKind] = useState<PlaybackKind>('none')
  const [error, setError] = useState<string | null>(null)
  const [displayAt, setDisplayAt] = useState<string>('—')
  const [size, setSize] = useState<string>('—')

  const path = `cam${camera.cam_id}/main`
  const live = camera.main_state === 'ok'

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    // 스트림이 죽어 있으면 붙지 않는다. 죽은 경로를 계속 두드리면 브라우저 콘솔이
    // 오류로 가득 차서 진짜 문제가 묻힌다. 살아나면 이 effect 가 다시 돈다.
    if (!live) {
      setKind('none')
      setDisplayAt('—')
      return
    }

    const handle = startPlayback(
      video,
      { whep: `${WHEP_BASE}/${path}/whep`, hls: `${HLS_BASE}/${path}/index.m3u8` },
      (state) => {
        setKind(state.kind)
        setError(state.error)
      },
      preferenceFromLocation(window.location.search),
    )
    return () => handle.stop()
  }, [live, path])

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
      setSize(`${video.videoWidth}×${video.videoHeight}`)
      handle = video.requestVideoFrameCallback(onFrame)
    }

    handle = video.requestVideoFrameCallback(onFrame)
    return () => {
      cancelled = true
      video.cancelVideoFrameCallback(handle)
    }
  }, [kind])

  return (
    <figure className={`tile tile--${STATE_TONE[camera.main_state]}`}>
      <div className="tile__frame">
        <video ref={videoRef} muted playsInline autoPlay className="tile__video" />

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
        <span className="tile__meta">{live ? KIND_LABEL[kind] : STATE_LABEL[camera.main_state]}</span>
        <span className="tile__spacer" />
        {/* REC 표시는 REC 컴포넌트(§4.7)의 `cameras[].recording` 이다.
            라이브가 보인다고 녹화 중인 것이 아니다 — 둘은 다른 프로세스다. */}
        <span className={recording ? 'tile__rec tile__rec--on' : 'tile__rec'}>REC</span>
      </figcaption>

      {error && <p className="tile__error">{error}</p>}
    </figure>
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
