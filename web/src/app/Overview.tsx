import { useEffect } from 'react'
import { DataNotice, useManifest, usePulseData } from '../data'
import { OrgLeaderboard } from '../features/leaderboard/Leaderboard'
import { OverviewKpis } from '../features/overview/OverviewKpis'
import { RunStatusBanner } from '../features/overview/RunStatusBanner'

/** National KPIs from the manifest summary paint before DuckDB-WASM loads. */
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
    {manifest.status === 'ready' && <RunStatusBanner manifest={manifest.data} />}
    {manifest.status === 'ready' && <OverviewKpis manifest={manifest.data} />}
    {manifest.status === 'ready' && <OrgLeaderboard weeks={manifest.data.weeks_available} parentId="CA" parentName="Canada" childHref={(id) => `/r/${encodeURIComponent(id)}`} />}
  </main>
}
