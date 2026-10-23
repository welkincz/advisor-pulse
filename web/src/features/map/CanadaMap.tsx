import { type KeyboardEvent, type PointerEvent, type ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { Geometry } from 'geojson'
import { useReducedMotion } from '../../app/useReducedMotion'
import { standardEase } from '../../motion/tween'
import type { Basemap } from './data'
import { labelRank, shift, shortBox, spreadLabels } from './labels'
import { type Box, type Point, type Project, centroid, fit, fitted, lambert, lineData, pathData, projectedBox } from './projection'

/** A district's shape, which places its circle at the middle of its branch FSAs. Pass a stable array. */
export interface MapPlace { id: string; name: string; region: string; geometry: Geometry }
/** What changes with the week: circle size (activity volume), colour and value label. */
/** `empty`: no value this week at all (a dashed ring). A value with no comparison yet is `fill: null`. */
export interface MapMark { size: number; fill: string | null; label: string; empty: boolean }
/** An FSA in the optional FSA layer. Pass a stable array; colours come from `overlayFill`. */
export interface MapArea { id: string; name: string; geometry: Geometry }

type Camera = { k: number; x: number; y: number }

const IDENTITY: Camera = { k: 1, x: 0, y: 0 }
const ZOOM_MS = 760
const SWEEP_MS = 700
const MIN_K = 0.8
const MAX_K = 40
const NEUTRAL = 'color-mix(in srgb, var(--ink) 5%, var(--paper))'
const QUIET = 'color-mix(in srgb, var(--ink) 3%, var(--paper))'
const TERRITORY = 'var(--field)'

// Where each region's (province's) name sits on the national view. The Maritimes are too
// small to hold a label, so theirs sit out in the water with a hairline back to the province.
const LABEL_AT: Record<string, { at: [number, number]; anchor?: 'start' | 'end'; from?: [number, number] }> = {
  BC: { at: [-124.6, 54.6] },
  AB: { at: [-114.9, 55.2] },
  SK: { at: [-105.8, 54.6] },
  MB: { at: [-97.6, 55.6] },
  ON: { at: [-86.5, 50.2] },
  QC: { at: [-72.5, 52.5] },
  NL: { at: [-61.2, 53.4] },
  NB: { at: [-69.4, 44.0], anchor: 'end', from: [-66.4, 46.4] },
  NS: { at: [-60.2, 43.4], anchor: 'start', from: [-63.4, 44.9] },
  PE: { at: [-61.4, 48.3], anchor: 'start', from: [-63.2, 46.4] },
}

function grow([[x0, y0], [x1, y1]]: Box, by: number): Box {
  const dx = Math.max((x1 - x0) * by, 30)
  const dy = Math.max((y1 - y0) * by, 30)
  return [[x0 - dx, y0 - dy], [x1 + dx, y1 + dy]]
}

/** Interpolate around the screen centre with a geometric zoom, so a zoom feels like one motion. */
function between(from: Camera, to: Camera, t: number, width: number, height: number): Camera {
  const centre = (c: Camera): Point => [(width / 2 - c.x) / c.k, (height / 2 - c.y) / c.k]
  const [ax, ay] = centre(from)
  const [bx, by] = centre(to)
  const k = from.k * (to.k / from.k) ** t
  const cx = ax + (bx - ax) * t
  const cy = ay + (by - ay) * t
  return { k, x: width / 2 - cx * k, y: height / 2 - cy * k }
}

interface Label { id: string; x: number; y: number; width: number; anchor: 'start' | 'end' }

/**
 * Place district labels beside their circles: flip to the left near the right edge, then
 * nudge down wherever two labels would overlap.
 */
export function placeLabels(items: { id: string; x: number; y: number; r: number; text: string }[], width: number, gap = 15): Label[] {
  const placed: Label[] = []
  for (const item of [...items].sort((a, b) => a.y - b.y)) {
    const textWidth = item.text.length * 6.4
    const anchor = item.x + item.r + 6 + textWidth > width - 4 ? 'end' : 'start'
    const x = anchor === 'start' ? item.x + item.r + 6 : item.x - item.r - 6
    const left = anchor === 'start' ? x : x - textWidth
    let y = item.y
    for (const other of placed) {
      const otherLeft = other.anchor === 'start' ? other.x : other.x - other.width
      const overlaps = left < otherLeft + other.width && otherLeft < left + textWidth
      if (overlaps && Math.abs(other.y - y) < gap) y = other.y + gap
    }
    placed.push({ id: item.id, x, y, width: textWidth, anchor })
  }
  return placed
}

/**
 * Canada in Statistics Canada's Lambert projection, as plain SVG. Provinces take their
 * serving region's colour; districts are circles over them. Choosing a region flies the
 * camera to it. Drag to pan, wheel or +/- to zoom, arrow keys to pan, 0 to reset.
 */
export function CanadaMap({ ready, basemap, width, height, focus, regionNames, regionFill, regionValue, places, mark, overlay, overlayFill, hot, onHot, onRegion, onMark, tooltip, label }: {
  /** False while values load: the basemap draws in neutral and the entrance waits. */
  ready: boolean
  basemap: Basemap
  width: number
  height: number
  focus: string | null
  regionNames: ReadonlyMap<string, string>
  regionFill: (region: string) => string | null
  regionValue: (region: string) => string | null
  places: readonly MapPlace[]
  mark: (id: string) => MapMark | undefined
  overlay?: readonly MapArea[]
  overlayFill?: (id: string) => string | null
  hot: string | null
  onHot: (id: string | null) => void
  onRegion: (region: string | null) => void
  onMark: (id: string) => void
  tooltip: (id: string) => ReactNode
  label: string
}) {
  const reducedMotion = useReducedMotion()
  const svg = useRef<SVGSVGElement>(null)
  const [camera, setCamera] = useState<Camera>(IDENTITY)
  const cameraRef = useRef(camera)
  cameraRef.current = camera
  const flight = useRef(0)
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null)
  const [tip, setTip] = useState<{ x: number; y: number } | null>(null)
  const [sweep, setSweep] = useState<'waiting' | 'running' | 'done'>(reducedMotion ? 'done' : 'waiting')

  const geometry = useMemo(() => {
    if (!width || !height) return null
    const unit = lambert()
    // Fit to the country south of 74°N; the far Arctic islands run off the top edge.
    const box = projectedBox(basemap.provinces.map((p) => p.geometry), unit, ([, lat]) => lat! < 74)
    if (!box) return null
    const project: Project = fitted(unit, box, width, height, 12)
    const provinces = basemap.provinces.map((p) => {
      const d = pathData(p.geometry, project)
      const middle = centroid(p.geometry, project)
      return { code: p.properties.province, name: p.properties.name, region: p.properties.region_code, d, x: middle?.[0] ?? 0 }
    })
    const points = new Map(places.map((m) => [m.id, centroid(m.geometry, project)]))
    const regionBoxes = new Map<string, Box>()
    for (const region of new Set(places.map((m) => m.region))) {
      const found = projectedBox(places.filter((m) => m.region === region).map((m) => m.geometry), project)
      if (found) regionBoxes.set(region, grow(found, 0.35))
    }
    const labels = new Map(Object.entries(LABEL_AT).map(([id, l]) => [id, { at: project(l.at), anchor: (l.anchor ?? 'middle') as 'start' | 'end' | 'middle', from: l.from ? project(l.from) : null }]))
    return {
      provinces, points, regionBoxes, labels,
      borders: lineData(basemap.borders, project),
      regionBorders: lineData(basemap.regionBorders, project),
      project,
    }
  }, [basemap, places, width, height])
  // Kept apart from the basemap so the FSA layer never moves the camera.
  const overlayPaths = useMemo(() => (geometry && overlay ? overlay.map((area) => ({ ...area, d: pathData(area.geometry, geometry.project) })) : []), [geometry, overlay])

  // Fly to the focused region, or back out to the whole country.
  const target = useMemo<Camera>(() => {
    const box = focus ? geometry?.regionBoxes.get(focus) : null
    return box ? fit(box, width, height, 40) : IDENTITY
  }, [focus, geometry, width, height])

  useEffect(() => {
    cancelAnimationFrame(flight.current)
    const from = cameraRef.current
    if (reducedMotion) { setCamera(target); return }
    let start: number | null = null
    const step = (now: number) => {
      start ??= now
      const t = Math.min(1, (now - start) / ZOOM_MS)
      setCamera(between(from, target, standardEase(t), width, height))
      if (t < 1) flight.current = requestAnimationFrame(step)
    }
    flight.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(flight.current)
  }, [target, reducedMotion, width, height])

  // The one entrance: colour sweeps west to east across the country on first paint.
  useEffect(() => {
    if (sweep !== 'waiting' || !geometry || !ready) return
    const frame = requestAnimationFrame(() => setSweep('running'))
    const done = window.setTimeout(() => setSweep('done'), SWEEP_MS + 900)
    return () => { cancelAnimationFrame(frame); window.clearTimeout(done) }
  }, [geometry, sweep, ready])

  const zoomAt = (factor: number, cx: number, cy: number) => {
    cancelAnimationFrame(flight.current)
    setCamera((c) => {
      const k = Math.max(MIN_K, Math.min(MAX_K, c.k * factor))
      const ratio = k / c.k
      return { k, x: cx - (cx - c.x) * ratio, y: cy - (cy - c.y) * ratio }
    })
  }

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
        cancelAnimationFrame(flight.current)
        drag.current = { x: event.clientX, y: event.clientY, moved: true }
        setCamera((c) => ({ ...c, x: c.x + dx, y: c.y + dy }))
        setTip(null)
        return
      }
    }
    const id = (event.target as Element).closest('[data-hot]')?.getAttribute('data-hot') ?? null
    onHot(id)
    setTip(id ? { x: event.clientX - box.left, y: event.clientY - box.top } : null)
  }
  const onPointerUp = () => { setTimeout(() => { drag.current = null }) }
  const clicked = (run: () => void) => () => { if (!drag.current?.moved) run() }
  const onKeyDown = (event: KeyboardEvent<SVGSVGElement>) => {
    const step = 48
    const moves: Record<string, [number, number]> = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }
    if (event.key === '+' || event.key === '=') zoomAt(1.5, width / 2, height / 2)
    else if (event.key === '-') zoomAt(1 / 1.5, width / 2, height / 2)
    else if (event.key === '0') setCamera(target)
    else if (event.key === 'Escape' && focus) onRegion(null)
    else if (moves[event.key]) setCamera((c) => ({ ...c, x: c.x + moves[event.key]![0], y: c.y + moves[event.key]![1] }))
    else return
    event.preventDefault()
  }

  // Province labels are drawn at their spot, then measured and moved apart before paint, so no
  // two touch and none hangs off the canvas. Runs after every render: the camera moves them.
  const provinceLabels = useRef<SVGGElement>(null)
  useLayoutEffect(() => {
    const groups = [...(provinceLabels.current?.querySelectorAll<SVGGElement>('.map-label-group') ?? [])]
    const texts = groups.map((g) => g.querySelector('text')!)
    if (!texts.length || typeof texts[0]!.getBBox !== 'function') return
    const order = groups.map((g, i) => ({ g, text: texts[i]!, id: g.dataset.region ?? '' })).sort((a, b) => labelRank(a.id) - labelRank(b.id))
    const names = order.map(({ text }) => {
      const name = text.firstElementChild as SVGTSpanElement
      // A short code is written straight into the DOM below, which React does not see. Putting
      // the full name (data-name, set by React) back before every measure keeps the two in step.
      if (name.textContent !== name.dataset.name) name.textContent = name.dataset.name ?? ''
      return name
    })
    const spots = spreadLabels(order.map(({ id, text }, i) => {
      const name = shift(names[i]!.getBBox(), 0, 0)
      const anchor = (text.getAttribute('text-anchor') ?? 'middle') as 'start' | 'middle' | 'end'
      const line = order[i]!.g.querySelector('line')
      const at = line ? [Number(line.getAttribute('x1')), Number(line.getAttribute('y1'))] as const : undefined
      return { id, full: shift(text.getBBox(), 0, 0), name, short: shortBox(name, names[i]!.dataset.name ?? '', id, anchor), at }
    }), { width, height })
    order.forEach(({ g, text, id }, i) => {
      const spot = spots[i]!
      if (spot.short) names[i]!.textContent = id
      text.setAttribute('transform', `translate(${spot.dx} ${spot.dy})`)
      g.style.visibility = spot.visible ? '' : 'hidden'
      const value = text.children[1] as SVGTSpanElement | undefined
      if (value) value.style.visibility = spot.visible && spot.value ? '' : 'hidden'
      const line = g.querySelector('line')
      if (line) {
        line.setAttribute('x2', String(Number(line.dataset.x2) + spot.dx))
        line.setAttribute('y2', String(Number(line.dataset.y2) + spot.dy))
      }
    })
  })

  if (!geometry) return null
  const { k, x, y } = camera
  const screen = ([px, py]: Point): Point => [px * k + x, py * k + y]
  const sized = places.flatMap((place) => {
    const info = mark(place.id)
    const point = geometry.points.get(place.id)
    return info && point ? [{ place, info, point }] : []
  })
  const largest = Math.max(1, ...sized.map((m) => m.info.size))
  // Circles scale with the canvas so a phone is not covered in discs.
  const scale = Math.min(1, width / 720)
  const markAt = sized.map(({ place, info, point }) => {
    const [sx, sy] = screen(point)
    const inFocus = place.region === focus
    const r = ((inFocus ? 4 : 2.5) + (inFocus ? 16 : 8) * Math.sqrt(info.size / largest)) * (inFocus ? Math.max(0.6, scale) : 1)
    return { mark: { ...place, ...info }, sx, sy, r, inFocus }
  })
  const labels = placeLabels(markAt.filter((m) => m.inFocus).map((m) => ({ id: m.mark.id, x: m.sx, y: m.sy, r: m.r, text: `${m.mark.name} ${m.mark.label}` })), width)

  const provinceFill = (region: string | null) => {
    if (sweep === 'waiting') return NEUTRAL
    if (!region) return TERRITORY
    if (focus) return region === focus ? NEUTRAL : QUIET
    return regionFill(region) ?? NEUTRAL
  }

  return <>
    <svg ref={svg} className={`canada-map${focus ? ' is-focused' : ''}`} width={width} height={height} viewBox={`0 0 ${width} ${height}`} tabIndex={0}
      role="img" aria-label={`${label}. Drag or use arrow keys to pan; plus and minus to zoom; 0 to reset${focus ? '; Escape to return to Canada' : ''}.`}
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
      onPointerLeave={() => { setTip(null); onHot(null) }} onKeyDown={onKeyDown}>
      <defs>
        <pattern id="map-territory" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="6" className="map-hatch" />
        </pattern>
      </defs>
      <g transform={`translate(${x} ${y}) scale(${k})`}>
        {geometry.provinces.map((p) => {
          const active = p.region && (!focus || p.region !== focus)
          const delay = sweep === 'running' ? `${Math.round((p.x / width) * SWEEP_MS)}ms` : undefined
          return <path key={p.code} d={p.d} className={`map-province${p.region && p.region === hot ? ' is-hot' : ''}${active ? ' is-link' : ''}`}
            style={{ fill: provinceFill(p.region), transitionDelay: delay }}
            data-hot={p.region && !focus ? p.region : undefined}
            onClick={clicked(() => { if (p.region && p.region !== focus) onRegion(p.region) })} />
        })}
        {geometry.provinces.filter((p) => !p.region).map((p) => <path key={`hatch-${p.code}`} d={p.d} className="map-territory" />)}
        <path d={geometry.borders} className="map-border" />
        <path d={geometry.regionBorders} className="map-region-border" />
        {overlayPaths.map((area) => <path key={area.id} d={area.d} className="map-fsa" style={{ fill: overlayFill?.(area.id) ?? NEUTRAL }} data-hot={area.id} />)}
      </g>
      <g className="map-marks">
        {markAt.map(({ mark, sx, sy, r, inFocus }) => <circle key={mark.id} cx={sx} cy={sy} style={{ r, fill: inFocus && !mark.empty ? mark.fill ?? NEUTRAL : undefined }}
          className={`map-mark${inFocus ? ' is-focus' : ''}${inFocus && mark.empty ? ' is-empty' : ''}${mark.id === hot ? ' is-hot' : ''}`} data-hot={mark.id}
          onClick={clicked(() => inFocus ? onMark(mark.id) : onRegion(mark.region))} />)}
      </g>
      <g className="map-labels" aria-hidden="true" ref={provinceLabels}>
        {!focus && [...geometry.labels].filter(([id]) => regionNames.has(id)).map(([id, label]) => {
          const [lx, ly] = screen(label.at)
          const value = regionValue(id)
          const from = label.from ? screen(label.from) : null
          const end = [lx + (label.anchor === 'end' ? 4 : -4), ly - 4]
          return <g key={id} className={`map-label-group${id === hot ? ' is-hot' : ''}`} data-region={id}>
            {from && <line className="map-leader" x1={from[0]} y1={from[1]} x2={end[0]} y2={end[1]} data-x2={end[0]} data-y2={end[1]} />}
            <text x={lx} y={ly} className={`map-label${id === hot ? ' is-hot' : ''}${from ? ' map-label-small' : ''}`} textAnchor={label.anchor}>
              <tspan className="map-label-name" data-name={regionNames.get(id)}>{regionNames.get(id)}</tspan>
              {value && <tspan x={lx} dy="1.25em" className="map-label-value">{value}</tspan>}
            </text>
          </g>
        })}
        {focus && labels.map((label) => {
          const mark = markAt.find((m) => m.mark.id === label.id)!.mark
          return <text key={label.id} x={label.x} y={label.y} dy="0.35em" textAnchor={label.anchor} className={`map-label map-label-small${label.id === hot ? ' is-hot' : ''}`}>
            <tspan className="map-label-name">{mark.name}</tspan><tspan dx="0.4em" className="map-label-value">{mark.label}</tspan>
          </text>
        })}
      </g>
    </svg>
    {tip && hot && <div className={`map-tooltip${tip.y > height / 2 ? ' is-above' : ''}`} style={{ left: Math.max(0, Math.min(tip.x, width - 340)), top: tip.y }}>{tooltip(hot)}</div>}
  </>
}
