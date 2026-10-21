import type { CSSProperties, ReactNode } from 'react'
import { AbsoluteFill, Easing, Sequence, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { loadFont } from '@remotion/google-fonts/NunitoSans'
import { type RecapProps, formatLike, pct } from './props'
import { COLORS } from './theme'

const { fontFamily } = loadFont('normal', { weights: ['400', '600', '700'], subsets: ['latin'] })

/** Scene lengths in frames at 30 fps; the whole recap runs about 23 seconds. */
export const SCENES = { title: 75, headline: 120, kpis: 150, regions: 180, flagged: 90, close: 75 } as const
export const RECAP_FRAMES = Object.values(SCENES).reduce((sum, n) => sum + n, 0)

const FADE = 10
const ease = Easing.bezier(0.2, 0, 0, 1)
const figures: CSSProperties = { fontVariantNumeric: 'tabular-nums lining-nums' }

/** A scene that fades in and out over its own length, so cuts never jump. */
function Scene({ children, length }: { children: ReactNode; length: number }) {
  const frame = useCurrentFrame()
  const opacity = interpolate(frame, [0, FADE, length - FADE, length], [0, 1, 1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  return <AbsoluteFill style={{ opacity, padding: '72px 96px', justifyContent: 'center' }}>{children}</AbsoluteFill>
}

/** Rises a few pixels into place, `delay` frames after its scene starts. */
function Rise({ delay = 0, children, style }: { delay?: number; children: ReactNode; style?: CSSProperties }) {
  const frame = useCurrentFrame()
  const t = interpolate(frame - delay, [0, 18], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease })
  return <div style={{ ...style, opacity: t, transform: `translateY(${(1 - t) * 14}px)` }}>{children}</div>
}

/** The site's anomaly ring: a circle that draws itself on (stroke-dashoffset, as on the trend charts). */
function Ring({ delay, size = 30 }: { delay: number; size?: number }) {
  const frame = useCurrentFrame()
  const drawn = interpolate(frame - delay, [0, 16], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease })
  const r = size / 2 - 2
  return <svg width={size} height={size} style={{ flex: 'none' }} aria-hidden="true">
    <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={COLORS.signal} strokeWidth={2} pathLength={1}
      strokeDasharray={1} strokeDashoffset={1 - drawn} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
    <circle cx={size / 2} cy={size / 2} r={3.5} fill={COLORS.signal} opacity={drawn} />
  </svg>
}

const kicker: CSSProperties = { fontSize: 22, color: COLORS.muted, fontWeight: 600 }

function Title({ week, dates }: Pick<RecapProps, 'week' | 'dates'>) {
  return <Scene length={SCENES.title}>
    <Rise><p style={{ ...kicker, color: COLORS.signal, margin: 0 }}>Advisor Pulse, the week in 20 seconds</p></Rise>
    <Rise delay={6}><h1 style={{ fontSize: 120, lineHeight: 1, margin: '16px 0 12px', fontWeight: 700, letterSpacing: -2 }}>Week {Number(week.slice(-2))}</h1></Rise>
    <Rise delay={12}><p style={{ fontSize: 30, margin: 0, color: COLORS.muted }}>{dates}</p></Rise>
    <Rise delay={18} style={{ position: 'absolute', bottom: 56, left: 96 }}><p style={{ fontSize: 18, margin: 0, color: COLORS.muted }}>Maplecrest Bank (fictional). Synthetic data from the weekly batch report.</p></Rise>
  </Scene>
}

function Headline({ headline, support }: Pick<RecapProps, 'headline' | 'support'>) {
  return <Scene length={SCENES.headline}>
    <Rise><p style={kicker}>Canada this week</p></Rise>
    <Rise delay={6}><h2 style={{ fontSize: 58, lineHeight: 1.12, margin: '12px 0 24px', fontWeight: 700, maxWidth: 1000, letterSpacing: -0.5 }}>{headline}</h2></Rise>
    <Rise delay={30}><p style={{ fontSize: 28, lineHeight: 1.4, margin: 0, color: COLORS.muted, maxWidth: 940 }}>{support}</p></Rise>
  </Scene>
}

function Kpis({ kpis }: Pick<RecapProps, 'kpis'>) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  return <Scene length={SCENES.kpis}>
    <Rise><p style={kicker}>Four measures, national</p></Rise>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '28px 56px', marginTop: 28 }}>
      {kpis.map((kpi, i) => {
        const delay = 8 + i * 8
        const t = spring({ frame: frame - delay, fps, config: { damping: 18, stiffness: 90 } })
        // Count up to the figure, then print it exactly as the site does.
        const shown = kpi.value == null ? '–' : t > 0.995 ? kpi.text : formatLike(kpi.code, kpi.value * Math.min(1, t))
        const good = kpi.wow == null || kpi.wow === 0 ? null : (kpi.wow > 0) === (kpi.better === 'higher')
        return <Rise key={kpi.code} delay={delay} style={{ borderTop: `2px solid ${COLORS.ink}`, paddingTop: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 22, fontWeight: 600 }}>
            {kpi.label}{kpi.flag && <><Ring delay={delay + 24} size={26} /><span style={{ color: COLORS.signal, fontSize: 18 }}>Anomaly</span></>}
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 18, marginTop: 6 }}>
            <span style={{ ...figures, fontSize: 64, fontWeight: 700, lineHeight: 1 }}>{shown}</span>
            {kpi.wow != null && <span style={{ ...figures, fontSize: 24, fontWeight: 600, color: good === null ? COLORS.muted : good ? COLORS['better-3'] : COLORS['worse-3'] }}>
              {kpi.wow > 0 ? '▲' : kpi.wow < 0 ? '▼' : ''} {pct(kpi.wow)} on last week
            </span>}
          </div>
        </Rise>
      })}
    </div>
  </Scene>
}

