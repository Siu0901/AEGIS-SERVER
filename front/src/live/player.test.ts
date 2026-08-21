/**
 * 라이브 재생의 **연결 유지** 성질 (FN-REC-01).
 *
 * 여기서 잠그는 것은 「붙는가」가 아니라 **「끊겼을 때 스스로 다시 붙는가」**다.
 *
 * 초기 구현은 첫 프레임까지만 감시하고 그 뒤로는 연결을 다시 보지 않았다. 피어
 * 연결이 죽어도 `<video>` 는 마지막 프레임을 물고 있어서 화면은 「멈춘 영상」인데
 * 상태 표시는 「WebRTC 정상」이었고, 새로고침 말고는 복구 수단이 없었다.
 * 실측(mediamtx 로그 2026-08-21)으로 카메라가 38초·35초씩 얼어 있었다.
 *
 * **이 결함은 눈으로 못 잡는다.** 재현하려면 몇 분을 기다려야 하고, 기다린 사람만
 * 알게 된다. 그래서 타이머를 순간이동시켜 여기서 잠근다 — 얼어붙은 화면을 정상으로
 * 보이게 두는 것이 이 화면에서 가장 위험한 실패다(절대규칙 9).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// hls.js 는 실제 미디어 스택을 건드리므로 통째로 세운다. 여기서 볼 것은
// 「폴백으로 내려갔는가」와 「치명적 오류에서 복구를 시도했는가」뿐이다.
const hlsInstances: FakeHls[] = []

class FakeHls {
  static isSupported = () => true
  static Events = { ERROR: 'hlsError' } as const
  static ErrorTypes = { NETWORK_ERROR: 'networkError', MEDIA_ERROR: 'mediaError' } as const

  handlers: Record<string, (event: string, data: unknown) => void> = {}
  startLoad = vi.fn()
  recoverMediaError = vi.fn()
  destroy = vi.fn()
  loadSource = vi.fn()
  attachMedia = vi.fn()

  constructor() {
    hlsInstances.push(this)
  }

  on(event: string, handler: (event: string, data: unknown) => void) {
    this.handlers[event] = handler
  }

  /** mediamtx 쪽에서 오는 치명적 오류를 흉내낸다. */
  emitFatal(type: string, details: string) {
    this.handlers.hlsError?.('hlsError', { fatal: true, type, details })
  }
}

vi.mock('hls.js', () => ({ default: FakeHls }))

// ---------------------------------------------------------------------------
// 브라우저 대역
// ---------------------------------------------------------------------------

/** 지금 살아 있는 가짜 피어 연결들. 마지막 것이 화면에 걸린 연결이다. */
const peers: FakePeer[] = []

class FakePeer {
  connectionState = 'new'
  iceConnectionState = 'new'
  iceGatheringState = 'complete'
  localDescription: { sdp: string } | null = { sdp: 'v=0' }
  onconnectionstatechange: (() => void) | null = null
  oniceconnectionstatechange: (() => void) | null = null
  ontrack: ((event: unknown) => void) | null = null
  closed = false

  constructor() {
    peers.push(this)
  }

  addTransceiver() {}
  createOffer() {
    return Promise.resolve({ type: 'offer', sdp: 'v=0' })
  }
  setLocalDescription() {
    return Promise.resolve()
  }
  setRemoteDescription() {
    return Promise.resolve()
  }
  addEventListener() {}
  removeEventListener() {}
  close() {
    this.closed = true
  }

  /** 연결이 제 발로 죽는 상황. mediamtx 로그의 `peer connection closed` 에 해당한다. */
  drop(state: 'failed' | 'closed') {
    this.connectionState = state
    this.onconnectionstatechange?.()
  }

  /** ICE 만 끊겼다 — 돌아올 수도 있으므로 유예가 걸린다. */
  iceDrop(state: 'failed' | 'disconnected') {
    this.iceConnectionState = state
    this.oniceconnectionstatechange?.()
  }
}

