import { useMemo } from 'react'
import { DIVERGING, SEQUENTIAL, SERIES } from '../../theme/tokens'
import { Breadcrumb, Chart, Delta, Figure, Section, Sparkline, Stat, StatGroup, StatusMark } from '.'

/** Dev-only reference page (/_kitchen-sink): every primitive and palette, in the current scheme. */

const WEEKS = ['W33', 'W34', 'W35', 'W36', 'W37', 'W38', 'W39', 'W40']
const REGIONS = [
  { name: 'Ontario', values: [10.8, 11.2, 10.9, 11.6, 11.1, 10.4, 10.1, 10.4] },
  { name: 'Quebec', values: [12.1, 11.8, 12.4, 12.0, 12.6, 12.9, 12.2, 13.1] },
  { name: 'West', values: [9.6, 9.9, 10.3, 10.1, 10.6, 10.8, 11.0, 11.3] },
  { name: 'Atlantic', values: [11.4, 11.0, 10.7, 10.9, 10.2, 10.5, 10.0, 9.8] },
]

function Swatches({ names, label }: { names: readonly string[]; label: string }) {
  return <div className="ks-group"><h3>{label}</h3><div className="ks-swatches" role="list" aria-label={label}>
    {names.map((name) => <div key={name} role="listitem" className="ks-swatch">
      <span className="ks-chip" style={{ background: `var(--${name})` }} />
      <code>--{name}</code>
    </div>)}
  </div></div>
}

export default function KitchenSink() {
  const lines = useMemo(() => ({
    tooltip: { trigger: 'axis' },
    legend: { top: 0, left: 0 },
    // Direct end labels need their own gutter; the theme's containLabel only covers the axes.
    grid: { top: 36, right: 72 },
    xAxis: { type: 'category', data: WEEKS },
    yAxis: { type: 'value', min: 9 },
    series: REGIONS.map((r) => ({ type: 'line', name: r.name, data: r.values, endLabel: { show: true, formatter: '{a}' } })),
  }), [])
  const bars = useMemo(() => ({
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: ['GTA', 'EON', 'SWO', 'NON'] },
    yAxis: { type: 'value' },
    series: [{ type: 'bar', name: 'Appointments booked', data: [412, 268, 301, 122] }],
  }), [])

  return <main className="ks">
    <p className="eyebrow">Design system</p>
    <h1>Kitchen sink</h1>
    <p className="intro">Every primitive in the current colour scheme. Switch your system to dark mode to check the other one.</p>

    <div className="ks-trail"><Breadcrumb items={[{ label: 'National', to: '/' }, { label: 'Ontario', to: '/r/ON' }, { label: 'GTA', to: '/r/ON/d/GTA' }, { label: 'BR-0412' }]} /></div>

    <Section id="type" title="Type" lede="Avenir Next. One family; weight and size carry the hierarchy.">
      <div className="ks-type">
        <p style={{ fontSize: 'var(--text-display)', fontWeight: 600, letterSpacing: '-0.03em', lineHeight: 1.1, margin: 0 }}>Display 72</p>
        <p style={{ fontSize: 'var(--text-3xl)', margin: 0 }}>Figure 48 <span className="figure-num">1,284.6</span></p>
        <p style={{ fontSize: 'var(--text-2xl)', margin: 0 }}>Stat 36 <span className="figure-num">11.5</span></p>
        <h2>Section heading 24</h2>
        <p className="intro">Lead 21. Activities per advisor rose in Quebec for the third week running.</p>
        <p>Body 16. Weekly figures are computed from completed activities, attributed to the branch the advisor belonged to on the activity date.</p>
        <p style={{ fontSize: 'var(--text-xs)', color: 'var(--muted)' }}>Note 12. Source: weekly run of 5 Oct 2026, synthetic data.</p>
      </div>
    </Section>

    <Section id="colour" title="Colour" lede="Paper and ink do the work; signal gold marks the one thing to look at.">
      <Swatches label="Surfaces and ink" names={['paper', 'ink', 'muted', 'faint', 'rule', 'signal', 'focus']} />
      <Swatches label="Categorical" names={SERIES} />
      <Swatches label="Sequential" names={SEQUENTIAL} />
      <Swatches label="Diverging" names={DIVERGING} />
      <Swatches label="Status" names={['status-good', 'status-warning', 'status-critical', 'status-neutral', 'status-running']} />
    </Section>

    <Section id="stats" title="Stats" lede="Value first, then how it moved and the trend behind it.">
      <StatGroup label="National, week 2026-W40">
        <Stat label="Activities per advisor" value="11.5" emphasis>
          <Delta value={0.146} /><Sparkline values={[10.6, 10.9, 10.2, 10.8, 10.4, 10.1, 10.07, 11.54]} label="Activities per advisor, last 8 weeks: from 10.6 to 11.5" />
        </Stat>
        <Stat label="Show rate" value="84.4" unit="%"><Delta value={0.085} /></Stat>
        <Stat label="No-show rate" value="15.6" unit="%"><Delta value={-0.297} better="lower" /></Stat>
        <Stat label="Late-arriving rate" value="2.9" unit="%"><Delta value={3.738} better="lower" /></Stat>
        <Stat label="Average meeting minutes" value="54.9"><Delta value={-0.113} better="neither" /></Stat>
        <Stat label="Clients contacted" value="95"><Delta value={null} /></Stat>
      </StatGroup>
    </Section>

    <Section id="figures" title="Figures" lede="Every chart sits in a Figure with a reading, a source note and the numbers.">
      <Figure
        title="Activities per advisor by region"
        reading="Quebec leads; Atlantic has slipped for five of the last six weeks."
        note="Weekly runs 2026-W33 to W40. Synthetic data, fictional bank."
        table={<table><thead><tr><th>Region</th>{WEEKS.map((w) => <th key={w} className="num">{w}</th>)}</tr></thead>
          <tbody>{REGIONS.map((r) => <tr key={r.name}><th>{r.name}</th>{r.values.map((v, i) => <td key={i} className="num">{v.toFixed(1)}</td>)}</tr>)}</tbody></table>}
      >
        <Chart option={lines} label="Line chart of activities per advisor for four regions over eight weeks" height={280} />
      </Figure>
      <Figure title="Appointments booked, Ontario districts" note="Week 2026-W40.">
        <Chart option={bars} label="Bar chart of appointments booked in four Ontario districts" />
      </Figure>
    </Section>

    <Section id="status" title="Pipeline status" lede="A glyph and a word; colour is the third cue, never the only one.">
      <ul className="ks-status">
        {(['SUCCESS', 'WARN', 'FAILED', 'SKIPPED', 'RUNNING'] as const).map((s) => <li key={s}><StatusMark status={s} /></li>)}
      </ul>
    </Section>
  </main>
}
