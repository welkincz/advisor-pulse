import { LEVEL_BELOW, formatChange } from '../../data/kpi'

export type Better = 'higher' | 'lower' | 'neither'

function judge(value: number, better: Better): 'better' | 'worse' | 'flat' {
  if (Math.abs(value) < LEVEL_BELOW || better === 'neither') return 'flat'
  return (value > 0) === (better === 'higher') ? 'better' : 'worse'
}

const GLYPH = { up: '▲', down: '▼', flat: '■' } as const
const WORD = { better: 'better than', worse: 'worse than', flat: 'level with' } as const

/**
 * Week-over-week change. Direction is the glyph and sign; better or worse is colour plus the
 * spoken label, judged with `better` so a falling no-show rate reads as good news.
 */
export function Delta({ value, better = 'higher', against = 'last week' }: { value: number | null | undefined; better?: Better; against?: string }) {
  if (value === null || value === undefined) return <span className="delta delta-none">No prior week</span>
  const verdict = judge(value, better)
  const direction = Math.abs(value) < LEVEL_BELOW ? 'flat' : value > 0 ? 'up' : 'down'
  const text = formatChange(value)
  // role="img" makes the label valid on a span (axe: aria-prohibited-attr); the parts are hidden.
  return <span className={`delta delta-${verdict}`} role="img" aria-label={`${text}, ${WORD[verdict]} ${against}`}>
    <span className="delta-glyph" aria-hidden="true">{GLYPH[direction]}</span>
    <span className="figure-num" aria-hidden="true">{text}</span>
  </span>
}
