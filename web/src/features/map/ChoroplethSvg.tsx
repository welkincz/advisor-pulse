import { type KeyboardEvent, type PointerEvent, useEffect, useMemo, useRef, useState } from 'react'
import type { Position } from 'geojson'
import type { Boundary } from './data'

type Bounds = [[number, number], [number, number]]
type View = { k: number; x: number; y: number }

const PADDING = 32
// deck.gl's old camera cap: zoom 8 on 512 px tiles, in pixels per radian of longitude.
const MAX_FIT_SCALE = (512 * 2 ** 8) / (2 * Math.PI)
const MIN_ZOOM = 1
const MAX_ZOOM = 16

/** Web Mercator in radians; y grows southward like screen space. */
function mercator([lon, lat]: Position): [number, number] {
  const phi = (Math.max(-85, Math.min(85, lat!)) * Math.PI) / 180
  return [(lon! * Math.PI) / 180, -Math.log(Math.tan(Math.PI / 4 + phi / 2))]
}

/** Scale and offset that fit `bounds` into the canvas with padding, like a camera fitBounds. */
export function fitProjection(bounds: Bounds, width: number, height: number) {
  const [x0, y1] = mercator(bounds[0])
  const [x1, y0] = mercator(bounds[1])
  const scale = Math.min(MAX_FIT_SCALE, (width - 2 * PADDING) / Math.max(x1 - x0, 1e-9), (height - 2 * PADDING) / Math.max(y1 - y0, 1e-9))
  const dx = width / 2 - ((x0 + x1) / 2) * scale
  const dy = height / 2 - ((y0 + y1) / 2) * scale
  return (point: Position): [number, number] => {
    const [x, y] = mercator(point)
    return [x * scale + dx, y * scale + dy]
  }
}

export function pathData(feature: Boundary, project: (point: Position) => [number, number]): string {
  const polygons = feature.geometry.type === 'Polygon' ? [feature.geometry.coordinates] : feature.geometry.coordinates
  return polygons.map((rings) => rings.map((ring) => ring.map((point, i) => {
    const [x, y] = project(point)
    return `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`
  }).join('') + 'Z').join('')).join('')
}

/**
 * The choropleth as plain SVG: no basemap, drag to pan, wheel or +/- to zoom, arrow keys
 * to pan when focused. The list beside it is the keyboard route to each area's report.
 */
export function ChoroplethSvg({ features, bounds, width, height, idOf, nameOf, fill, onSelect, label }: {
  features: readonly Boundary[]
  bounds: Bounds | null
  width: number
  height: number
  idOf: (feature: Boundary) => string | undefined
  nameOf: (feature: Boundary) => string | undefined
  fill: (feature: Boundary) => string
  onSelect?: (id: string) => void
  label: string
}) {
  const svg = useRef<SVGSVGElement>(null)
  const [view, setView] = useState<View>({ k: 1, x: 0, y: 0 })
  const [tip, setTip] = useState<{ text: string; x: number; y: number } | null>(null)
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null)

  const paths = useMemo(() => {
    if (!bounds || !width) return []
    const project = fitProjection(bounds, width, height)
    return features.map((feature) => ({ feature, d: pathData(feature, project) }))
  }, [features, bounds, width, height])

  const zoomAt = (factor: number, cx: number, cy: number) => setView((v) => {
    const k = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, v.k * factor))
    const ratio = k / v.k
    return { k, x: cx - (cx - v.x) * ratio, y: cy - (cy - v.y) * ratio }
  })

  // React's onWheel is passive, so the page would scroll too; listen directly instead.
  useEffect(() => {
    const element = svg.current
    if (!element) return
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const box = element.getBoundingClientRect()
      zoomAt(Math.exp(-event.deltaY * 0.002), event.clientX - box.left, event.clientY - box.top)
    }
    element.addEventListener('wheel', onWheel, { passive: false })
    return () => element.removeEventListener('wheel', onWheel)
  }, [])

  const onPointerDown = (event: PointerEvent<SVGSVGElement>) => {
    drag.current = { x: event.clientX, y: event.clientY, moved: false }
  }
  const onPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    const start = drag.current
    if (start && event.buttons) {
      const dx = event.clientX - start.x
      const dy = event.clientY - start.y
      if (start.moved || Math.hypot(dx, dy) > 3) {
        if (!start.moved) event.currentTarget.setPointerCapture(event.pointerId)
        start.moved = true
        drag.current = { x: event.clientX, y: event.clientY, moved: true }
        setView((v) => ({ ...v, x: v.x + dx, y: v.y + dy }))
        setTip(null)
        return
      }
    }
    const target = (event.target as Element).closest('path')
    const text = target?.getAttribute('data-name')
    setTip(text ? { text, x: event.clientX - box.left, y: event.clientY - box.top } : null)
  }
  const onPointerUp = () => { setTimeout(() => { drag.current = null }) }
  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    const step = 40
    const moves: Record<string, [number, number]> = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }
    if (event.key === '+' || event.key === '=') zoomAt(1.5, width / 2, height / 2)
    else if (event.key === '-') zoomAt(1 / 1.5, width / 2, height / 2)
    else if (event.key === '0') setView({ k: 1, x: 0, y: 0 })
    else if (moves[event.key]) setView((v) => ({ ...v, x: v.x + moves[event.key]![0], y: v.y + moves[event.key]![1] }))
    else return
    event.preventDefault()
  }

  return <>
    <svg ref={svg} className="map-svg" width={width} height={height} viewBox={`0 0 ${width} ${height}`} tabIndex={0}
      role="img" aria-label={`${label}. Drag or use arrow keys to pan; plus and minus to zoom; 0 to reset.`}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
      onPointerLeave={() => setTip(null)} onKeyDown={onKeyDown}>
      <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
        {paths.map(({ feature, d }, i) => {
          const id = idOf(feature)
          return <path key={id ?? i} d={d} style={{ fill: fill(feature) }} data-id={id} data-name={nameOf(feature) ?? id}
            className={onSelect && id ? 'map-area map-area-link' : 'map-area'}
            onClick={() => { if (onSelect && id && !drag.current?.moved) onSelect(id) }} />
        })}
      </g>
    </svg>
    {tip && <div className="map-tooltip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>}
  </>
}
