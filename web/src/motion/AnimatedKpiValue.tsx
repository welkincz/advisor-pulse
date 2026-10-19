import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from '../app/useReducedMotion'
import { formatKpi } from '../data'
import type { KpiCode } from '../data/generated/weekly_report'
import { tween } from './tween'
import './motion.css'

/** Tween a changed weekly value while assistive technology receives only the final value. */
export function AnimatedKpiValue({ code, value }: { code: KpiCode; value: number | null }) {
  const reducedMotion = useReducedMotion()
  const [shownNumber, setShownNumber] = useState(value ?? 0)
  const current = useRef(value ?? 0)
  const previous = useRef(value)
  const final = formatKpi(code, value)
  const prior = formatKpi(code, previous.current)

  useEffect(() => {
    const before = previous.current
    previous.current = value
    const set = (number: number) => { current.current = number; setShownNumber(number) }
    if (value == null || reducedMotion || before == null || before === value) {
      set(value ?? 0)
      return
    }
    return tween(current.current, value, 600, set)
  }, [code, reducedMotion, value])

  if (value == null || reducedMotion) return final
  return <span className="motion-number" data-motion-number>
    <span className="motion-number-reserve" aria-hidden="true" data-reserve={prior.length > final.length ? prior : final} />
    <span className="motion-number-visual" aria-hidden="true">{formatKpi(code, shownNumber)}</span>
    <span className="motion-sr-only">Value: {final}</span>
  </span>
}
