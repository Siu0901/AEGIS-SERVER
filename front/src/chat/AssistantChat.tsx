/**
 * 챗봇 본체 (FN-UI-06 · API명세서 §4.4).
 *
 * **자리는 실시간 관제 사이드 하나다.** 전용 화면을 두지 않는 이유는 「지금 상황은?」이
 * 현재 프레임을 읽어 답하기 때문이다 — 영상을 보면서 묻는 자리가 맞고, 같은 것을 두
 * 곳에서 열 수 있으면 대화 세션이 어디에 있는지 헷갈린다.
 *
 * 사이드에서는 `compact` 로 넣는다. 좁은 폭에서 예시 칩과 안내문이 대화 자체를
 * 밀어내므로 그 둘을 접는다. `compact` 아닌 쪽은 넓은 자리에 다시 놓게 될 때를 위해
 * 남겨 둔 것이며, 지금 부르는 곳은 없다.
 *
 * 세션은 `sessionStorage` 다. **`localStorage` 가 아니다** — 다른 탭·다음 날의 대화까지
 * 살아나면 서버 이력(상한 8턴)과 어긋나 화면만 옛 말을 기억한다.
 */

import { useEffect, useRef, useState } from 'react'
import { askAssistant, clearAssistant } from '../api/analysis'
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
  '오늘 시정률 알려줘',
  '이번 주 위반 몇 건이야',
  '지게차 근처 작업 장면 찾아줘',
  '지금 1번 카메라 상황은?',
]

/** 좁은 사이드에서 쓰는 짧은 예시. 네 개를 다 넣으면 두 줄을 먹는다. */
const EXAMPLES_COMPACT = ['오늘 시정률', '지금 상황은?']

type Turn = { question: string; answer: ChatResponse | null; error: string | null }

const STORE_KEY = 'aegis.assistant'

function loadStored(): { sessionId: string; turns: Turn[] } {
  try {
    const raw = sessionStorage.getItem(STORE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as { sessionId: string; turns: Turn[] }
      if (parsed.sessionId && Array.isArray(parsed.turns)) return parsed
    }
  } catch {
    // 저장 형식이 바뀌었거나 깨졌다. 새 세션으로 시작한다 — 대화 이력은 놓쳐도
    // 안전에 영향이 없다.
  }
  return { sessionId: `s-${Date.now().toString(36)}`, turns: [] }
}

export default function AssistantChat({ compact = false }: { compact?: boolean }) {
  const stored = useRef(loadStored())
  const [message, setMessage] = useState('')
  const [turns, setTurns] = useState<Turn[]>(stored.current.turns)
  const [busy, setBusy] = useState(false)
  const sessionId = useRef(stored.current.sessionId)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns])

  // 화면을 떠나도 남는다. 「생각하는 중」인 턴은 저장하지 않는다 — 돌아왔을 때
  // 영영 답이 오지 않는 말풍선이 남는다.
  useEffect(() => {
    const settled = turns.filter((turn) => turn.answer !== null || turn.error !== null)
    sessionStorage.setItem(
      STORE_KEY,
      JSON.stringify({ sessionId: sessionId.current, turns: settled }),
    )
  }, [turns])

  const clear = () => {
    void clearAssistant(sessionId.current)
    // ★ **세션 ID 도 새로 만든다.** 같은 ID 를 쓰면 서버가 지우지 못한 이력이 남아
    //   있을 때 새 대화가 옛 화제를 이어받는다.
    sessionId.current = `s-${Date.now().toString(36)}`
    setTurns([])
    sessionStorage.removeItem(STORE_KEY)
  }

  const ask = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || busy) return
    setBusy(true)
    setMessage('')
    setTurns((current) => [...current, { question: trimmed, answer: null, error: null }])
    try {
      const answer = await askAssistant({ session_id: sessionId.current, message: trimmed })
      setTurns((current) =>
        current.map((turn, index) => (index === current.length - 1 ? { ...turn, answer } : turn)),
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

  const examples = compact ? EXAMPLES_COMPACT : EXAMPLES

  return (
    <section className={compact ? 'card chat chat--compact' : 'card chat'}>
      <div className="analysis__head">
        <h2 className="card__title">챗봇</h2>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={clear}
          disabled={busy || turns.length === 0}
        >
          대화 지우기
        </button>
      </div>

      <div className="chat__log">
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
        {!compact && <span className="search__examples-label">예시</span>}
        {examples.map((example) => (
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
          placeholder={compact ? '현장에 대해 물어봐라' : '현장에 대해 물어봐라'}
          onChange={(event) => setMessage(event.target.value)}
          aria-label="챗봇 질의"
        />
        <button type="submit" className="btn btn--primary" disabled={busy || !message.trim()}>
          보내기
        </button>
      </form>

    </section>
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
