import { useEffect } from 'react'
import { BrowserRouter, Link, NavLink, Route, Routes, useParams } from 'react-router-dom'
import { useReducedMotion } from './useReducedMotion'

const navigation = [
  ['/', 'Overview'], ['/map', 'Map'], ['/pipeline', 'Pipeline'],
  ['/quality', 'Data quality'], ['/case-study', 'Case study'],
] as const

function Page({ title }: { title: string }) {
  return <main><p className="eyebrow">Maplecrest Bank · fictional</p><h1>{title}</h1><p className="intro">A weekly view of advisor activity, report quality, and pipeline status.</p></main>
}

function DrillPage({ title }: { title: string }) {
  const { region, district, branch, advisor } = useParams()
  const levels = [region, district, branch, advisor].filter(Boolean)
  return <main><p className="eyebrow">Maplecrest Bank · fictional</p><h1>{title}</h1><p className="intro">Weekly advisor activity for {levels.at(-1)}.</p><nav className="drill-trail" aria-label="Drill path">{levels.map((level, index) => <span key={index}>{index > 0 && ' / '}{level}</span>)}</nav></main>
}

function Shell() {
  const reducedMotion = useReducedMotion()
  useEffect(() => { document.documentElement.dataset.motion = reducedMotion ? 'reduced' : 'full' }, [reducedMotion])
  return <div className="site">
    <header className="site-header"><Link className="brand" to="/">Advisor Pulse</Link><nav className="site-nav" aria-label="Main navigation">{navigation.slice(1).map(([path, label]) => <NavLink key={path} to={path}>{label}</NavLink>)}</nav></header>
    <Routes>
      <Route path="/" element={<Page title="Overview" />} />
      <Route path="/r/:region" element={<DrillPage title="Region" />} />
      <Route path="/r/:region/d/:district" element={<DrillPage title="District" />} />
      <Route path="/r/:region/d/:district/b/:branch" element={<DrillPage title="Branch" />} />
      <Route path="/r/:region/d/:district/b/:branch/a/:advisor" element={<DrillPage title="Advisor" />} />
      <Route path="/map" element={<Page title="Map" />} />
      <Route path="/pipeline" element={<Page title="Pipeline" />} />
      <Route path="/quality" element={<Page title="Data quality" />} />
      <Route path="/case-study" element={<Page title="Case study" />} />
      <Route path="*" element={<Page title="Page not found" />} />
    </Routes>
    <footer className="site-footer">Weekly batch report · synthetic data · fictional bank</footer>
  </div>
}

export function App() { return <BrowserRouter><Shell /></BrowserRouter> }
