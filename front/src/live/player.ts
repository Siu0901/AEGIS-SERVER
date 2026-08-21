/**
 * 라이브 재생 — WebRTC(WHEP) 우선, 실패하면 HLS 폴백 (FN-REC-01).
 *
 * 두 경로를 다 두는 이유는 **지연이 크게 다르기 때문**이다. 오버레이 시간 정합
 * 목표가 ±100ms(FN-UI-02)라 WebRTC 가 기본이고, WebRTC 가 막히는 망에서도 화면은
 * 보여야 하므로 HLS 로 내려간다. 지금 어느 경로로 재생 중인지를 화면에 표시하는 것은
 * 장식이 아니다 — 두 경로의 지연이 다르므로 M2 에서 오버레이가 어긋날 때 원인을
 * 가르는 첫 단서가 된다.
 *
 * ★ **붙는 것보다 붙어 있는 것이 어렵다.** 초기 구현은 첫 프레임까지만 감시하고
 *   그 뒤로는 연결을 다시 보지 않았다. 그래서 피어 연결이 죽어도 `<video>` 는
 *   마지막 프레임을 그대로 물고 있었고, 화면은 「멈춘 영상」인데 상태 표시는
 *   「WebRTC 정상」이었다. 새로고침 말고는 복구 수단이 없었다.
 *
 *   실측(mediamtx 로그, 2026-08-21): TCP-ICE 세션이 1~5분마다
 *   `closed: peer connection closed` 로 죽었고, 끊긴 뒤 38초·35초 동안 아무도
 *   다시 붙지 않았다. 사람이 새로고침할 때까지 카메라가 얼어 있었다는 뜻이다.
 *
 *   **얼어붙은 화면을 정상으로 보이게 두는 것이 이 화면에서 가장 위험하다** —
 *   관제자는 「위반이 없다」로 읽는다. 그래서 아래 두 가지를 함께 둔다.
 *     1. 연결 상태와 프레임 진행을 계속 감시해 끊기면 스스로 다시 붙는다.
 *     2. 다시 붙는 동안에는 그 사실을 `retrying` 으로 올려 화면에 드러낸다.
 */

import Hls from 'hls.js'

export type PlaybackKind = 'webrtc' | 'hls' | 'none'

/**
 * 재생 경로별 오버레이 지연 버퍼 정책 키 (API명세서 §4.5 · FN-UI-02).
 *
 * 영상 지연이 경로에 따라 한 자릿수 배 차이가 나므로(M1 실측: WebRTC 0.27~0.34초 ·
 * LL-HLS 약 2.5초) 버퍼 값도 경로마다 다르다. **값은 여기 적지 않는다** — 정책값은
 * DB `policies` 테이블이 원본이고 `GET /policies` 로 읽는다(CLAUDE.md 절대규칙 6).
 * 여기 있는 것은 "지금 이 경로에는 어느 키가 적용되는가"라는 대응표뿐이다.
 * 오버레이 렌더링은 M2 에서 이 대응을 따라 버퍼를 고른다.
 */
export const OVERLAY_BUFFER_POLICY_KEY = {
  webrtc: 'overlay_buffer_webrtc_ms',
  hls: 'overlay_buffer_hls_ms',
  none: null,
} as const satisfies Record<PlaybackKind, string | null>

export type PlayerState = {
  kind: PlaybackKind
  error: string | null
  /**
   * 끊겨서 다시 붙는 중인가.
   *
   * `kind` 만으로는 부족하다 — 재연결 중에도 `<video>` 에는 직전 프레임이 남아
   * 있어서, 이 값을 화면에 드러내지 않으면 멈춘 그림이 살아 있는 영상으로 보인다.
   */
  retrying: boolean
}

/**
 * WebRTC 가 붙었는데 프레임이 오지 않는 상태를 성공으로 보지 않기 위한 감시 시간.
 *
 * WHEP 는 SDP 교환이 끝나면 200 을 돌려주므로, ICE 가 막혀 미디어가 한 장도 오지
 * 않아도 "연결됨"으로 보인다. 그러면 검은 화면을 띄운 채 폴백하지 않는다.
 */