type FakeVideo = HTMLVideoElement & {
  fireLoadedData: () => void
  /** 프레임이 흐르는 것을 흉내낸다. 이 값이 안 늘면 정지로 판정되어야 한다. */
  advance: (seconds: number) => void
}

function fakeVideo(): FakeVideo {
  const once: Record<string, Array<() => void>> = {}
  const video = {
    currentTime: 0,
    paused: false,
    videoWidth: 1920,
    videoHeight: 1080,
    srcObject: null as unknown,
    play: () => Promise.resolve(),
    canPlayType: () => '',
    removeAttribute: () => {},
    addEventListener: (type: string, handler: () => void) => {
      ;(once[type] ??= []).push(handler)
    },
    removeEventListener: () => {},
    fireLoadedData: () => {
      const handlers = once.loadeddata ?? []
      once.loadeddata = []
      for (const handler of handlers) handler()
    },
    advance: (seconds: number) => {
      video.currentTime += seconds
    },
  }
  return video as unknown as FakeVideo
}

const URLS = { whep: 'http://x/cam1/main/whep', hls: 'http://x/cam1/main/index.m3u8' }

/** 마지막 원소. `Array.prototype.at` 은 타깃(ES2020)에 없다. */
function last<T>(items: T[]): T {
  const item = items[items.length - 1]
  if (item === undefined) throw new Error('비어 있다')
  return item
}

/** WHEP 이 붙고 첫 프레임까지 도착한 상태로 만든다. */
async function settle(video: FakeVideo) {
  await vi.advanceTimersByTimeAsync(0)
  video.fireLoadedData()
  await vi.advanceTimersByTimeAsync(0)
}

let startPlayback: typeof import('./player').startPlayback

