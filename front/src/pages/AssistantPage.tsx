/**
 * 챗봇 전용 화면 (FN-UI-06 · API명세서 §4.4).
 *
 * **대화 본체는 `chat/AssistantChat` 에 있다.** 실시간 관제 사이드에도 같은 것이
 * 들어가므로(FN-UI-02) 두 벌로 두지 않는다 — 라우팅 표시나 첨부 처리가 한쪽에만
 * 반영되면 같은 질문에 화면마다 다른 근거가 보인다.
 *
 * 이 파일이 하는 일은 전용 화면의 폭과 여백을 주는 것뿐이다.
 */

import AssistantChat from '../chat/AssistantChat'
import './analysis.css'

export default function AssistantPage() {
  return (
    <div className="analysis analysis--chat">
      <AssistantChat />
    </div>
  )
}
