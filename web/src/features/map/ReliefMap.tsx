import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import type { Geometry, Position } from 'geojson'
import {
  AmbientLight, BufferGeometry, Color, CylinderGeometry, DirectionalLight, ExtrudeGeometry, Group, HemisphereLight,
  Mesh, MeshStandardMaterial, PCFSoftShadowMap, PerspectiveCamera, PlaneGeometry, Raycaster, Scene, Shape,
  ShadowMaterial, Vector2, Vector3, WebGLRenderer,
} from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { useReducedMotion } from '../../app/useReducedMotion'
import { standardEase } from '../../motion/tween'
import type { MapMark, MapPlace } from './CanadaMap'
import type { Basemap } from './data'
import { type Point, centroid, lambert, projectedBox } from './projection'
import './relief.css'

const WORLD = 100
const BASE = 0.5
const RISE = 7
/** The lowest province still stands this share of RISE above the base, so no value reads as zero. */
const FLOOR = 0.12
/** Small Maritime provinces label out at sea, with a leader line: screen-pixel offsets. */
const LEADER: Record<string, [number, number]> = { NB: [-46, 44], PE: [4, -46], NS: [58, 34] }
/** Neighbouring prairie labels step apart so their names do not touch. */
const NUDGE: Record<string, [number, number]> = { SK: [-14, 8], MB: [16, -6] }
const FLY_MS = 900
const MIN_RING_AREA = 0.002

/** Read a colour token (`var(--seq-3)` or a token name) from :root, so the scene follows the theme. */
function tokenColor(value: string | null | undefined, fallback = 'diverging-mid'): Color {
  const name = /var\(--([\w-]+)\)/.exec(value ?? '')?.[1] ?? (value && !value.includes('(') ? value : fallback)
  const css = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim()
  return css ? new Color(css) : new Color(0.8, 0.8, 0.8)
}

function ringArea(ring: readonly Point[]): number {
  let area = 0
  for (let i = 0; i < ring.length - 1; i++) area += ring[i]![0] * ring[i + 1]![1] - ring[i + 1]![0] * ring[i]![1]
  return area / 2
}

/** Extrudable shapes for a polygon or multipolygon in world units; tiny islands are dropped. */
function shapes(geometry: Geometry, toWorld: (p: Position) => Point): Shape[] {
  if (geometry.type !== 'Polygon' && geometry.type !== 'MultiPolygon') return []
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates
  const out: Shape[] = []
  for (const rings of polygons) {
    const outer = rings[0]!.map(toWorld)
    if (Math.abs(ringArea(outer)) < MIN_RING_AREA * WORLD) continue
    const shape = new Shape(outer.map(([x, y]) => new Vector2(x, y)))
    for (const hole of rings.slice(1)) {
      const points = hole.map(toWorld)
      if (Math.abs(ringArea(points)) > MIN_RING_AREA) shape.holes.push(new Shape(points.map(([x, y]) => new Vector2(x, y))))
    }
    out.push(shape)
  }
  return out
}

interface ProvinceMesh { id: string; region: string | null; group: Group; top: MeshStandardMaterial; side: MeshStandardMaterial; height: number; target: number; centre: Point }
interface ColumnMesh { id: string; region: string; mesh: Mesh; material: MeshStandardMaterial; height: number; target: number; at: Point }

/**
 * Canada in relief: each province is extruded by its value (height is the measure, colour is
 * the comparison), lit softly from the north-west, with district columns rising out of the
 * chosen province. Drag to orbit, scroll to zoom. The flat map stays one click away and is
 * what keyboard, reduced-motion and no-WebGL readers get.
 */
/** The focused province's footprint (world units, south of 62°N) and its widest side. */
function focusBox(basemap: Basemap, region: string, project: (p: Position) => Point) {
  const box = projectedBox(basemap.provinces.filter((p) => p.properties.region_code === region).map((p) => p.geometry), project, ([, lat]) => lat! < 62)
  return box ? { box, span: Math.max(box[1][0] - box[0][0], box[1][1] - box[0][1], 8) } : null
}