const FIRST_FRAME_TIMEOUT_MS = 4000

/**
 * 붙은 뒤 재생 위치가 이만큼 안 늘면 끊긴 것으로 본다.
 *
 * 15fps 스트림이라 정상이면 `currentTime` 이 매 66ms 늘어난다. 6초는 그 90배라
 * 일시적 지터로는 절대 닿지 않는 값이고, 반대로 사람이 「멈췄네」하고 알아채기
 * 전에 복구를 시작할 만큼은 짧다.
 */
const STALL_TIMEOUT_MS = 6000

/** 정지 감시 주기. */
const STALL_POLL_MS = 1000

/**
 * ICE 가 `disconnected` 로 떨어졌을 때 스스로 돌아오기를 기다리는 시간.
 *
 * `disconnected` 는 일시적일 수 있어서 즉시 부수면 멀쩡한 연결을 끊게 된다.
 * 다만 Docker Desktop 의 TCP-ICE 경로에서는 거의 돌아오지 않으므로 짧게 잡는다.
 */
const ICE_DISCONNECT_GRACE_MS = 3000

/** 재연결 백오프(ms). 마지막 값이 상한이다. */
const RETRY_BACKOFF_MS = [500, 1000, 2000, 4000, 8000] as const

/**
 * WebRTC 재시도를 이만큼 연속 실패하면 HLS 로 내려간다.
 *
 * 계속 WebRTC 만 두드리면 망이 WebRTC 를 막는 환경에서 영영 화면이 안 나온다.
 * 반대로 한 번 실패에 바로 내려가면 순간 끊김마다 2.5초 지연 경로로 떨어진다.
 */
