import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Bullet } from '../../components/charts/Bullet'
import { StackedWeeks } from '../../components/charts/StackedWeeks'
import { TrendChart } from '../../components/charts/TrendChart'
import { Section, Sparkline } from '../../components/primitives'
import { DataNotice, useDqWeekly, useRunLog } from '../../data'
import type { DqAction, DqWeekly } from '../../data/generated/dq_weekly'
import { formatShare, ingestSkip, qualitySentence, readCheck } from './checks'
import { FlagBacktest } from './FlagBacktest'
import { QualityMark } from './QualityMark'
import { RULES, RULES_URL } from './rules'
import './quality.css'

const percent = (rate: number | null | undefined, digits = 2) => (rate == null ? '–' : formatShare(rate, digits))

/**
 * The share of the batch, from the counts. The mart's `rate` is rounded to four places, which
 * turns a steady 0.19% into a line flicking between 0.19% and 0.20%.
 */
const share = (row: DqWeekly | undefined) => (row && row.rows_in_batch > 0 ? row.rows_affected / row.rows_in_batch : row?.rate ?? null)

/** How each rule handles a bad row, folded into the three outcomes a reader cares about. */
const HANDLING: readonly { key: string; label: string; color: string; actions: readonly DqAction[] }[] = [
  { key: 'quarantine', label: 'Quarantined', color: 'var(--series-1)', actions: ['QUARANTINE', 'FAIL_FILE'] },
  { key: 'dedupe', label: 'Removed as duplicates', color: 'var(--series-2)', actions: ['DEDUPE'] },
  { key: 'kept', label: 'Kept and mapped', color: 'var(--series-4)', actions: ['NORMALIZE', 'MAP_UNKNOWN', 'KEEP_FLAGGED'] },
]

function byRule(rows: readonly DqWeekly[]) {
  const out = new Map<string, Map<string, DqWeekly>>()
  for (const row of rows) {
    let weeks = out.get(row.rule_id)
    if (!weeks) out.set(row.rule_id, weeks = new Map())
    weeks.set(row.iso_week_id, row)
  }
  return out
}

