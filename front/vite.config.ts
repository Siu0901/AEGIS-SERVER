import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * 프론트도 **레포 루트의 `.env` 하나**를 읽는다 (견본 `.env.example`).
 * docker-compose · 서버 · REC 이 같은 파일을 보므로 주소를 두 곳에 적어 어긋나는 일이 없다.
 *
 * `envDir: '..'` 과 `loadEnv(mode, '..', '')` 를 함께 쓰는 이유: vite 는 기본적으로
 * `VITE_` 접두사가 붙은 키만 클라이언트에 노출하는데, 우리 키에는 접두사가 없다
 * (API명세서 §4.7 이 `RECORDER_BASE` 같은 이름을 그대로 지정한다). 세 번째 인자를
 * 빈 문자열로 주면 전부 읽어오고, 그중 **필요한 것만 골라** `define` 으로 내려보낸다.
 * 통째로 노출하면 DB 자격증명까지 번들에 들어간다.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', '')

  return {
    plugins: [react()],
    envDir: '..',
    define: {
      __MEDIAMTX_WHEP__: JSON.stringify(env.MEDIAMTX_WHEP || 'http://127.0.0.1:8889'),
      __MEDIAMTX_HLS__: JSON.stringify(env.MEDIAMTX_HLS || 'http://127.0.0.1:8888'),
    },
    server: {
      // 명시하지 않으면 Windows 에서 `localhost` 가 ::1 로만 바인딩되는데, Chrome 은
      // `localhost` 를 127.0.0.1 로 먼저 풀어서 연결이 거부된다. 나머지 서비스도
      // 전부 127.0.0.1 을 쓰므로 여기서 맞춰 둔다.
      host: '127.0.0.1',
      port: 5173,
      // 서버(:8000)를 같은 오리진으로 프록시한다. WebSocket 도 함께 넘긴다.
      // **타깃도 `localhost` 을 쓰지 않는다.** 프록시가 ::1 로 먼저 붙으려다
      // 타임아웃(실측 2.6초)을 먹고 IPv4 로 폴백하는데, `/ws/dashboard` 에서는
      // 그 2.6초가 오버레이 좌표 도착 지연으로 그대로 나타난다.
      proxy: {
        '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
        '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
        // 키프레임·클립. **없으면 조용히 깨진다** — vite 의 SPA 폴백이 `/media/...`
        // 요청에 `index.html` 을 돌려주므로 `<img>` 는 깨진 그림, `<video>` 는 재생
        // 불가가 된다. 404 가 아니라 200(text/html)이라 콘솔에도 오류가 안 남는다.
        // 서버에서는 정상이라 「검색 결과에 그림만 안 나오는」 증상으로만 보인다.
        '/media': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      },
    },
    /**
     * 프론트 단위 테스트 (`npm run test` · `uv run tasks.py verify` 가 부른다).
     *
     * 검증 대상은 **순수 로직**이다 — 오버레이 지연 버퍼의 보간·부호·낡음 판정과
     * 지표 표시 규약(`formatRate` 의 `null` → `–`). M2 에서는 스크래치에서 `tsc` 로
     * 컴파일해 node 로 돌려 확인했고, 그것은 다음 사람이 반복할 수 없는 검증이었다.
     *
     * `environment` 를 `node` 로 둔다. DOM 이 필요한 렌더 테스트는 없다 —
     * 컴포넌트는 브라우저에서 눈으로 보는 것이 더 정확하고, 여기서 잠글 것은
     * **눈으로 확인할 수 없는 계산**이다.
     */
    test: {
      environment: 'node',
      include: ['src/**/*.test.ts'],
      // 통과했는지 아닌지가 종료코드로만 드러나면 안 된다(절대규칙 9).
      reporters: ['default'],
    },
  }
})
