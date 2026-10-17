import { useState } from 'react'
import type { EChartsCoreOption } from 'echarts/core'
import { Chart, Figure, Section, Stat, StatGroup, StatusMark } from '../../components/primitives'
import { DataNotice, useDqWeekly, useRunLog } from '../../data'
import type { DqWeekly } from '../../data/generated/dq_weekly'
import { RULES, RULES_URL } from './rules'
import './quality.css'

function percent(rate: number | null | undefined): string {
  return rate == null ? '—' : `${(rate * 100).toFixed(2)}%`
}

function trendOption(rows: DqWeekly[]): EChartsCoreOption {
  return {
    aria: { enabled: false },
    grid: { left: 8, right: 20, top: 12, bottom: 20, containLabel: true },
    tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => typeof value === 'number' ? `${value.toFixed(2)}%` : '—' },
    xAxis: { type: 'category', data: rows.map((row) => row.iso_week_id), boundaryGap: false },
    yAxis: { type: 'value', min: 0, axisLabel: { formatter: '{value}%' } },
    series: [{ type: 'line', data: rows.map((row) => row.rate == null ? null : row.rate * 100), showSymbol: true }],
  }
}

export function QualityPage() {
  const [selected, setSelected] = useState<string>('DQ001')
  const weekly = useDqWeekly()
  const runLog = useRunLog()
  const allRows = weekly.status === 'ready' ? weekly.data : []
  const lastWeek = allRows.at(-1)?.iso_week_id
  const latestRows = new Map(allRows.filter((row) => row.iso_week_id === lastWeek).map((row) => [row.rule_id, row]))
  const trend = allRows.filter((row) => row.rule_id === selected)
  const first = trend[0]
  const last = trend.at(-1)
  const latestRun = runLog.status === 'ready' ? runLog.data.runs[0] : undefined

  return <main>
    <p className="eyebrow">Maplecrest Bank · fictional</p>
    <h1>Data quality</h1>
    <p className="intro">Rule coverage, weekly defect rates, and checks from the last recorded run. All data is synthetic.</p>

    <Section id="quality-summary" title="At a glance" lede="The rule index follows the documented definitions; trend coverage depends on exported rows.">
      <StatGroup label="Data quality summary">
        <Stat label="Documented rules" value={RULES.length} emphasis />
        <Stat label="Rules with weekly records" value={weekly.status === 'ready' ? new Set(allRows.map((row) => row.rule_id)).size : '—'} />
        <Stat label="Latest run checks" value={latestRun?.checks.length ?? '—'} />
      </StatGroup>
      {weekly.status === 'loading' && <p aria-busy="true">Loading quality history…</p>}
      {weekly.status === 'error' && <DataNotice what="quality history" onRetry={weekly.retry} />}
      {weekly.status === 'empty' && <p>No weekly quality export is available.</p>}
    </Section>

    <Section id="quality-trend" title="Weekly trend" lede="Select any rule. A missing row means no published measurement for that rule and week.">
      <label className="quality-picker">Trend rule
        <select value={selected} onChange={(event) => setSelected(event.target.value)}>
          {RULES.map((rule) => <option key={rule.id} value={rule.id}>{rule.id} · {rule.description}</option>)}
        </select>
      </label>
      {weekly.status === 'ready' && !trend.length && <p>No weekly trend data is published for {selected}.</p>}
      {first && last && <Figure title={`${selected} · weekly affected rate`}
        reading={`${percent(first.rate)} in ${first.iso_week_id} to ${percent(last.rate)} in ${last.iso_week_id}.`}
        note={<>Affected rate uses each row's recorded batch denominator. A dash means the rate was not reported.</>}
        table={<table aria-label={`${selected} weekly values`}><thead><tr><th>Week</th><th className="num">Affected</th><th className="num">Batch</th><th className="num">Rate</th></tr></thead><tbody>
          {trend.map((row) => <tr key={row.iso_week_id}><th scope="row">{row.iso_week_id}</th><td className="num">{row.rows_affected}</td><td className="num">{row.rows_in_batch}</td><td className="num">{percent(row.rate)}</td></tr>)}
        </tbody></table>}>
        <Chart option={trendOption(trend)} label={`${selected} weekly affected rate from ${first.iso_week_id} to ${last.iso_week_id}`} height={250} />
      </Figure>}
    </Section>

    <Section id="quality-rules" title="Rule index" lede={<>Definitions and actions follow <a href={RULES_URL}>PLAN.md §8</a>. Latest rates refer to the most recent exported week.</>}>
      <div className="quality-table-wrap">
        <p className="quality-scroll-hint">Scroll the table sideways for actions and rates.</p>
        <div className="quality-scroll" tabIndex={0} role="region" aria-label="Data quality rule index, scrollable">
          <table className="quality-table" aria-label="Data quality rule index">
            <thead><tr><th>Rule</th><th>Check</th><th>Action</th><th className="num">{lastWeek ?? 'Latest'} rate</th></tr></thead>
            <tbody>{RULES.map((rule) => {
              const row = latestRows.get(rule.id)
              return <tr key={rule.id}><th scope="row"><a href={RULES_URL}>{rule.id}</a></th><td>{rule.description}</td><td>{rule.action}</td><td className="num">{row ? percent(row.rate) : 'No row'}</td></tr>
            })}</tbody>
          </table>
        </div>
      </div>
    </Section>

    <Section id="quality-checks" title="Latest run checks" lede="Recorded check outcomes from run_log.json; these may refer to a different week than the latest quality export.">
      {runLog.status === 'loading' && <p aria-busy="true">Loading run checks…</p>}
      {runLog.status === 'error' && <DataNotice what="the last run checks" onRetry={runLog.retry} />}
      {(runLog.status === 'empty' || (runLog.status === 'ready' && !latestRun)) && <p>No run is recorded.</p>}
      {latestRun && <>
        <p className="quality-run">{latestRun.run_type.toLowerCase()} run · {latestRun.iso_week_id} · <StatusMark status={latestRun.status} /></p>
        {latestRun.checks.length ? <div className="quality-table-wrap"><p className="quality-scroll-hint">Scroll the table sideways for expected values and messages.</p><div className="quality-scroll" tabIndex={0} role="region" aria-label="Latest run checks, scrollable"><table className="quality-table" aria-label="Latest run checks">
          <thead><tr><th>Check</th><th>Result</th><th>Observed</th><th>Expected</th><th>Message</th></tr></thead>
          <tbody>{latestRun.checks.map((check) => <tr key={check.check_id}><th scope="row"><a href={RULES_URL}>{check.check_id}</a></th><td><StatusMark status={check.status === 'PASS' ? 'SUCCESS' : check.status === 'FAIL' ? 'FAILED' : 'WARN'} label={check.status} /></td><td className="num">{check.observed ?? '—'}</td><td>{check.expected ?? '—'}</td><td>{check.message ?? '—'}</td></tr>)}</tbody>
        </table></div></div> : <p>No checks were recorded for this run.</p>}
      </>}
    </Section>
  </main>
}