export function QualityPage() {
  const [search, setSearch] = useSearchParams()
  const weekly = useDqWeekly()
  const runLog = useRunLog()
  const all = useMemo(() => (weekly.status === 'ready' ? weekly.data : []), [weekly])
  const weeks = useMemo(() => [...new Set(all.map((r) => r.iso_week_id))].sort(), [all])
  const rules = useMemo(() => byRule(all), [all])
  const measured = RULES.filter((rule) => rules.has(rule.id))
  const requested = search.get('rule')
  const selected = requested && rules.has(requested) ? requested : measured[0]?.id ?? 'DQ001'
  const lastWeek = weeks.at(-1)
  const latestRun = runLog.status === 'ready' ? runLog.data.runs.find((r) => r.run_type === 'WEEKLY') ?? runLog.data.runs[0] : undefined
  const alreadyLoaded = latestRun ? ingestSkip(latestRun)?.alreadyLoaded ?? false : false

  const stacks = useMemo(() => HANDLING.map((group) => ({
    key: group.key, label: group.label, color: group.color,
    values: weeks.map((w) => all.filter((r) => r.iso_week_id === w && group.actions.includes(r.action)).reduce((sum, r) => sum + r.rows_affected, 0)),
  })), [all, weeks])
  const series = weeks.map((w) => rules.get(selected)?.get(w))
  const rule = RULES.find((r) => r.id === selected)
  const choose = (id: string) => {
    const next = new URLSearchParams(search)
    next.set('rule', id)
    setSearch(next, { replace: true })
  }

  return <main className="quality">
    <h1>Data quality</h1>
    <p className="intro">{latestRun ? qualitySentence(latestRun) : 'Rule coverage, weekly defect rates and the checks from the last recorded run.'}</p>

    <Section id="quality-checks" title="This run's checks" lede={latestRun ? <>The {latestRun.run_type.toLowerCase()} run for {latestRun.iso_week_id}: <QualityMark status={latestRun.status} /></> : 'The checks the runner applies after every load.'}>
      {runLog.status === 'loading' && <p aria-busy="true">Loading run checks…</p>}
      {runLog.status === 'error' && <DataNotice what="the last run checks" onRetry={runLog.retry} />}
      {(runLog.status === 'empty' || (runLog.status === 'ready' && !latestRun)) && <p>No run is recorded.</p>}
      {latestRun && (latestRun.checks.length ? <ul className="checks">
        {latestRun.checks.map((check) => {
          const reading = readCheck(check, { alreadyLoaded })
          const status = check.status === 'PASS' ? 'SUCCESS' : check.status === 'FAIL' ? 'FAILED' : 'WARN'
          const unit = reading.bullet?.unit
          const format = (v: number) => (unit === '%' ? percent(v, v < 0.01 ? 2 : 0) : `${v} d`)
          return <li key={check.check_id} className="check" data-check={check.check_id}>
            <div className="check-head">
              <span className="check-title"><a href={RULES_URL}>{check.check_id}</a> {reading.title}</span>
              <QualityMark status={status} label={check.status === 'PASS' ? 'Passed' : check.status === 'FAIL' ? 'Failed' : 'Warning'} />
            </div>
            <p className="check-value figure-num">{reading.value}</p>
            {reading.bullet && <Bullet {...reading.bullet} format={format} label={`${reading.title}: ${reading.value}`} />}
            <p className="check-detail">{reading.detail}</p>
            <p className="check-severity">{check.severity === 'FAIL' ? 'Stops the run if it fails' : 'Warns without stopping the run'}</p>
          </li>
        })}
      </ul> : <p>No checks were recorded for this run.</p>)}
    </Section>

    <FlagBacktest />

    <Section id="quality-volume" title="Rows held back each week" lede="Every weekly batch, split by what the rules did with the rows they caught.">
      {weekly.status === 'loading' && <p aria-busy="true">Loading quality history…</p>}
      {weekly.status === 'error' && <DataNotice what="quality history" onRetry={weekly.retry} />}
      {weekly.status === 'empty' && <p>No weekly quality export is available.</p>}
      {weeks.length > 0 && <>
        <p className="stack-legend">{HANDLING.map((g) => <span key={g.key}><i style={{ background: g.color }} aria-hidden="true" />{g.label}</span>)}</p>
        <StackedWeeks weeks={weeks} series={stacks} label={`Rows caught by data quality rules per week, ${weeks[0]} to ${lastWeek}, split into quarantined, removed as duplicates, and kept and mapped`} />
        <details className="figure-table"><summary>Show the numbers</summary>
          <div className="quality-scroll quality-weeks" tabIndex={0} role="region" aria-label="Rows held back by week">
            <table><thead><tr><th scope="col">Week</th>{HANDLING.map((g) => <th key={g.key} scope="col" className="num">{g.label}</th>)}</tr></thead>
              <tbody>{[...weeks].reverse().map((w) => {
                const i = weeks.indexOf(w)
                return <tr key={w}><th scope="row">{w}</th>{stacks.map((st) => <td key={st.key} className="num">{st.values[i]!.toLocaleString('en-CA')}</td>)}</tr>
              })}</tbody></table>
          </div>
        </details>
      </>}
    </Section>

    <Section id="quality-rules" title="Rule by rule" lede={<>Rules measured every week, with the share of each batch they caught. Definitions follow <a href={RULES_URL}>PLAN.md §8</a>.</>}>
      {measured.length > 0 && <div className="rules">
        <ul className="rule-list" aria-label="Measured rules">
          {measured.map((r) => {
            const weeksOf = rules.get(r.id)!
            const latest = lastWeek ? weeksOf.get(lastWeek) : undefined
            return <li key={r.id}>
              <button type="button" aria-pressed={r.id === selected} onClick={() => choose(r.id)}>
                <span className="rule-id">{r.id}</span>
                <span className="rule-name">{r.description}</span>
                <span className="rule-rate figure-num">{percent(share(latest))}</span>
                <Sparkline values={weeks.slice(-26).map((w) => share(weeksOf.get(w)))} label={`${r.id} rate, last 26 weeks`} width={72} height={18} />
              </button>
            </li>
          })}
        </ul>
        <figure className="rule-detail">
          <figcaption>
            <h3>{selected} {rule?.description}</h3>
            <p>{rule?.action}. Latest: {percent(share(series.at(-1)))} of the batch, {series.at(-1)?.rows_affected.toLocaleString('en-CA') ?? '–'} rows.</p>
          </figcaption>
          <TrendChart weeks={weeks} values={series.map(share)} morphKey={selected} height={220}
            format={(v) => percent(v)} label={`${selected} weekly affected rate, ${weeks[0]} to ${lastWeek}`}
            tip={(i) => series[i] ? <span>{series[i]!.rows_affected.toLocaleString('en-CA')} of {series[i]!.rows_in_batch.toLocaleString('en-CA')} rows</span> : null} />
          <details className="figure-table"><summary>Show the numbers</summary>
            <table aria-label={`${selected} weekly values`}><thead><tr><th>Week</th><th className="num">Affected</th><th className="num">Batch</th><th className="num">Rate</th></tr></thead><tbody>
              {series.flatMap((row) => row ? [<tr key={row.iso_week_id}><th scope="row">{row.iso_week_id}</th><td className="num">{row.rows_affected.toLocaleString('en-CA')}</td><td className="num">{row.rows_in_batch.toLocaleString('en-CA')}</td><td className="num">{percent(share(row))}</td></tr>] : [])}
            </tbody></table>
          </details>
        </figure>
      </div>}
    </Section>

    <Section id="quality-index" title="Every rule" lede="All eighteen rules. Some are dbt tests or run checks, so they have no weekly rate; their result shows in the pipeline and in the checks above.">
      <div className="quality-scroll" tabIndex={0} role="region" aria-label="Data quality rule index, scrollable">
        <table className="quality-table" aria-label="Data quality rule index">
          <thead><tr><th>Rule</th><th>Check</th><th>Action</th><th className="num">{lastWeek ?? 'Latest'} rate</th></tr></thead>
          <tbody>{RULES.map((r) => {
            const row = lastWeek ? rules.get(r.id)?.get(lastWeek) : undefined
            return <tr key={r.id}><th scope="row"><a href={RULES_URL}>{r.id}</a></th><td>{r.description}</td><td>{r.action}</td>
              <td className="num">{row ? percent(share(row)) : <span className="quality-muted">{r.id >= 'DQ030' ? 'Run check' : r.id >= 'DQ020' ? 'dbt test' : 'Not weekly'}</span>}</td></tr>
          })}</tbody>
        </table>
      </div>
    </Section>
  </main>
}
