/**
 * 시연용 녹화 영상 타일 (FN-UI-02 「전체 분할 보기」).
 *
 * **감지 파이프라인과 무관하다.** 여기 뜨는 박스는 영상에 이미 구워져 있는 것이고,
 * 엣지·서버·오버레이 어느 것도 이 타일을 거치지 않는다. 카메라를 여러 대 붙였을 때
 * 관제 화면이 어떻게 보이는지를 시연에서 보여주기 위한 자리다.
 *
 * ★ **「시연 영상」 표시를 뗄 수 없게 붙여 둔다.** 실시간 타일과 생김새가 같아서
 *   표시가 없으면 녹화를 실시간 감지로 오해하게 된다. 이 프로젝트의 지표(방송 후
 *   시정률)가 신뢰를 얻으려면 무엇이 실측이고 무엇이 아닌지가 화면에서 갈려야 한다.
 */

type Props = {
  /** `media/` 안의 파일 이름. 서버가 `/media` 로 서빙하고 vite 가 프록시한다. */
  file: string
  /** 타일에 띄울 이름. */
  name: string
}

export default function DemoTile({ file, name }: Props) {
  return (
    <figure className="tile tile--demo">
      <div className="tile__frame">
        {/*
          `muted` 가 없으면 브라우저가 자동재생을 막는다. 소리는 이 시스템이 쓰지 않는다.
          `playsInline` 은 모바일에서 전체화면으로 튀는 것을 막는다.
        */}
        <video
          className="tile__video"
          src={`/media/${file}`}
          autoPlay
          loop
          muted
          playsInline
          preload="auto"
        />
        <span className="tile__demo-badge">시연 영상</span>
      </div>

      <figcaption className="tile__bar">
        <span className="dot dot--muted" />
        <span className="tile__name">{name}</span>
        <span className="tile__spacer" />
        {/* 실시간 타일의 REC 자리에 아무것도 두지 않는다 — 녹화 중이 아니다. */}
        <span className="tile__meta">녹화 재생</span>
      </figcaption>
    </figure>
  )
}