export default function ReliefMap({ basemap, places, mark, width, height, focus, hot, onHot, onRegion, onMark, regionFill, regionHeight, regionNames, regionValue, tooltip, label }: {
  basemap: Basemap
  places: readonly MapPlace[]
  mark: (id: string) => (MapMark & { height: number | null }) | undefined
  width: number
  height: number
  focus: string | null
  hot: string | null
  onHot: (id: string | null) => void
  onRegion: (region: string | null) => void
  onMark: (id: string) => void
  /** Colour token (as `var(--…)`) for a region's top face. */
  regionFill: (region: string) => string | null
  /** 0–1 height for a region, or null when it has no value. */
  regionHeight: (region: string) => number | null
  regionNames: ReadonlyMap<string, string>
  regionValue: (region: string) => string | null
  tooltip: (id: string) => ReactNode
  label: string
}) {
  const reducedMotion = useReducedMotion()
  const host = useRef<HTMLDivElement>(null)
  const state = useRef<{
    renderer: WebGLRenderer; scene: Scene; camera: PerspectiveCamera; controls: OrbitControls
    provinces: ProvinceMesh[]; columns: ColumnMesh[]; frame: number; home: { target: Vector3; position: Vector3 }
    fly: { from: { t: Vector3; p: Vector3 }; to: { t: Vector3; p: Vector3 }; start: number } | null
    project: (p: Position) => Point
  } | null>(null)
  const [tip, setTip] = useState<{ x: number; y: number } | null>(null)
  const labelEls = useRef(new Map<string, HTMLSpanElement>())
  const leaderEls = useRef(new Map<string, SVGLineElement>())
  const callbacks = useRef({ onHot, onRegion, onMark, focus })
  callbacks.current = { onHot, onRegion, onMark, focus }

  // World coordinates: Statistics Canada Lambert, fitted to the south of 74°N, y pointing north.
  const projection = useMemo(() => {
    const unit = lambert()
    const box = projectedBox(basemap.provinces.map((p) => p.geometry), unit, ([, lat]) => lat! < 74)!
    const [[x0, y0], [x1, y1]] = box
    const k = WORLD / (x1 - x0)
    const cx = (x0 + x1) / 2
    const cy = (y0 + y1) / 2
    return (p: Position): Point => { const [x, y] = unit(p); return [(x - cx) * k, -(y - cy) * k] }
  }, [basemap])

  // Build the scene once per basemap; values update meshes in place below.
  useEffect(() => {
    const element = host.current
    if (!element) return
    const renderer = new WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = PCFSoftShadowMap
    element.appendChild(renderer.domElement)
    renderer.domElement.setAttribute('role', 'img')

    const scene = new Scene()
    const camera = new PerspectiveCamera(32, 1, 1, 1000)
    camera.up.set(0, 0, 1)
    const home = { target: new Vector3(4, -4, 0), position: new Vector3(4, -92, 112) }
    camera.position.copy(home.position)

    scene.add(new HemisphereLight(0xffffff, tokenColor('rule'), 1.1))
    scene.add(new AmbientLight(0xffffff, 0.25))
    const sun = new DirectionalLight(0xffffff, 1.6)
    sun.position.set(-60, 70, 120)
    sun.castShadow = true
    sun.shadow.mapSize.set(2048, 2048)
    Object.assign(sun.shadow.camera, { left: -70, right: 70, top: 60, bottom: -60, near: 1, far: 400 })
    sun.shadow.radius = 4
    scene.add(sun)
    const ground = new Mesh(new PlaneGeometry(400, 400), new ShadowMaterial({ opacity: 0.12 }))
    ground.position.z = -0.01
    ground.receiveShadow = true
    scene.add(ground)

    const provinces: ProvinceMesh[] = basemap.provinces.map((province) => {
      const group = new Group()
      const top = new MeshStandardMaterial({ roughness: 0.82, metalness: 0 })
      const side = new MeshStandardMaterial({ roughness: 0.9, metalness: 0 })
      for (const shape of shapes(province.geometry, projection)) {
        const geometry = new ExtrudeGeometry(shape, { depth: 1, bevelEnabled: false, curveSegments: 1 })
        const mesh = new Mesh(geometry, [top, side])
        mesh.castShadow = true
        mesh.receiveShadow = true
        mesh.userData = { kind: 'province', id: province.properties.province, region: province.properties.region_code }
        group.add(mesh)
      }
      group.scale.z = BASE
      scene.add(group)
      const middle = centroid(province.geometry, projection) ?? [0, 0]
      return { id: province.properties.province, region: province.properties.region_code, group, top, side, height: BASE, target: BASE, centre: middle }
    })

    const columns: ColumnMesh[] = places.flatMap((place) => {
      const at = centroid(place.geometry, projection)
      if (!at) return []
      const material = new MeshStandardMaterial({ roughness: 0.6, metalness: 0 })
      const mesh = new Mesh(new CylinderGeometry(1, 1, 1, 28), material)
      mesh.rotation.x = Math.PI / 2
      mesh.castShadow = true
      mesh.visible = false
      mesh.userData = { kind: 'district', id: place.id, region: place.region }
      scene.add(mesh)
      return [{ id: place.id, region: place.region, mesh, material, height: 0, target: 0, at }]
    })

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.target.copy(home.target)
    controls.enableDamping = true
    controls.dampingFactor = 0.08
    controls.minDistance = 10
    controls.maxDistance = 220
    controls.minPolarAngle = 0.15
    controls.maxPolarAngle = 1.15
    controls.minAzimuthAngle = -0.7
    controls.maxAzimuthAngle = 0.7
    controls.screenSpacePanning = true
    controls.update()

    state.current = { renderer, scene, camera, controls, provinces, columns, frame: 0, home, fly: null, project: projection }

    // Hover and click by ray: a drag that moved the camera is not a click.
    const ray = new Raycaster()
    const pointer = new Vector2()
    let down: { x: number; y: number } | null = null
    const pick = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect()
      pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1)
      ray.setFromCamera(pointer, camera)
      const meshes = [...columns.filter((c) => c.mesh.visible).map((c) => c.mesh), ...provinces.flatMap((p) => p.group.children)]
      const hit = ray.intersectObjects(meshes, false)[0]
      return { data: hit?.object.userData as { kind: string; id: string; region: string | null } | undefined, x: event.clientX - rect.left, y: event.clientY - rect.top }
    }
    const onMove = (event: PointerEvent) => {
      if (event.buttons) return
      const { data, x, y } = pick(event)
      const id = data ? (data.kind === 'district' ? data.id : data.region) : null
      callbacks.current.onHot(id ?? null)
      setTip(id ? { x, y } : null)
      renderer.domElement.style.cursor = id ? 'pointer' : 'grab'
    }
    const onDown = (event: PointerEvent) => { down = { x: event.clientX, y: event.clientY } }
    const onUp = (event: PointerEvent) => {
      if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 4) { down = null; return }
      down = null
      const { data } = pick(event)
      if (!data) return
      if (data.kind === 'district') callbacks.current.onMark(data.id)
      else if (data.region) callbacks.current.onRegion(data.region === callbacks.current.focus ? null : data.region)
    }
    const onLeave = () => { callbacks.current.onHot(null); setTip(null) }
    renderer.domElement.addEventListener('pointermove', onMove)
    renderer.domElement.addEventListener('pointerdown', onDown)
    renderer.domElement.addEventListener('pointerup', onUp)
    renderer.domElement.addEventListener('pointerleave', onLeave)

    const loop = (now: number) => {
      const s = state.current!
      if (s.fly) {
        const t = Math.min(1, (now - s.fly.start) / FLY_MS)
        const e = standardEase(t)
        s.controls.target.lerpVectors(s.fly.from.t, s.fly.to.t, e)
        s.camera.position.lerpVectors(s.fly.from.p, s.fly.to.p, e)
        if (t >= 1) s.fly = null
      }
      for (const p of s.provinces) {
        p.height += (p.target - p.height) * 0.14
        p.group.scale.z = p.height
      }
      for (const c of s.columns) {
        c.height += (c.target - c.height) * 0.14
        c.mesh.visible = c.height > 0.02
        c.mesh.scale.y = Math.max(0.01, c.height)
        const base = s.provinces.find((p) => p.region === c.region)?.height ?? BASE
        c.mesh.position.set(c.at[0], c.at[1], base + c.height / 2)
      }
      s.controls.update()
      s.renderer.render(s.scene, s.camera)
      // Labels follow their province's top face on screen, moved directly (no React render).
      const rect = s.renderer.domElement.getBoundingClientRect()
      for (const p of s.provinces) {
        const el = p.region ? labelEls.current.get(p.region) : undefined
        if (!el || p.region !== p.id) continue
        const v = new Vector3(p.centre[0], p.centre[1], p.height + 0.6).project(s.camera)
        const x = ((v.x + 1) / 2) * rect.width
        const y = ((1 - v.y) / 2) * rect.height
        const [dx, dy] = LEADER[p.region] ?? NUDGE[p.region] ?? [0, 0]
        el.style.transform = `translate(${x + dx}px, ${y + dy}px)`
        const line = leaderEls.current.get(p.region)
        if (line) Object.entries({ x1: x, y1: y, x2: x + dx * 0.78, y2: y + dy * 0.78 }).forEach(([k, n]) => line.setAttribute(k, String(n)))
      }
      s.frame = requestAnimationFrame(loop)
    }
    state.current.frame = requestAnimationFrame(loop)

    return () => {
      cancelAnimationFrame(state.current?.frame ?? 0)
      renderer.domElement.removeEventListener('pointermove', onMove)
      renderer.domElement.removeEventListener('pointerdown', onDown)
      renderer.domElement.removeEventListener('pointerup', onUp)
      renderer.domElement.removeEventListener('pointerleave', onLeave)
      controls.dispose()
      scene.traverse((object) => {
        if (object instanceof Mesh) {
          (object.geometry as BufferGeometry).dispose()
          const material = object.material
          for (const m of Array.isArray(material) ? material : [material]) m.dispose()
        }
      })
      renderer.dispose()
      renderer.domElement.remove()
      state.current = null
    }
  }, [basemap, places, projection])

  useEffect(() => {
    const s = state.current
    if (!s || !width || !height) return
    s.renderer.setSize(width, height)
    s.camera.aspect = width / height
    s.camera.updateProjectionMatrix()
    s.renderer.domElement.setAttribute('aria-label', label)
  }, [width, height, label])

  // Values, colours and the theme: update materials and target heights in place.
  const [scheme, setScheme] = useState(0)
  useEffect(() => {
    const bump = () => setScheme((n) => n + 1)
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    media.addEventListener('change', bump)
    const observer = new MutationObserver(bump)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => { media.removeEventListener('change', bump); observer.disconnect() }
  }, [])
  useEffect(() => {
    const s = state.current
    if (!s) return
    const ink = tokenColor('ink')
    for (const p of s.provinces) {
      const inFocus = !focus || p.region === focus
      const top = p.region ? tokenColor(regionFill(p.region)) : tokenColor('rule').lerp(tokenColor('paper'), 0.35)
      const value = p.region ? regionHeight(p.region) : null
      p.target = !p.region ? 0.15 : value === null ? BASE : BASE + (FLOOR + (1 - FLOOR) * value) * RISE
      // Inside a province the districts carry the values, so the province lies flat beneath them.
      if (focus) p.target = inFocus ? BASE : 0.15
      if (focus && !inFocus) top.lerp(tokenColor('paper'), 0.72)
      p.top.color.copy(top)
      p.side.color.copy(top.clone().lerp(ink, 0.22))
      const lit = p.region !== null && hot === p.region
      p.top.emissive.copy(lit ? tokenColor('ink') : new Color(0x000000))
      p.top.emissiveIntensity = lit ? 0.08 : 0
      if (reducedMotion) { p.height = p.target; p.group.scale.z = p.height }
    }
    const largest = Math.max(1, ...s.columns.map((c) => mark(c.id)?.size ?? 0))
    // Columns are sized to the province, so a small one and Ontario read alike.
    const span = (focus && focusBox(basemap, focus, s.project)?.span) || 20
    for (const c of s.columns) {
      const info = mark(c.id)
      const show = focus !== null && c.region === focus && info && !info.empty
      c.target = show ? span * (0.06 + 0.24 * (info.height ?? 0.5)) : 0
      const r = span * (0.018 + 0.032 * Math.sqrt((info?.size ?? 0) / largest))
      c.mesh.scale.x = r
      c.mesh.scale.z = r
      c.material.color.copy(tokenColor(info?.fill))
      c.material.emissive.copy(hot === c.id ? tokenColor('ink') : new Color(0x000000))
      c.material.emissiveIntensity = hot === c.id ? 0.12 : 0
      if (reducedMotion) c.height = c.target
    }
  }, [focus, hot, regionFill, regionHeight, mark, reducedMotion, scheme, basemap])

  // Fly to the chosen province, or back out to the country.
  useEffect(() => {
    const s = state.current
    if (!s) return
    const province = focus ? s.provinces.find((p) => p.region === focus) : null
    let to = { t: s.home.target.clone(), p: s.home.position.clone() }
    if (province) {
      const fit = focusBox(basemap, focus!, s.project)
      const [[x0, y0], [x1, y1]] = fit?.box ?? [[province.centre[0] - 5, province.centre[1] - 5], [province.centre[0] + 5, province.centre[1] + 5]]
      const span = fit?.span ?? 10
      const t = new Vector3((x0 + x1) / 2, (y0 + y1) / 2, BASE)
      to = { t, p: t.clone().add(new Vector3(0, -span * 1.3, span * 1.9)) }
    }
    if (reducedMotion) {
      s.controls.target.copy(to.t)
      s.camera.position.copy(to.p)
      return
    }
    s.fly = { from: { t: s.controls.target.clone(), p: s.camera.position.clone() }, to, start: performance.now() }
  }, [focus, basemap, reducedMotion])

  return <div className="relief" ref={host} style={{ width, height }}>
    <div className="relief-labels" aria-hidden="true">
      {!focus && <svg className="relief-leaders">{Object.keys(LEADER).filter((id) => regionNames.has(id)).map((id) =>
        <line key={id} ref={(el) => { if (el) leaderEls.current.set(id, el); else leaderEls.current.delete(id) }} />)}</svg>}
      {!focus && [...regionNames.keys()].map((id) => <span key={id} ref={(el) => { if (el) labelEls.current.set(id, el); else labelEls.current.delete(id) }}
        className={`relief-label${id in LEADER ? ' is-small' : ''}${hot === id ? ' is-hot' : ''}`}>
        <b>{id in LEADER ? id : regionNames.get(id)}</b>{regionValue(id) && <i>{regionValue(id)}</i>}
      </span>)}
    </div>
    {tip && hot && <div className="map-tooltip" style={{ left: Math.min(tip.x, width - 220), top: tip.y }}>{tooltip(hot)}</div>}
  </div>
}
