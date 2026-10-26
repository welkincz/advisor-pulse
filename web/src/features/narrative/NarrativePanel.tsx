import { useEffect, useRef, useState } from 'react'
import { Section } from '../../components/primitives/Section'
import { DataNotice, KPI_LABELS, formatKpi, formatWow, useManifest, useNarrative, usePulseData } from '../../data'
import type { NarrativeFact } from '../../data/generated/narrative'
import type { WeeklyReport } from '../../data/generated/weekly_report'
import { FIELDS, cited, currentFacts, figures } from './restatement'
import './narrative.css'

function CitedFacts({ ids, facts, current }: { ids: readonly string[]; facts: readonly NarrativeFact[]; current: Map<string, WeeklyReport> }) {
  const byId = new Map(facts.map((fact) => [fact.fact_id, fact]))
  return <details className="narrative-facts">
    <summary>View cited {ids.length === 1 ? 'fact' : 'facts'}</summary>
    <dl>
      {ids.map((id) => {
        const fact = byId.get(id)
        const prior = fact ? figures(fact) : []
        const latest = current.has(id) ? figures(current.get(id)!) : prior
        const now = (i: number) => prior[i] !== latest[i] && <span className="narrative-now" data-field={FIELDS[i]}>now {latest[i]}</span>
        return <div key={id} data-fact={id}>
          <dt>{fact ? KPI_LABELS[fact.kpi_code] : `Fact ${id} unavailable`}</dt>
          <dd>{fact && <>
            <span className="figure-num">{formatKpi(fact.kpi_code, fact.value)}</span>{now(0)}
            <span className="narrative-fact-context">{fact.node_id}, {fact.iso_week_id}</span>
            {(fact.prior_week_value != null || prior[1] !== latest[1]) && <><span className="narrative-fact-context">
              Prior week: {formatKpi(fact.kpi_code, fact.prior_week_value)}
            </span>{now(1)}</>}
            {(fact.wow_pct != null || prior[2] !== latest[2]) && <><span className="narrative-fact-context">{formatWow(fact.wow_pct)}</span>{now(2)}</>}
            {(fact.rank_in_parent != null || prior[3] !== latest[3]) && <><span className="narrative-fact-context">
              Rank {fact.rank_in_parent ?? '–'} of {fact.peer_count ?? '–'}
            </span>{now(3)}</>}
          </>}</dd>
        </div>
      })}
    </dl>
  </details>
}

/** A narrative for the selected node and reporting week. */
export function NarrativePanel({ week, nodeId }: { week: string; nodeId: string }) {
  const manifest = useManifest()
  const result = useNarrative(week, nodeId)
  const data = usePulseData()
  const n = result.status === 'ready' ? result.data : null
  const [attempt, retry] = useState(0)
  const [current, setCurrent] = useState<{ source: typeof n; rows?: Map<string, WeeklyReport>; error?: boolean }>({ source: null })
  useEffect(() => {
    let active = true
    setCurrent({ source: n })
    if (n) currentFacts(data, n).then(
      (rows) => active && setCurrent({ source: n, rows }),
      () => active && setCurrent({ source: n, error: true }),
    )
    return () => { active = false }
  }, [data, n, attempt])
  const appeared = useRef(false)
  const [firstView, setFirstView] = useState(true)
  useEffect(() => {
    if (result.status === 'ready') appeared.current = true
    else if (appeared.current) setFirstView(false)
  }, [result.status])
  if (result.status === 'loading') return <p aria-busy="true">Loading weekly narrative…</p>
  if (result.status === 'error') return <DataNotice what="the weekly narrative" onRetry={result.retry} />
  if (result.status === 'empty') {
    const published = manifest.status === 'ready' && manifest.data.files.some(
      (file) => file.name === `narratives/${week}.json`,
    )
    if (manifest.status !== 'ready' || published) return null
    return <Section id="weekly-narrative" title="Weekly interpretation" lede={`Week ${week}`}>
      <p>No narrative was published for {week}. The weekly figures remain available above.</p>
    </Section>
  }

  if (current.source !== n || (!current.rows && !current.error)) return <p aria-busy="true">Checking cited figures…</p>
  if (current.error) return <DataNotice what="the current cited figures" onRetry={() => retry((v) => v + 1)} />
  const rows = current.rows!
  const narrative = result.data
  const changed = new Set(cited(narrative).filter((f) => figures(f).some((text, i) => text !== figures(rows.get(f.fact_id)!)[i])).map((f) => f.fact_id))
  const restated = (ids: string[]) => ids.some((id) => changed.has(id))
  const marker = <span className="narrative-restated">Figures restated</span>
  return <Section id="weekly-narrative" title="Weekly interpretation" lede={`Week ${week}`} revealOrder={firstView ? 1 : undefined}>
    <div className="narrative-panel">
      <p className="narrative-disclosure">
        {narrative.model == null ? 'Template summary' : "AI-generated from this week's figures"}
      </p>
      <h3 className="narrative-headline">{narrative.headline}</h3>
      {changed.size > 0 && <p className="data-notice narrative-restatement" role="status" data-restated-count={changed.size}>
        Written by the {week} weekly run. Late-arriving activity has since changed {changed.size} of the figures it cites.
      </p>}
      <ul className="narrative-bullets">
        {narrative.bullets.map((bullet, index) => <li key={`${index}-${bullet.fact_ids.join('-')}`} data-restated={restated(bullet.fact_ids) || undefined}>
          <p>{bullet.text} {restated(bullet.fact_ids) && marker}</p>
          <CitedFacts ids={bullet.fact_ids} facts={narrative.facts_used} current={rows} />
        </li>)}
      </ul>
      {narrative.watchlist && narrative.watchlist.length > 0 && <div className="narrative-watchlist">
        <h4>Watchlist</h4>
        <ul>{narrative.watchlist.map((item) => <li key={`${item.node_id}-${item.reason}`} data-restated={restated(item.fact_ids) || undefined}>
          <strong>{item.node_id}</strong>: {item.reason} {restated(item.fact_ids) && marker}
          <CitedFacts ids={item.fact_ids} facts={narrative.facts_used} current={rows} />
        </li>)}</ul>
      </div>}
    </div>
  </Section>
}
