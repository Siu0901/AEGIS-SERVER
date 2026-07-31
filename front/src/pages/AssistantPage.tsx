/**
 * 챗봇 (FN-UI-06 · API명세서 §4.4).
 *
 * 통계 · 장면 검색 · 현재 상황 브리핑을 한 창에서 묻는다. 경로는 서버가 정하고
 * (`route`) 화면은 그것을 **표시**한다.
 *
 * 이 화면의 판단들:
 *
 * · ★ **어느 경로로 답했는지 밝힌다.** 통계(SQL)와 장면 검색(임베딩)과 현재 화면
 *   판독(멀티모달)은 근거의 종류가 다르다. 같은 말풍선으로 보여주면 사람은 셋을
 *   같은 신뢰도로 읽는다
 * · ★ **표(`table`)의 `null` 을 그대로 `–` 로 그린다**(§6.7). 서버는 셀에 `null` 을
 *   담아 보내고, `0%` 로 접는 판단은 하지 않는다 — 그 판단이 여기 있다
 * · **첨부는 §4.4 네 종류를 전부 그린다.** 클립·이미지·표·이벤트 링크. 모르는 종류가
 *   오면 조용히 버리지 않고 그 사실을 적는다(절대규칙 9)
 * · **세션 ID 는 브라우저가 만든다.** 서버가 대화 이력을 들고 있지 않으므로 이 값은
 *   지금 로그 상관용이다 — 그 사실을 화면이 숨기지 않는다
 */

import { useEffect, useRef, useState } from 'react'
import { askAssistant } from '../api/analysis'
import type {
  ChatResponse,
  ChatRoute,
  ClipAttachment,
  EventRefAttachment,
  ImageAttachment,
  TableAttachment,
} from '../types/contracts'

/**
 * §4.4 `attachments[]` 원소. 생성기가 유니온 별칭을 만들지 않으므로 여기서 짓는다 —
 * `ChatResponse.attachments` 의 원소 타입과 **같은 네 가지**다.
 */
type Attachment = ClipAttachment | ImageAttachment | TableAttachment | EventRefAttachment
import './analysis.css'

/** §4.4 `route` — 무엇을 근거로 답했는가. */
const ROUTE_LABEL: Record<ChatRoute, string> = {
  sql: 'SQL 집계',
  vector: '장면 검색',
  vision: '현재 화면',
}

const ROUTE_NOTE: Record<ChatRoute, string> = {
  sql: '이벤트 표를 집계한 숫자다. 표를 함께 실어 문장과 대조할 수 있다.',
  // ★ 「임베딩으로 찾았다」고 단정하지 않는다. 조건이 전부 구조화되어 있거나
  //   클라우드가 꺼져 있으면 같은 경로가 SQL 로 떨어진다 — 실제로 무엇이
  //   돌았는지는 근거 줄의 `mode` 에 있다.
  vector: '과거 이벤트에서 찾은 장면이다. 실제 처리 경로는 아래 근거의 mode 를 봐라.',
  vision: '지금 이 순간의 프레임을 보고 만든 요약이다.',
}

const EXAMPLES = [
  '이번 주 위반 몇 건이야',
  '지게차 근처 작업 장면 찾아줘',
  '지금 1번 카메라 상황은?',
]

type Turn = { question: string; answer: ChatResponse | null; error: string | null }

