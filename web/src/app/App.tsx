import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import { DrillPage } from '../features/drill/DrillPage'
import { Overview } from './Overview'
import { CommandPalette } from './shell/CommandPalette'
import { Freshness } from './shell/Freshness'
import { SiteNav } from './shell/SiteNav'
import { ThemeToggle } from './shell/ThemeToggle'
import { useReducedMotion } from './useReducedMotion'
import './shell/shell.css'

// React Flow loads only with the pipeline page.
const PipelinePage = lazy(() => import('../features/pipeline/PipelinePage').then((m) => ({ default: m.PipelinePage })))
const MapPage = lazy(() => import('../features/map/MapPage').then((m) => ({ default: m.MapPage })))
const CaseStudyPage = lazy(() => import('../features/case-study/CaseStudyPage').then((m) => ({ default: m.CaseStudyPage })))
const QualityPage = lazy(() => import('../features/quality/QualityPage').then((m) => ({ default: m.QualityPage })))
// Dev-only reference page for the design system; tree-shaken out of production builds.
const KitchenSink = import.meta.env.DEV ? lazy(() => import('../components/primitives/KitchenSink')) : null

function Page({ title }: { title: string }) {
  return <main><h1>{title}</h1><p className="intro">There is no page at this address. <Link to="/">Open the weekly overview</Link>, or press / to search.</p></main>
}

function Shell() {
  const reducedMotion = useReducedMotion()
  useEffect(() => { document.documentElement.dataset.motion = reducedMotion ? 'reduced' : 'full' }, [reducedMotion])
  return <div className="site">
    <a className="skip-link" href="#main">Skip to the report</a>
    <header className="site-header">
      <Link className="brand" to="/" viewTransition>
        <span className="brand-name">Advisor Pulse</span>
        <span className="brand-for">Maplecrest Bank, fictional</span>
      </Link>
      <SiteNav />
      <div className="site-tools"><Freshness /><CommandPalette /><ThemeToggle /></div>
    </header>
    <div id="main" tabIndex={-1} className="site-main">
      <Routes>
        <Route path="/" element={<Overview />} />
        <Route path="/r/:region" element={<DrillPage />} />
        <Route path="/r/:region/d/:district" element={<DrillPage />} />
        <Route path="/r/:region/d/:district/b/:branch" element={<DrillPage />} />
        <Route path="/r/:region/d/:district/b/:branch/a/:advisor" element={<DrillPage />} />
        <Route path="/map" element={<Suspense fallback={<main aria-busy="true" />}><MapPage /></Suspense>} />
        <Route path="/pipeline" element={<Suspense fallback={<main aria-busy="true" />}><PipelinePage /></Suspense>} />
        <Route path="/quality" element={<Suspense fallback={<main aria-busy="true" />}><QualityPage /></Suspense>} />
        <Route path="/case-study" element={<Suspense fallback={<main aria-busy="true" />}><CaseStudyPage /></Suspense>} />
        {KitchenSink && <Route path="/_kitchen-sink" element={<Suspense fallback={null}><KitchenSink /></Suspense>} />}
        <Route path="*" element={<Page title="Page not found" />} />
      </Routes>
    </div>
    <footer className="site-footer">
      <p>A weekly batch report. Maplecrest Bank is fictional and every figure is synthetic, generated and checked by the pipeline this site reports on.</p>
      <p><Link to="/case-study">How it was built</Link> <a href="https://github.com/welkincz/advisor-pulse">Source on GitHub</a></p>
    </footer>
  </div>
}

export function App() { return <BrowserRouter><Shell /></BrowserRouter> }
