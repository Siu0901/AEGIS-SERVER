/**
 * 영상 검색 (FN-UI-04 · API명세서 §4.3).
 *
 * 자연어 질의 한 줄과 유사도순 결과. 시안의 정보구조(상단 질의 · 하단 카드 그리드)를
 * 따르되 라벨은 명세서를 쓴다(부록 B).
 *
 * 이 화면의 판단들:
 *
 * · **`mode` 를 숨기지 않는다.** 서버가 SQL 로 답했는지 벡터로 답했는지에 따라 결과
 *   순서의 의미가 다르다 — `sql` 이면 시간순이고 `vector`·`hybrid` 면 유사도순이다.
 *   그것을 표시하지 않으면 사용자는 왜 이 순서인지 알 수 없다
 * · **유사도가 없는 항목에 숫자를 그리지 않는다.** `similarity` 가 `null` 이면 재지
 *   않았다는 뜻이고(§4.3 `mode = "sql"`), 0% 로 그리면 "전혀 안 닮았다"가 된다
 * · **클립이 없는 결과도 보여준다.** 확정 직후에는 `clip_status` 가 `pending` 이라
 *   클립이 없다. 그때는 키프레임을 대신 띄우고, 그것도 없으면 자리만 남긴다 —
 *   결과에서 빼면 방금 난 위반이 검색되지 않는다
 * · **예시 질의를 함께 둔다.** 무엇을 물어볼 수 있는지 모르면 이 화면은 빈칸 하나다.
 *   하이브리드가 무엇을 하는지도 예시가 가장 잘 설명한다
 */

import { useCallback, useState } from 'react'
import { searchScenes } from '../api/analysis'
import type { SceneSearchItem, SearchMode } from '../types/contracts'
import { stamp } from '../types/labels'
import './analysis.css'

/** 한 번에 받아올 결과 수. 카드 그리드 3열 × 4줄이면 화면을 채운다. */
const TOP_K = 12

/** §4.3 `mode` 를 사람이 읽는 문장으로. **순서의 의미가 여기서 갈린다.** */
const MODE_LABEL: Record<SearchMode, string> = {
  sql: '조건 검색 (최신순)',
  vector: '장면 유사도순',
  hybrid: '조건 + 장면 유사도순',
}

const MODE_NOTE: Record<SearchMode, string> = {
  sql: '기간 · 카메라 · 유형 조건으로 찾았다.',
  vector: '문장과 닮은 장면 순으로 정렬했다.',
  hybrid: '조건으로 좁힌 뒤 문장과 닮은 순으로 정렬했다.',
}

/** 무엇을 물어볼 수 있는지 보여주는 예시. 세 경로가 하나씩이다. */
const EXAMPLES = [
  '지난주 1번 카메라 안전모 미착용',
  '지게차 근처에서 작업하던 장면',
  '오늘 금지구역 침입',
]

export default function SearchPage() {
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<SceneSearchItem[] | null>(null)
  const [mode, setMode] = useState<SearchMode | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return
    setBusy(true)
    setError(null)
    try {
      const found = await searchScenes({
        query: trimmed,
        top_k: TOP_K,
        filters: { from: null, to: null, cam_id: null },
      })
      setItems(found.items)
      setMode(found.mode)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
      setItems(null)
      setMode(null)
    } finally {
      setBusy(false)
    }
  }, [])

  return (
    <div className="analysis">
      <section className="card">
        <h2 className="card__title">영상 검색</h2>
        <form
          className="search__form"
          onSubmit={(event) => {
            event.preventDefault()
            void run(query)
          }}
        >
          <input
            className="search__input"
            value={query}
            placeholder="예: 지난주 1번 카메라에서 지게차 가까이 있던 장면"
            onChange={(event) => setQuery(event.target.value)}
            aria-label="장면 검색 질의"
          />
          <button type="submit" className="btn btn--primary" disabled={busy || !query.trim()}>
            {busy ? '찾는 중…' : '검색'}
          </button>
        </form>

        <div className="search__examples">
          <span className="search__examples-label">예시</span>
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="chip"
              onClick={() => {
                setQuery(example)
                void run(example)
              }}
            >
              {example}
            </button>
          ))}
        </div>

        {/* ★ 어느 경로로 답했는지 밝힌다 — 결과 순서의 의미가 여기서 갈린다. */}
        {mode && (
          <p className="card__note">
            <strong>{MODE_LABEL[mode]}</strong> · {MODE_NOTE[mode]}
          </p>
        )}
        {error && <p className="analysis__error">{error}</p>}
      </section>

      <section className="card">
        <h2 className="card__title">결과 {items ? `${items.length}건` : ''}</h2>
        {items !== null && items.length === 0 && (
          <p className="card__note">
            조건에 맞는 장면이 없다.
          </p>
        )}
        <div className="search__grid">
          {(items ?? []).map((item) => (
            <ResultCard key={item.event_id} item={item} />
          ))}
        </div>
      </section>
    </div>
  )
}

function ResultCard({ item }: { item: SceneSearchItem }) {
  return (
    <a className="search__card" href={`/events?event=${item.event_id}`}>
      <div className="search__thumb">
        {item.thumbnail_url ? (
          <img src={item.thumbnail_url} alt={item.title} loading="lazy" />
        ) : (
          // 확정 직후에는 키프레임 추출이 아직 끝나지 않았다(FN-REC-03). 결과에서
          // 빼지 않고 자리만 남긴다 — 빼면 방금 난 위반이 검색되지 않는다.
          <span className="search__thumb-empty">그림 없음</span>
        )}
        {/* ★ 재지 않은 유사도를 0% 로 그리지 않는다(§4.3). */}
        {item.similarity !== null && (
          <span className="search__score">{Math.round(item.similarity * 100)}%</span>
        )}
      </div>
      <div className="search__meta">
        <strong>{item.title}</strong>
        <span>{stamp(item.occurred_at)}</span>
        <span className="search__id">{item.event_id}</span>
        {!item.clip_url && <span className="search__pending">클립 준비 중</span>}
      </div>
    </a>
  )
}
