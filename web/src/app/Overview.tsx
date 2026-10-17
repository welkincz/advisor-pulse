import { useEffect } from 'react'
import { DataNotice, KPI_LABELS, formatKpi, formatWow, useManifest, usePulseData } from '../data'

/** National KPIs from the manifest summary, so they paint before DuckDB-WASM loads. Tiles and trends come in #36. */
export function Overview() {
  const data = usePulseData()
  const manifest = useManifest()
  useEffect(() => {
    if (manifest.status !== 'ready') return
    const idle = window.requestIdleCallback ?? ((run: () => void) => window.setTimeout(run, 1))
    idle(() => data.warm())
  }, [data, manifest.status])

  return <main>
    <p className="eyebrow">Maplecrest Bank · fictional</p>
    <h1>Overview</h1>
    <p className="intro">A weekly view of advisor activity, report quality, and pipeline status.</p>
    {manifest.status === 'loading' && <p className="intro" aria-busy="true">Loading the latest weekly report…</p>}
    {manifest.status === 'error' && <DataNotice what="this week's report" onRetry={manifest.retry} />}
    {manifest.status === 'ready' && <section aria-labelledby="summary-heading">
      <h2 id="summary-heading">National, week {manifest.data.latest_week}</h2>
      <dl className="kpi-summary">
        {manifest.data.summary.map((kpi) => <div key={kpi.kpi_code} data-kpi={kpi.kpi_code}>
          <dt>{KPI_LABELS[kpi.kpi_code]}</dt>
          <dd>{formatKpi(kpi.kpi_code, kpi.value)} <span className="kpi-wow">{formatWow(kpi.wow_pct)}</span></dd>
        </div>)}
      </dl>
    </section>}
  </main>
}
