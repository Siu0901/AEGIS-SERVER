/**
 * 라이브 재생 — WebRTC(WHEP) 우선, 실패하면 HLS 폴백 (FN-REC-01).
 *
 * 두 경로를 다 두는 이유는 **지연이 크게 다르기 때문**이다. 오버레이 시간 정합
 * 목표가 ±100ms(FN-UI-02)라 WebRTC 가 기본이고, WebRTC 가 막히는 망에서도 화면은
 * 보여야 하므로 HLS 로 내려간다. 지금 어느 경로로 재생 중인지를 화면에 표시하는 것은
 * 장식이 아니다 — 두 경로의 지연이 다르므로 M2 에서 오버레이가 어긋날 때 원인을
 * 가르는 첫 단서가 된다.
 */

import Hls from 'hls.js'

export type PlaybackKind = 'webrtc' | 'hls' | 'none'

export type PlayerState = {
  kind: PlaybackKind
  error: string | null
}

/**
 * WebRTC 가 붙었는데 프레임이 오지 않는 상태를 성공으로 보지 않기 위한 감시 시간.
 *
 * WHEP 는 SDP 교환이 끝나면 200 을 돌려주므로, ICE 가 막혀 미디어가 한 장도 오지
 * 않아도 "연결됨"으로 보인다. 그러면 검은 화면을 띄운 채 폴백하지 않는다.
 */
const FIRST_FRAME_TIMEOUT_MS = 4000

export type PlayerHandle = {
  stop: () => void
}

/** 어느 경로로 재생할지. `auto` 가 기본이고 나머지는 진단용 강제 지정이다. */
export type PlaybackPreference = 'auto' | 'webrtc' | 'hls'

/**
 * `?playback=hls` 처럼 URL 로 경로를 강제한다.
 *
 * 폴백은 **평소에 안 도는 경로**라 조용히 썩기 쉽다. 두 경로의 지연 차이를 재거나
 * 폴백이 아직 살아 있는지 확인할 때 이 스위치가 없으면 WebRTC 를 인위적으로
 * 망가뜨리는 수밖에 없다.
 */
export function preferenceFromLocation(search: string): PlaybackPreference {
  const value = new URLSearchParams(search).get('playback')
  return value === 'hls' || value === 'webrtc' ? value : 'auto'
}

/**
 * `video` 에 라이브를 붙인다. 경로가 바뀔 때마다 `onState` 로 알린다.
 *
 * 반환한 `stop()` 을 반드시 불러야 한다 — RTCPeerConnection 과 hls.js 는 둘 다
 * 스스로 정리되지 않아서, 카메라 타일을 다시 그릴 때마다 연결이 쌓인다.
 */
export function startPlayback(
  video: HTMLVideoElement,
  urls: { whep: string; hls: string },
  onState: (state: PlayerState) => void,
  preference: PlaybackPreference = 'auto',
): PlayerHandle {
  let stopped = false
  let pc: RTCPeerConnection | null = null
  let hls: Hls | null = null
  let watchdog: number | undefined

  const cleanupWebrtc = () => {
    window.clearTimeout(watchdog)
    pc?.close()
    pc = null
  }

  const cleanupHls = () => {
    hls?.destroy()
    hls = null
  }

  const fallbackToHls = (reason: string) => {
    if (stopped) return
    cleanupWebrtc()
    if (preference === 'webrtc') {
      // 강제 지정이면 몰래 다른 경로로 내려가지 않는다. 진단이 목적인데 경로가
      // 바뀌어 버리면 무엇을 재고 있는지 알 수 없게 된다.
      onState({ kind: 'none', error: `WebRTC 실패(강제 지정): ${reason}` })
      return
    }
    console.warn('[live] WebRTC 실패 → HLS 폴백:', reason)
    startHls(reason)
  }

  const startHls = (webrtcReason: string) => {
    if (stopped) return
    if (Hls.isSupported()) {
      hls = new Hls({
        lowLatencyMode: true,
        backBufferLength: 10,
        // **라이브 엣지에 붙여둔다.** 기본값으로 두면 재생 위치가 뒤로 밀린 채
        // 그대로 흘러간다 — 실측 중 한 채널이 20초 넘게 뒤처진 상태로 계속 재생됐다.
        // 그만큼 밀리면 오버레이를 `ts` 로 맞춰 그려도 영상과 어긋난다(FN-UI-02).
        liveSyncDurationCount: 3,
        // 뒤처지면 조금 빠르게 재생해 따라잡는다. 끊고 다시 붙는 것보다 덜 튄다.
        maxLiveSyncPlaybackRate: 1.5,
      })
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (!data.fatal) return
        onState({ kind: 'none', error: `HLS 실패: ${data.details} (WebRTC: ${webrtcReason})` })
      })
      hls.loadSource(urls.hls)
      hls.attachMedia(video)
      void video.play().catch(() => undefined)
      onState({ kind: 'hls', error: null })
      return
    }
    // Safari 는 hls.js 없이 재생한다.
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = urls.hls
      void video.play().catch(() => undefined)
      onState({ kind: 'hls', error: null })
      return
    }
    onState({ kind: 'none', error: `재생 경로 없음 (WebRTC: ${webrtcReason})` })
  }

  const startWebrtc = async () => {
    try {
      pc = new RTCPeerConnection({ iceServers: [] })
      pc.addTransceiver('video', { direction: 'recvonly' })

      pc.ontrack = (event) => {
        if (stopped) return
        video.srcObject = event.streams[0] ?? new MediaStream([event.track])
        void video.play().catch(() => undefined)
      }

      const offer = await pc.createOffer()
      await pc.setLocalDescription(offer)
      await waitForIceGathering(pc)

      const response = await fetch(urls.whep, {
        method: 'POST',
        headers: { 'Content-Type': 'application/sdp' },
        body: pc.localDescription?.sdp ?? '',
      })
      if (!response.ok) {
        fallbackToHls(`WHEP ${response.status}`)
        return
      }
      const answer = await response.text()
      if (stopped) return
      await pc.setRemoteDescription({ type: 'answer', sdp: answer })

      // 프레임이 실제로 도착해야 성공이다.
      watchdog = window.setTimeout(() => {
        if (video.videoWidth === 0) fallbackToHls('프레임 미도착')
      }, FIRST_FRAME_TIMEOUT_MS)

      video.addEventListener(
        'loadeddata',
        () => {
          window.clearTimeout(watchdog)
          if (!stopped) onState({ kind: 'webrtc', error: null })
        },
        { once: true },
      )
    } catch (error) {
      fallbackToHls(error instanceof Error ? error.message : String(error))
    }
  }

  if (preference === 'hls') {
    startHls('강제 지정(?playback=hls)')
  } else {
    void startWebrtc()
  }

  return {
    stop: () => {
      stopped = true
      cleanupWebrtc()
      cleanupHls()
      video.srcObject = null
      video.removeAttribute('src')
    },
  }
}

/** ICE 수집이 끝날 때까지 기다린다(비-트리클 WHEP). 오래 끌지 않도록 상한을 둔다. */
function waitForIceGathering(pc: RTCPeerConnection, timeoutMs = 1500): Promise<void> {
  if (pc.iceGatheringState === 'complete') return Promise.resolve()
  return new Promise((resolve) => {
    const done = () => {
      pc.removeEventListener('icegatheringstatechange', check)
      window.clearTimeout(timer)
      resolve()
    }
    const check = () => {
      if (pc.iceGatheringState === 'complete') done()
    }
    const timer = window.setTimeout(done, timeoutMs)
    pc.addEventListener('icegatheringstatechange', check)
  })
}