export default function AssistantPage() {
  const [message, setMessage] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [busy, setBusy] = useState(false)
  const sessionId = useRef(`s-${Date.now().toString(36)}`)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns])

  const ask = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || busy) return
    setBusy(true)
    setMessage('')
    setTurns((current) => [...current, { question: trimmed, answer: null, error: null }])
    try {
      const answer = await askAssistant({ session_id: sessionId.current, message: trimmed })
      setTurns((current) =>
        current.map((turn, index) =>
          index === current.length - 1 ? { ...turn, answer } : turn,
        ),
      )
    } catch (cause) {
      const detail = cause instanceof Error ? cause.message : String(cause)
      setTurns((current) =>
        current.map((turn, index) =>
          index === current.length - 1 ? { ...turn, error: detail } : turn,
        ),
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="analysis analysis--chat">
      <section className="card chat">
        <h2 className="card__title">챗봇</h2>
        <div className="chat__log">
          {turns.length === 0 && (
            <p className="card__note">
              통계는 SQL 로, 장면 검색은 임베딩으로, 「지금 상황」은 현재 프레임으로
              답한다(FN-AI-08). 어느 경로로 답했는지는 답변마다 표시된다.
            </p>
          )}
          {turns.map((turn, index) => (
            <div key={index} className="chat__turn">
              <p className="chat__ask">{turn.question}</p>
              {turn.answer === null && turn.error === null && (
                <p className="chat__pending">생각하는 중…</p>
              )}
              {turn.error && <p className="analysis__error">{turn.error}</p>}
              {turn.answer && <Answer answer={turn.answer} />}
            </div>
          ))}
          <div ref={endRef} />
        </div>

        <div className="search__examples">
          <span className="search__examples-label">예시</span>
          {EXAMPLES.map((example) => (
            <button key={example} type="button" className="chip" onClick={() => void ask(example)}>
              {example}
            </button>
          ))}
        </div>

        <form
          className="search__form"
          onSubmit={(event) => {
            event.preventDefault()
            void ask(message)
          }}
        >
          <input
            className="search__input"
            value={message}
            placeholder="현장에 대해 물어봐라"
            onChange={(event) => setMessage(event.target.value)}
            aria-label="챗봇 질의"
          />
          <button type="submit" className="btn btn--primary" disabled={busy || !message.trim()}>
            보내기
          </button>
        </form>
        <p className="card__note">
          세션 {sessionId.current} · 서버는 대화 이력을 들고 있지 않다. 질의 하나가 곧
          한 번의 조회다.
        </p>
      </section>
    </div>
  )
}

function Answer({ answer }: { answer: ChatResponse }) {
  return (
    <div className="chat__answer">
      <p className="chat__route">
        <span className="chip chip--on">{ROUTE_LABEL[answer.route]}</span>
        {ROUTE_NOTE[answer.route]}
      </p>
      <p className="chat__text">{answer.answer}</p>
      {answer.attachments.map((attachment, index) => (
        <Attachment key={index} attachment={attachment} />
      ))}
      {answer.sources.length > 0 && (
        <p className="chat__sources">
          근거: {answer.sources.map((source) => `${source.type} — ${source.detail}`).join(' · ')}
        </p>
      )}
    </div>
  )
}

function Attachment({ attachment }: { attachment: Attachment }) {
  if (attachment.kind === 'table') {
    return (
      <table className="analysis__table chat__table">
        <thead>
          <tr>
            {attachment.columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {attachment.rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className={typeof cell === 'number' ? 'analysis__num' : ''}>
                  {/* ★ `null` 은 `–` 다(§6.7). 0 으로 접으면 「판정 가능한 이벤트가
                      없다」가 「0%」로 둔갑한다. 단위는 항목 이름에 적혀 오므로
                      (「… (%)」) 화면이 숫자의 뜻을 추측하지 않는다. */}
                  {cell === null ? '–' : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    )
  }
  if (attachment.kind === 'clip') {
    return (
      <a className="chat__clip" href={`/events?event=${attachment.event_id}`}>
        <img src={attachment.thumbnail_url} alt={attachment.label} loading="lazy" />
        <span>{attachment.label}</span>
      </a>
    )
  }
  if (attachment.kind === 'image') {
    return (
      <figure className="chat__image">
        <img src={attachment.image_url} alt={attachment.label} loading="lazy" />
        <figcaption>{attachment.label}</figcaption>
      </figure>
    )
  }
  if (attachment.kind === 'event_ref') {
    return (
      <a className="chip" href={`/events?event=${attachment.event_id}`}>
        {attachment.label}
      </a>
    )
  }
  // 모르는 첨부 종류다. **조용히 버리지 않는다**(절대규칙 9) — 계약이 늘었는데
  // 화면이 따라오지 않은 것이고, 그 사실이 드러나야 고칠 수 있다.
  return <p className="analysis__error">표시할 수 없는 첨부다: {JSON.stringify(attachment)}</p>
}
