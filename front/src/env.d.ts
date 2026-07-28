/// <reference types="vite/client" />

/**
 * `vite.config.ts` 의 `define` 으로 주입되는 값. 원본은 레포 루트 `.env` 다.
 *
 * mediamtx 주소만 노출한다. 루트 `.env` 에는 DB 자격증명도 있으므로 통째로
 * 내려보내지 않는다.
 */
declare const __MEDIAMTX_WHEP__: string
declare const __MEDIAMTX_HLS__: string