function Regions({ regions, rankedLabel }: Pick<RecapProps, 'regions' | 'rankedLabel'>) {
  const frame = useCurrentFrame()
  const { fps } = useVideoConfig()
  const reach = Math.max(0.01, ...regions.map((r) => Math.abs(r.away ?? 0)))
  const rowHeight = Math.min(44, 440 / Math.max(1, regions.length))
  return <Scene length={SCENES.regions}>
    <Rise><p style={kicker}>{rankedLabel}, each region against its usual week</p></Rise>
    <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr 110px', fontSize: 18, color: COLORS.muted, marginTop: 20 }}>
      <span /><span style={{ display: 'flex', justifyContent: 'space-between' }}><span>Worse than usual</span><span>Usual</span><span>Better than usual</span></span><span />
    </div>
    <div style={{ marginTop: 8 }}>
      {regions.map((region, i) => {
        // Bars settle with a spring, one row after another, best first.
        const grow = spring({ frame: frame - 14 - i * 4, fps, config: { damping: 14, stiffness: 110 } })
        const share = region.away == null ? 0 : Math.max(-1, Math.min(1, region.away / reach))
        const step = Math.min(3, Math.max(1, Math.ceil(Math.abs(share) * 3)))
        const color = region.away == null ? COLORS['diverging-mid'] : share >= 0 ? COLORS[`better-${step}` as 'better-1'] : COLORS[`worse-${step}` as 'worse-1']
        return <div key={region.id} style={{ display: 'grid', gridTemplateColumns: '300px 1fr 110px', alignItems: 'center', height: rowHeight, borderTop: `1px solid ${COLORS.rule}`, fontSize: 22 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 10, fontWeight: 600 }}>{region.name}{region.flag && <Ring delay={70 + i * 4} size={20} />}</span>
          <span style={{ position: 'relative', height: rowHeight * 0.42 }}>
            <i style={{ position: 'absolute', top: -6, bottom: -6, left: '50%', width: 1, background: COLORS.ink, opacity: 0.5 }} />
            <i style={{ position: 'absolute', top: 0, bottom: 0, background: color, borderRadius: share < 0 ? '4px 0 0 4px' : '0 4px 4px 0',
              ...(share < 0 ? { right: '50%' } : { left: '50%' }), width: `${Math.abs(share) * 50 * grow}%` }} />
          </span>
          <span style={{ ...figures, textAlign: 'right', color: COLORS.muted }}>{region.away == null ? '–' : pct(region.away)}</span>
        </div>
      })}
    </div>
  </Scene>
}

function Flagged({ flagged }: Pick<RecapProps, 'flagged'>) {
  return <Scene length={SCENES.flagged}>
    <Rise><p style={kicker}>{flagged.length ? 'Biggest anomalies in the regions' : 'Anomalies in the regions'}</p></Rise>
    {flagged.length === 0 && <Rise delay={8}><p style={{ fontSize: 44, fontWeight: 700 }}>No region was flagged this week.</p></Rise>}
    <div style={{ display: 'grid', gap: 26, marginTop: 24 }}>
      {flagged.map((item, i) => <Rise key={`${item.name}-${item.label}`} delay={8 + i * 10} style={{ display: 'flex', alignItems: 'center', gap: 22 }}>
        <Ring delay={14 + i * 10} size={44} />
        <span style={{ fontSize: 38, fontWeight: 700 }}>{item.name}</span>
        <span style={{ fontSize: 30, color: COLORS.muted }}>{item.label.toLowerCase()} {item.wow == null ? '' : `${pct(item.wow)} on last week`}</span>
      </Rise>)}
    </div>
  </Scene>
}

function Close({ summary }: Pick<RecapProps, 'summary'>) {
  return <Scene length={SCENES.close}>
    {summary && <Rise><p style={kicker}>From the run summary</p></Rise>}
    {summary && <Rise delay={6}><p style={{ fontSize: 40, lineHeight: 1.25, fontWeight: 600, margin: '12px 0 40px', maxWidth: 1000 }}>{summary}</p></Rise>}
    <Rise delay={summary ? 24 : 0}><p style={{ fontSize: 28, margin: 0, color: COLORS.muted }}>The full weekly report: <span style={{ color: COLORS.ink, fontWeight: 700 }}>pulse.charliebuild.com</span></p></Rise>
  </Scene>
}

export function Recap(props: RecapProps) {
  let at = 0
  const next = (length: number) => { const from = at; at += length; return { from, durationInFrames: length } }
  return <AbsoluteFill style={{ background: COLORS.paper, color: COLORS.ink, fontFamily }}>
    <Sequence {...next(SCENES.title)}><Title week={props.week} dates={props.dates} /></Sequence>
    <Sequence {...next(SCENES.headline)}><Headline headline={props.headline} support={props.support} /></Sequence>
    <Sequence {...next(SCENES.kpis)}><Kpis kpis={props.kpis} /></Sequence>
    <Sequence {...next(SCENES.regions)}><Regions regions={props.regions} rankedLabel={props.rankedLabel} /></Sequence>
    <Sequence {...next(SCENES.flagged)}><Flagged flagged={props.flagged} /></Sequence>
    <Sequence {...next(SCENES.close)}><Close summary={props.summary} /></Sequence>
  </AbsoluteFill>
}
