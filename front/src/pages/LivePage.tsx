/**
 * 실시간 관제 (FN-UI-02).
 *
 * M1 범위는 **2채널 라이브와 그 상태**까지다. 오버레이·진행 중 이벤트·수동 방송은
 * 각각 M2·M3·M5 에서 이 화면에 붙는다. 지금 없는 기능을 자리표시자로 그려두지 않는다 —
 * 빈 패널은 "아직 없음"과 "고장남"을 구분하지 못하게 만든다.
 *
 * 레이아웃은 `docs/AEGIS_front_design.pdf` 2페이지를 따르되, 용어는 기능명세서
 * 부록 B 대조표대로 제조현장 기준으로 쓴다.
 */

import { useSystemStatus } from '../api/useSystemStatus'
import CameraTile from '../live/CameraTile'
import '../live/live.css'

/** 카메라 표시 이름. 실제 설치 위치명은 M6 설정 화면에서 관리한다(FN-CFG). */
const CAMERA_NAMES: Record<number, string> = {
  1: '카메라 1 · 작업장 A',
  2: '카메라 2 · 지게차 통행로',
}

export default function LivePage() {
  const { status, connected, error } = useSystemStatus()

  if (error && !status) {
    return (
      <section className="card">
        <h2 className="card__title">실시간 관제</h2>
        <p className="card__note">
          서버 상태를 읽지 못했다 — {error}
          <br />
          <code>uv run uvicorn server.app.main:app --reload</code> 가 떠 있는지 확인해라.
        </p>
      </section>
    )
  }

  if (!status) {
    return (
      <section className="card">
        <h2 className="card__title">실시간 관제</h2>
        <p className="card__note">시스템 상태를 불러오는 중…</p>
      </section>
    )
  }

  // §4.6 에는 카메라별 녹화 여부가 없다. REC(§4.7)에 닿았는지(`storage` 가 채워졌는지)와
  // 메인 스트림 상태로 판단한다. REC 이 죽으면 storage 가 null 로 오므로 REC 표시가 꺼진다.
  const recorderUp = status.storage.retention_days !== null

  return (
    <div className="live">
      <div className="live__grid">
        {status.cameras.map((camera) => (
          <CameraTile
            key={camera.cam_id}
            camera={camera}
            name={CAMERA_NAMES[camera.cam_id] ?? `카메라 ${camera.cam_id}`}
            recording={recorderUp && camera.main_state === 'ok'}
          />
        ))}
      </div>

      <aside className="live__side">
        <section className="card">
          <h2 className="card__title">스트림 상태</h2>
          <table className="live__table">
            <thead>
              <tr>
                <th>카메라</th>
                <th>메인</th>
                <th>서브</th>
                <th>fps</th>
              </tr>
            </thead>
            <tbody>
              {status.cameras.map((camera) => (
                <tr key={camera.cam_id}>
                  <td>카메라 {camera.cam_id}</td>
                  <td className={`live__state live__state--${camera.main_state}`}>
                    {camera.main_state}
                  </td>
                  <td className={`live__state live__state--${camera.sub_state}`}>
                    {camera.sub_state}
                  </td>
                  {/* 엣지가 붙기 전에는 null 이다. 0 으로 그리면 장애처럼 보인다. */}
                  <td>{camera.fps === null ? '—' : camera.fps.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="card__note">
            메인은 서버가, 서브는 엣지가 관측한다. 메인이 끊겨도 추론은 계속되고 서브가
            끊겨도 녹화는 계속되므로 따로 표시한다.
          </p>
        </section>

        <section className="card">
          <h2 className="card__title">녹화 · 저장소</h2>
          <dl className="live__facts">
            <dt>REC</dt>
            <dd className={recorderUp ? 'ok' : 'danger'}>{recorderUp ? '녹화 중' : '응답 없음'}</dd>
            <dt>보존</dt>
            <dd>
              {status.storage.retention_days === null ? '—' : `${status.storage.retention_days}일`}
            </dd>
            <dt>여유</dt>
            <dd>{status.storage.free_gb === null ? '—' : `${status.storage.free_gb} GB`}</dd>
          </dl>
          <p className="card__note">
            녹화 원본은 엣지 SSD 에 있다. 여기 숫자는 REC 이 보고한 값이며 서버 노트북의
            디스크가 아니다.
          </p>
        </section>

        <section className="card">
          <h2 className="card__title">실시간 갱신</h2>
          <p className="card__note">
            <span className={`dot dot--${connected ? 'ok' : 'danger'}`} />{' '}
            {connected
              ? '/ws/dashboard 연결됨 — 상태 변화가 즉시 반영된다'
              : '/ws/dashboard 끊김 — 아래 값이 낡았을 수 있다'}
          </p>
        </section>
      </aside>
    </div>
  )
}
