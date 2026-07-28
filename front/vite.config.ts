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
      __MEDIAMTX_WHEP__: JSON.stringify(env.MEDIAMTX_WHEP || 'http://localhost:8889'),
      __MEDIAMTX_HLS__: JSON.stringify(env.MEDIAMTX_HLS || 'http://localhost:8888'),
    },
    server: {
      // 명시하지 않으면 Windows 에서 `localhost` 가 ::1 로만 바인딩되는데, Chrome 은
      // `localhost` 를 127.0.0.1 로 먼저 풀어서 연결이 거부된다. 나머지 서비스도
      // 전부 127.0.0.1 을 쓰므로 여기서 맞춰 둔다.
      host: '127.0.0.1',
      port: 5173,
      // 서버(:8000)를 같은 오리진으로 프록시한다. WebSocket 도 함께 넘긴다.
      proxy: {
        '/api': { target: 'http://localhost:8000', changeOrigin: true },
        '/ws': { target: 'ws://localhost:8000', ws: true },
      },
    },
  }
})
