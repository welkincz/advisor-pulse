import { animate, motion, useMotionValue, useTransform } from 'motion/react'
import { useEffect, useRef } from 'react'
import { useReducedMotion } from '../app/useReducedMotion'
import { formatKpi } from '../data'
import type { KpiCode } from '../data/generated/weekly_report'
import './motion.css'

/** Tween a changed weekly value while assistive technology receives only the final value. */
export function AnimatedKpiValue({ code, value }: { code: KpiCode; value: number | null }) {
  const reducedMotion = useReducedMotion()
  const current = useMotionValue(value ?? 0)
  const shown = useTransform(current, (number) => formatKpi(code, number))
  const previous = useRef(value)
  const final = formatKpi(code, value)
  const prior = formatKpi(code, previous.current)

  useEffect(() => {
    const before = previous.current
    previous.current = value
    if (value == null || reducedMotion || before == null || before === value) {
      current.set(value ?? 0)
      return
    }
    const controls = animate(current, value, { duration: 0.6, ease: [0.2, 0, 0, 1] })
    return () => controls.stop()
  }, [code, current, reducedMotion, value])

  if (value == null || reducedMotion) return final
  return <span className="motion-number" data-motion-number>
    <span className="motion-number-reserve" aria-hidden="true" data-reserve={prior.length > final.length ? prior : final} />
    <motion.span className="motion-number-visual" aria-hidden="true">{shown}</motion.span>
    <span className="motion-sr-only">Value: {final}</span>
  </span>
}