const WEBRTC_RETRY_LIMIT = 3

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
 * `video` 에 라이브를 붙이고 **붙어 있는 상태를 유지한다.** 경로나 재연결 상태가
 * 바뀔 때마다 `onState` 로 알린다.
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
  let firstFrame: number | undefined
  let iceGrace: number | undefined
  let retryTimer: number | undefined
  let stallTimer: number | undefined

  /** 지금 화면에 걸려 있는 경로. 재시도 판단에 쓴다. */
  let kind: PlaybackKind = 'none'
  /** 연속 실패 횟수. 성공(첫 프레임 도착)하면 0 으로 되돌린다. */
  let failures = 0
  /** 재연결 절차가 이미 돌고 있는가. 상태변화·정지감시가 동시에 물면 두 번 붙는다. */
  let recovering = false

  /** 마지막으로 재생 위치가 늘어난 시각과 그때의 위치. */
  let lastProgressAt = 0
  let lastMediaTime = -1

  const report = (next: PlayerState) => {
    if (stopped) return
    kind = next.kind
    onState(next)
  }

  const clearTimers = () => {
    window.clearTimeout(firstFrame)
    window.clearTimeout(iceGrace)
    window.clearTimeout(retryTimer)
    window.clearInterval(stallTimer)
    firstFrame = iceGrace = retryTimer = stallTimer = undefined
  }

  const cleanupWebrtc = () => {
    window.clearTimeout(firstFrame)
    window.clearTimeout(iceGrace)
    firstFrame = iceGrace = undefined
    if (pc) {
      // 핸들러를 먼저 떼지 않으면 우리가 부른 `close()` 가 다시 재연결을 발동한다.
      pc.onconnectionstatechange = null
      pc.oniceconnectionstatechange = null
      pc.ontrack = null
      pc.close()
    }
    pc = null
  }

  const cleanupHls = () => {
    hls?.destroy()
    hls = null
  }

  /**
   * 끊겼다 — 백오프를 두고 처음부터 다시 붙는다.
   *
   * **어느 경로로 다시 붙는지가 요점이다.** WebRTC 를 연속으로 실패하면 그 망에서는
   * WebRTC 가 안 되는 것이므로 HLS 로 내려가고, 그 전까지는 지연이 짧은 WebRTC 를
   * 계속 노린다.
   */
  const recover = (reason: string) => {
    if (stopped || recovering) return
    recovering = true
    clearTimers()
    cleanupWebrtc()
    cleanupHls()

    failures += 1
    const delay = RETRY_BACKOFF_MS[Math.min(failures - 1, RETRY_BACKOFF_MS.length - 1)]
    console.warn(`[live] 끊김 → ${delay}ms 뒤 재연결 (${failures}회): ${reason}`)
    // 경로는 유지한 채 재연결 중임을 알린다. 여기서 `none` 으로 내리면 오버레이가
    // 통째로 사라졌다가 돌아와 화면이 요란해진다.
    report({ kind, error: null, retrying: true })

    retryTimer = window.setTimeout(() => {
      recovering = false
      if (stopped) return
      if (preference === 'hls') {
        startHls('강제 지정(?playback=hls)')
        return
      }
      if (preference === 'auto' && failures > WEBRTC_RETRY_LIMIT) {
        startHls(`WebRTC ${failures}회 연속 실패: ${reason}`)
        return
      }
      void startWebrtc()
    }, delay)
  }

  /**
   * 재생이 실제로 진행되는지 계속 본다.
   *
   * 연결 상태만 보면 부족하다 — 피어 연결이 `connected` 인 채로 RTP 만 끊기는 경우가
   * 있고(Docker Desktop 의 TCP-ICE 에서 실제로 나왔다), 그때 브라우저는 아무 이벤트도
   * 주지 않는다. 화면이 얼어붙는데 코드에는 아무 일도 안 일어난다.
   */
  const watchProgress = () => {
    window.clearInterval(stallTimer)
    lastProgressAt = performance.now()
    lastMediaTime = -1
    stallTimer = window.setInterval(() => {
      if (stopped || recovering) return
      const now = performance.now()
      if (video.currentTime !== lastMediaTime) {
        lastMediaTime = video.currentTime
        lastProgressAt = now
        return
      }
      // 자동재생이 막혀 멈춘 것은 끊김이 아니다. 다시 틀어보고 판단은 미룬다.
      if (video.paused) {
        void video.play().catch(() => undefined)
        lastProgressAt = now
        return
      }
      if (now - lastProgressAt >= STALL_TIMEOUT_MS) {
        recover(`${Math.round((now - lastProgressAt) / 1000)}초간 프레임 정지`)
      }
    }, STALL_POLL_MS)
  }

  /** 첫 프레임이 왔다 = 이번 연결은 성공이다. */
  const onLive = (next: PlaybackKind) => {
    failures = 0
    report({ kind: next, error: null, retrying: false })
    watchProgress()
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
        // ★ **hls.js 는 치명적 오류에서 스스로 복구하지 않는다.** 여기서 아무것도
        //   안 하면 재생이 그 자리에서 영영 멈춘다. 종류별로 손을 넣어야 한다.
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
          console.warn('[live] HLS 네트워크 오류 → 재적재:', data.details)
          report({ kind: 'hls', error: null, retrying: true })
          hls?.startLoad()
          return
        }
        if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
          console.warn('[live] HLS 미디어 오류 → 복구:', data.details)
          report({ kind: 'hls', error: null, retrying: true })
          hls?.recoverMediaError()
          return
        }
        // 그 밖에는 hls.js 가 손쓸 수 없는 오류다. 통째로 다시 붙는다.
        recover(`HLS 실패: ${data.details} (WebRTC: ${webrtcReason})`)
      })
      hls.loadSource(urls.hls)
      hls.attachMedia(video)
      void video.play().catch(() => undefined)
      onLive('hls')
      return
    }
    // Safari 는 hls.js 없이 재생한다.
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = urls.hls
      void video.play().catch(() => undefined)
      onLive('hls')
      return
    }
    report({ kind: 'none', error: `재생 경로 없음 (WebRTC: ${webrtcReason})`, retrying: false })
  }

  const fallbackToHls = (reason: string) => {
    if (stopped) return
    cleanupWebrtc()
    if (preference === 'webrtc') {
      // 강제 지정이면 몰래 다른 경로로 내려가지 않는다. 진단이 목적인데 경로가
      // 바뀌어 버리면 무엇을 재고 있는지 알 수 없게 된다. 다만 재연결은 계속한다 —
      // 진단 중에 한 번 끊겼다고 화면이 영영 죽어 있으면 그것도 진단이 안 된다.
      report({ kind: 'none', error: `WebRTC 실패(강제 지정): ${reason}`, retrying: true })
      recover(reason)
      return
    }
    console.warn('[live] WebRTC 실패 → HLS 폴백:', reason)
    startHls(reason)
  }

  const startWebrtc = async () => {
    try {
      pc = new RTCPeerConnection({ iceServers: [] })
      const self = pc
      pc.addTransceiver('video', { direction: 'recvonly' })

      pc.ontrack = (event) => {
        if (stopped) return
        video.srcObject = event.streams[0] ?? new MediaStream([event.track])
        void video.play().catch(() => undefined)
      }

      // ★ **붙은 뒤에도 연결을 계속 본다.** 이것이 없어서 카메라가 얼어붙었다.
      pc.onconnectionstatechange = () => {
        if (stopped || pc !== self) return
        if (self.connectionState === 'failed' || self.connectionState === 'closed') {
          recover(`peer connection ${self.connectionState}`)
        }
      }
      pc.oniceconnectionstatechange = () => {
        if (stopped || pc !== self) return
        const state = self.iceConnectionState
        if (state === 'failed') {
          recover('ICE 실패')
          return
        }
        if (state === 'disconnected') {
          // 스스로 돌아올 수 있으므로 잠깐 기다린다. 안 돌아오면 다시 붙는다.
          window.clearTimeout(iceGrace)
          report({ kind, error: null, retrying: true })
          iceGrace = window.setTimeout(() => {
            if (stopped || pc !== self) return
            if (self.iceConnectionState === 'disconnected') recover('ICE 단절 지속')
          }, ICE_DISCONNECT_GRACE_MS)
          return
        }
        if (state === 'connected' || state === 'completed') {
          window.clearTimeout(iceGrace)
          iceGrace = undefined
        }
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
      if (stopped || pc !== self) return
      await pc.setRemoteDescription({ type: 'answer', sdp: answer })

      // 프레임이 실제로 도착해야 성공이다.
      firstFrame = window.setTimeout(() => {
        if (video.videoWidth === 0) fallbackToHls('프레임 미도착')
      }, FIRST_FRAME_TIMEOUT_MS)

      video.addEventListener(
        'loadeddata',
        () => {
          window.clearTimeout(firstFrame)
          firstFrame = undefined
          if (!stopped && pc === self) onLive('webrtc')
        },
        { once: true },
      )
    } catch (error) {
      fallbackToHls(error instanceof Error ? error.message : String(error))
    }
  }

  const teardown = () => {
    stopped = true
    clearTimers()
    cleanupWebrtc()
    cleanupHls()
    video.srcObject = null
    video.removeAttribute('src')
  }

  /**
   * ★ **탭을 닫거나 새로고침할 때 연결을 끊는다.**
   *
   * React 의 정리 함수는 페이지가 사라질 때 보장되지 않는다. 그래서 새로고침할
   * 때마다 mediamtx 쪽 세션이 살아남았다 — 실측으로 유령 리더 6개가 19분간 남아
   * 1080p 를 계속 받아갔고, 그 대역이 남은 연결을 더 잘 끊기게 만들었다.
   * `pagehide` 는 `beforeunload` 와 달리 모바일·bfcache 에서도 불린다.
   */
  const onPageHide = () => teardown()
  window.addEventListener('pagehide', onPageHide)

  if (preference === 'hls') {
    startHls('강제 지정(?playback=hls)')
  } else {
    void startWebrtc()
  }

  return {
    stop: () => {
      window.removeEventListener('pagehide', onPageHide)
      teardown()
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
