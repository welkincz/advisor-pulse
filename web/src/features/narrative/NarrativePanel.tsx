import { useEffect, useRef, useState } from 'react'
import { Section } from '../../components/primitives/Section'
import { DataNotice, KPI_LABELS, formatKpi, formatWow, useManifest, useNarrative } from '../../data'
import type { NarrativeFact } from '../../data/generated/narrative'
import './narrative.css'

function CitedFacts({ ids, facts }: { ids: readonly string[]; facts: readonly NarrativeFact[] }) {
  const byId = new Map(facts.map((fact) => [fact.fact_id, fact]))
  return <details className="narrative-facts">
    <summary>View cited {ids.length === 1 ? 'fact' : 'facts'}</summary>
    <dl>
      {ids.map((id) => {
        const fact = byId.get(id)
        return <div key={id}>
          <dt>{fact ? KPI_LABELS[fact.kpi_code] : `Fact ${id} unavailable`}</dt>
          <dd>{fact && <>
            <span className="figure-num">{formatKpi(fact.kpi_code, fact.value)}</span>
            <span className="narrative-fact-context">{fact.node_id}, {fact.iso_week_id}</span>
            {fact.prior_week_value != null && <span className="narrative-fact-context">
              Prior week: {formatKpi(fact.kpi_code, fact.prior_week_value)}
            </span>}
            {fact.wow_pct != null && <span className="narrative-fact-context">{formatWow(fact.wow_pct)}</span>}
            {fact.rank_in_parent != null && fact.peer_count != null && <span className="narrative-fact-context">
              Rank {fact.rank_in_parent} of {fact.peer_count}
            </span>}
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

  const narrative = result.data
  return <Section id="weekly-narrative" title="Weekly interpretation" lede={`Week ${week}`} revealOrder={firstView ? 1 : undefined}>
    <div className="narrative-panel">
      <p className="narrative-disclosure">
        {narrative.fallback ? 'Template summary' : "AI-generated from this week's figures"}
      </p>
      <h3 className="narrative-headline">{narrative.headline}</h3>
      <ul className="narrative-bullets">
        {narrative.bullets.map((bullet, index) => <li key={`${index}-${bullet.fact_ids.join('-')}`}>
          <p>{bullet.text}</p>
          <CitedFacts ids={bullet.fact_ids} facts={narrative.facts_used} />
        </li>)}
      </ul>
      {narrative.watchlist && narrative.watchlist.length > 0 && <div className="narrative-watchlist">
        <h4>Watchlist</h4>
        <ul>{narrative.watchlist.map((item) => <li key={`${item.node_id}-${item.reason}`}>
          <strong>{item.node_id}</strong>: {item.reason}
        </li>)}</ul>
      </div>}
    </div>
  </Section>
}