beforeEach(async () => {
  peers.length = 0
  hlsInstances.length = 0
  // `performance` 를 함께 세운다. vitest 기본값에는 빠져 있어서 그대로 두면
  // 정지 감시(`performance.now()` 기준)만 실시간으로 돌아 테스트가 통과해 버린다 —
  // 검증하려던 성질이 조용히 안 검증되는 쪽이 실패보다 나쁘다(절대규칙 9).
  vi.useFakeTimers({
    toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date', 'performance'],
  })

  const pageListeners = new Map<string, Set<() => void>>()
  vi.stubGlobal('window', {
    setTimeout: (fn: () => void, ms?: number) => setTimeout(fn, ms),
    clearTimeout: (id?: unknown) => clearTimeout(id as ReturnType<typeof setTimeout>),
    setInterval: (fn: () => void, ms?: number) => setInterval(fn, ms),
    clearInterval: (id?: unknown) => clearInterval(id as ReturnType<typeof setInterval>),
    addEventListener: (type: string, fn: () => void) => {
      ;(pageListeners.get(type) ?? pageListeners.set(type, new Set()).get(type)!).add(fn)
    },
    removeEventListener: (type: string, fn: () => void) => pageListeners.get(type)?.delete(fn),
  })
  vi.stubGlobal('RTCPeerConnection', FakePeer)
  vi.stubGlobal('MediaStream', class {})
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, text: async () => 'v=0' })))

  // player 는 모듈 최상위에서 hls.js 를 잡으므로 stub 을 세운 뒤에 읽어들인다.
  ;({ startPlayback } = await import('./player'))
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('startPlayback — 연결 유지', () => {
  it('피어 연결이 죽으면 스스로 다시 붙는다', async () => {
    const video = fakeVideo()
    const states: Array<{ kind: string; retrying: boolean }> = []
    const handle = startPlayback(video, URLS, (state) => states.push({ ...state }))

    await settle(video)
    expect(peers).toHaveLength(1)
    expect(last(states)).toEqual({ kind: 'webrtc', error: null, retrying: false })

    // mediamtx 로그의 `closed: peer connection closed` 순간.
    peers[0].drop('failed')

    // 끊긴 사실이 즉시 화면에 드러나야 한다 — 여기가 없어서 멈춘 그림이 「정상」이었다.
    expect(last(states)).toMatchObject({ retrying: true })

    // 백오프가 지나면 새 연결이 생긴다. **새로고침 없이.**
    await vi.advanceTimersByTimeAsync(600)
    expect(peers).toHaveLength(2)
    expect(peers[0].closed).toBe(true)

    await settle(video)
    expect(last(states)).toEqual({ kind: 'webrtc', error: null, retrying: false })

    handle.stop()
  })

  it('연결은 살아 있는데 프레임만 멈춰도 다시 붙는다', async () => {
    const video = fakeVideo()
    const handle = startPlayback(video, URLS, () => {})
    await settle(video)
    expect(peers).toHaveLength(1)

    // 프레임이 흐르는 동안에는 건드리지 않는다.
    for (let tick = 0; tick < 10; tick += 1) {
      video.advance(1)
      await vi.advanceTimersByTimeAsync(1000)
    }
    expect(peers).toHaveLength(1)

    // RTP 만 끊긴 상태 — `connectionState` 는 그대로 `connected` 다. 브라우저는
    // 아무 이벤트도 주지 않으므로 재생 위치로만 알아챌 수 있다.
    await vi.advanceTimersByTimeAsync(6000)
    await vi.advanceTimersByTimeAsync(600)
    expect(peers).toHaveLength(2)

    handle.stop()
  })

  it('ICE 가 잠깐 끊겼다 돌아오면 연결을 부수지 않는다', async () => {
    const video = fakeVideo()
    const handle = startPlayback(video, URLS, () => {})
    await settle(video)

    peers[0].iceDrop('disconnected')
    await vi.advanceTimersByTimeAsync(1000)
    peers[0].iceConnectionState = 'connected'
    peers[0].oniceconnectionstatechange?.()

    await vi.advanceTimersByTimeAsync(5000)
    expect(peers).toHaveLength(1)
    expect(peers[0].closed).toBe(false)

    handle.stop()
  })

  it('WebRTC 재시도가 한계를 넘으면 HLS 로 내려간다', async () => {
    const video = fakeVideo()
    const states: Array<{ kind: string }> = []
    const handle = startPlayback(video, URLS, (state) => states.push({ ...state }))
    await settle(video)

    // 붙을 때마다 곧바로 죽는 망. 매번 첫 프레임까지 받고 다시 끊긴다.
    for (let attempt = 0; attempt < 4; attempt += 1) {
      last(peers).drop('failed')
      await vi.advanceTimersByTimeAsync(10_000)
      await vi.advanceTimersByTimeAsync(0)
    }

    expect(hlsInstances).toHaveLength(1)
    expect(last(states)).toMatchObject({ kind: 'hls' })

    handle.stop()
  })

  it('HLS 치명적 오류에서 복구를 시도한다 — hls.js 는 스스로 하지 않는다', async () => {
    const video = fakeVideo()
    const handle = startPlayback(video, URLS, () => {}, 'hls')
    await vi.advanceTimersByTimeAsync(0)
    expect(hlsInstances).toHaveLength(1)

    hlsInstances[0].emitFatal(FakeHls.ErrorTypes.NETWORK_ERROR, 'levelLoadError')
    expect(hlsInstances[0].startLoad).toHaveBeenCalled()

    hlsInstances[0].emitFatal(FakeHls.ErrorTypes.MEDIA_ERROR, 'bufferStalledError')
    expect(hlsInstances[0].recoverMediaError).toHaveBeenCalled()

    handle.stop()
  })

  it('stop() 뒤에는 재연결이 돌지 않는다', async () => {
    const video = fakeVideo()
    const handle = startPlayback(video, URLS, () => {})
    await settle(video)

    handle.stop()
    expect(peers[0].closed).toBe(true)

    // 정리 과정에서 우리가 부른 close() 가 재연결을 발동하면 타일을 다시 그릴
    // 때마다 연결이 쌓인다 — 원래의 유령 세션 누수와 같은 경로다.
    await vi.advanceTimersByTimeAsync(30_000)
    expect(peers).toHaveLength(1)
  })
})
