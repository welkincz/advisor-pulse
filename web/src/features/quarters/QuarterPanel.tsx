import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Delta, Explain, Section, Term } from '../../components/primitives'
import type { Better } from '../../components/primitives/Delta'
import { DataNotice, KPI_LABELS, KPI_PLAIN, TERMS, formatKpi, useOrgQuarterly } from '../../data'
import { quarterLabel, quarterMonths } from '../../data/fiscal'
import type { KpiCode } from '../../data/generated/weekly_report'
import { QuarterChart } from './QuarterChart'
import { type Change, QUARTER_MEASURES, change, quarterSeries, toDate } from './quarters'
import './quarters.css'

function Versus({ result, better, against }: { result: Change; better: Better; against: string }) {
  if (result.value !== null) return <Delta value={result.value} better={better} against={against} />
  return <span className="delta delta-none">{result.reason === 'to-date' ? 'Compared once the quarter closes' : 'None yet'}</span>
}

/**
 * The fiscal-quarter view of one node: its quarters for the chosen measure, the chosen
 * quarter against the one before and the same quarter a year earlier, and its children for
 * that quarter. The fiscal year starts on 1 November. Hidden for exports without the mart.
 */
export function QuarterPanel({ nodeId, nodeName, code, better, childLabel, hrefFor, onOpen }: {
  nodeId: string
  nodeName: string
  code: KpiCode
  better: Better
  /** 'Regions', 'Districts' or 'Branches'; omitted for a node without children. */
  childLabel?: string
  hrefFor?: (childId: string) => string
  /** The drill page's shared title transition, so these links open a child the same way. */
  onOpen?: (event: React.MouseEvent<HTMLAnchorElement>, href: string) => void
}) {
  const result = useOrgQuarterly(nodeId)
  const rows = useMemo(() => (result.status === 'ready' ? result.data ?? [] : []), [result])
  const series = useMemo(() => quarterSeries(rows, nodeId, code), [rows, nodeId, code])
  const [chosen, setChosen] = useState<string | null>(null)
  const measure = QUARTER_MEASURES[code]

  // Empty: an export made before the quarterly mart, or one with no quarter in it yet.
  if (result.status === 'empty') return null
  const lede = <>The <Term title="Fiscal year" text="Starts on 1 November, as at Canadian banks, and is named for the year it ends in. A week counts in the quarter that holds its Sunday.">fiscal year</Term> starts on 1 November.</>
  if (result.status === 'error') return <Section id="quarters" title="Fiscal quarters" lede={lede}><DataNotice what="the fiscal quarters" onRetry={result.retry} /></Section>
  if (!measure) return <Section id="quarters" title="Fiscal quarters" lede={lede}>
    <p className="quarters-none">{KPI_LABELS[code]} is a batch measure, reported week by week for Canada only, so it has no quarterly figure. Choose another measure above.</p>
  </Section>

  const id = series.some((p) => p.id === chosen) ? chosen! : series.at(-1)?.id ?? null
  const point = series.find((p) => p.id === id)
  // A weekly average of a count keeps one decimal (92.5 a week), like the other averages.
  const fmt = (v: number | null | undefined) => (measure.basis === 'weekly' && v != null
    ? v.toLocaleString('en-CA', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
    : formatKpi(code, v))
  const unit = measure.basis === 'weekly' ? ' a week' : ''
  const children = rows.filter((r) => r.parent_id === nodeId && r.fiscal_quarter_id === id)
    .map((r) => {
      const own = quarterSeries(rows, r.node_id, code)
      return { id: r.node_id, name: r.node_name, value: measure.value(r), qoq: change(own, id!, code, 'qoq'), yoy: change(own, id!, code, 'yoy') }
    })
    .sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity))
  const basisNote = measure.basis === 'weekly'
    ? `${KPI_LABELS[code]} is shown as a weekly average over the weeks reported, so a quarter to date compares fairly with a whole one.`
    : measure.basis === 'quarter'
      ? 'Distinct clients are counted once over the whole quarter, so a quarter to date is compared only once it closes.'
      : `${KPI_LABELS[code]} is rebuilt from the quarter's own counts, not averaged from weekly rates.`

  return <Section id="quarters" title="Fiscal quarters" lede={lede}>
    {result.status === 'loading' || !point
      ? <div className="quarters-loading" aria-busy="true">{result.status === 'loading' ? 'Reading the fiscal quarters…' : 'No fiscal quarter has been reported yet.'}</div>
      : <figure className="figure quarters">
        <div className="quarters-head">
          <div>
            <h3 className="figure-title">{quarterLabel(point.id)}</h3>
            <p className="quarters-months">{quarterMonths(point.start, point.end)}{toDate(point) && <span className="quarters-to-date"><Term title={TERMS.toDate.title} text={TERMS.toDate.text}>To date</Term>: {toDate(point)}</span>}</p>
          </div>
          <p className="quarters-now">
            <Explain card={{ title: `${KPI_LABELS[code]}, ${quarterLabel(point.id)}`, value: `${fmt(point.value)}${unit}`, what: KPI_PLAIN[code], answer: { q: 'How is the quarter worked out?', a: basisNote } }}>
              {(described) => <span className="quarters-value figure-num term-quiet" tabIndex={0} {...described}>{fmt(point.value)}<small>{unit}</small></span>}
            </Explain>
            <span className="quarters-versus">
              <span>vs last quarter <Versus result={change(series, point.id, code, 'qoq')} better={better} against="last quarter" /></span>
              <span>vs a year earlier <Versus result={change(series, point.id, code, 'yoy')} better={better} against="the same quarter last year" /></span>
            </span>
          </p>
        </div>
        <QuarterChart points={series} selected={point.id} onSelect={setChosen} format={fmt}
          tickFormat={measure.basis === 'weekly' ? (v) => Math.round(v).toLocaleString('en-CA') : fmt}
          label={`${KPI_LABELS[code]}${unit}, ${nodeName}, by fiscal quarter from ${quarterLabel(series[0]!.id)} to ${quarterLabel(series.at(-1)!.id)}. Use the arrow keys to choose a quarter.`} />
        <figcaption className="figure-note">
          <details className="figure-table">
            <summary>Show the numbers</summary>
            <table><thead><tr><th scope="col">Quarter</th><th scope="col">Months</th><th scope="col" className="num">{KPI_LABELS[code]}{unit}</th><th scope="col" className="num">Weeks</th></tr></thead>
              <tbody>{[...series].reverse().map((p) => <tr key={p.id} aria-current={p.id === point.id ? 'true' : undefined}>
                <th scope="row">{quarterLabel(p.id)}</th><td>{quarterMonths(p.start, p.end)}</td><td className="num">{fmt(p.value)}</td>
                <td className="num">{p.complete ? p.weeksInQuarter : `${p.weeksReported} of ${p.weeksInQuarter}`}</td>
              </tr>)}</tbody></table>
          </details>
        </figcaption>
        {childLabel && children.length > 0 && <div className="quarters-children">
          <h3 className="figure-title">{childLabel} in {quarterLabel(point.id)}</h3>
          <div className="quarters-scroll" tabIndex={0} role="region" aria-label={`${childLabel} in ${quarterLabel(point.id)}, scrollable`}><table>
            <caption className="quarters-caption">{KPI_LABELS[code]}{unit} for {childLabel.toLowerCase()} in {nodeName}, {quarterLabel(point.id)}</caption>
            <thead><tr><th scope="col">{childLabel}</th><th scope="col" className="num">{KPI_LABELS[code]}{unit}</th><th scope="col" className="num">vs last quarter</th><th scope="col" className="num">vs a year earlier</th></tr></thead>
            <tbody>{children.map((c) => <tr key={c.id}>
              <th scope="row">{hrefFor ? <Link to={hrefFor(c.id)} onClick={onOpen && ((event) => onOpen(event, hrefFor(c.id)))}>{c.name}</Link> : c.name}</th>
              <td className="num figure-num">{fmt(c.value)}</td>
              <td className="num"><Versus result={c.qoq} better={better} against="last quarter" /></td>
              <td className="num"><Versus result={c.yoy} better={better} against="the same quarter last year" /></td>
            </tr>)}</tbody>
          </table></div>
        </div>}
      </figure>}
  </Section>
}
