import { useEffect, useRef } from 'react'
import type { EChartsCoreOption, EChartsType } from 'echarts/core'
import { useReducedMotion } from '../../app/useReducedMotion'
import { pulseTheme } from '../../theme/echarts'
import { useColorScheme } from '../../theme/tokens'

type Core = typeof import('echarts/core')
let engine: Promise<Core> | null = null

/** ECharts, tree-shaken to what the report uses and loaded on the first chart. */
function loadEcharts(): Promise<Core> {
  engine ??= import('./echarts').then((m) => m.core)
  return engine
}

/**
 * The only way to draw an ECharts chart in the app, so every chart gets the Pulse theme
 * for the current colour scheme, SVG rendering, resize handling and reduced motion.
 * Put it inside a <Figure> so it has a title and a table view.
 */
export function Chart({ option, label, height = 240 }: { option: EChartsCoreOption; label: string; height?: number }) {
  const element = useRef<HTMLDivElement>(null)
  const chart = useRef<EChartsType | null>(null)
  const latest = useRef(option)
  latest.current = option
  const scheme = useColorScheme()
  const reducedMotion = useReducedMotion()

  // Re-create on a scheme change: the theme is read from tokens.css at init.
  useEffect(() => {
    let disposed = false
    let observer: ResizeObserver | undefined
    loadEcharts().then((core) => {
      if (disposed || !element.current) return
      core.registerTheme(`pulse-${scheme}`, pulseTheme())
      const instance = core.init(element.current, `pulse-${scheme}`, { renderer: 'svg' })
      instance.setOption({ ...latest.current, animation: !reducedMotion })
      chart.current = instance
      observer = new ResizeObserver(() => instance.resize())
      observer.observe(element.current)
    })
    return () => {
      disposed = true
      observer?.disconnect()
      chart.current?.dispose()
      chart.current = null
    }
  }, [scheme, reducedMotion])

  useEffect(() => {
    chart.current?.setOption({ ...option, animation: !reducedMotion }, { notMerge: true })
  }, [option, reducedMotion])

  return <div ref={element} className="chart" role="img" aria-label={label} style={{ height }} />
}
