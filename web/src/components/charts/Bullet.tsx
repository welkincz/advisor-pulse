import './charts.css'

/**
 * A bullet chart: a hairline track, the observed value as a bar from zero, and tick marks
 * at the warn and fail limits. A limit beyond the track is noted in words, not drawn.
 */
export function Bullet({ observed, max, warn, fail, format, label }: {
  observed: number
  max: number
  warn?: number
  fail?: number
  format: (value: number) => string
  label: string
}) {
  const at = (value: number) => `${Math.min(100, (value / max) * 100)}%`
  // Limits are inclusive ("lag <= 2 days"), so only a value beyond one changes the bar.
  const over = (fail != null && observed > fail) ? 'is-fail' : (warn != null && observed > warn) ? 'is-warn' : ''
  const offScale = [warn != null && warn > max ? `warn ${format(warn)}` : null, fail != null && fail > max ? `fail ${format(fail)}` : null].filter(Boolean)
  return <div className="bullet" role="img" aria-label={label}>
    <div className="bullet-track">
      <i className={`bullet-bar ${over}`.trim()} style={{ inlineSize: at(observed) }} />
      {warn != null && warn <= max && <span className="bullet-limit is-warn" style={{ insetInlineStart: at(warn) }}><b>warn {format(warn)}</b></span>}
      {fail != null && fail <= max && <span className="bullet-limit is-fail" style={{ insetInlineStart: at(fail) }}><b>{fail === warn ? '' : 'fail '}{format(fail)}</b></span>}
    </div>
    <div className="bullet-scale" aria-hidden="true"><span>0</span>{offScale.length > 0 && <span>{offScale.join(', ')} off scale</span>}<span>{format(max)}</span></div>
  </div>
}
