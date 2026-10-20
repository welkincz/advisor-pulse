import { useEffect, useState } from 'react'
import source from '../../../../docs/case-study.md?raw'
import { ArchitectureDiagram } from './ArchitectureDiagram'
import { type Block, Inline, parseBlocks } from './markdown'
import './case-study.css'

/** A stable anchor for a heading: "What the integration run caught" → "what-the-integration-run-caught". */
export function slug(text: string): string {
  return text.toLowerCase().replace(/[`*]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}

function render(block: Block, index: number) {
  switch (block.kind) {
    case 'heading': {
      const Tag = block.level <= 2 ? 'h2' : 'h3'
      return <Tag key={index} id={block.level <= 2 ? slug(block.text) : undefined}><Inline text={block.text} /></Tag>
    }
    case 'paragraph':
      return <p key={index}><Inline text={block.text} /></p>
    case 'list': {
      const Tag = block.ordered ? 'ol' : 'ul'
      return <Tag key={index}>{block.items.map((item, i) => <li key={i}><Inline text={item} /></li>)}</Tag>
    }
    case 'table':
      return <div key={index} className="cs-table-wrap" role="region" aria-label="Table" tabIndex={0}>
        <table className="cs-table">
          {block.header.some(Boolean) && <thead><tr>{block.header.map((cell, i) =>
            <th key={i} scope="col" className={block.align[i] === 'right' ? 'num' : undefined}><Inline text={cell} /></th>)}</tr></thead>}
          <tbody>{block.rows.map((row, r) => <tr key={r}>{row.map((cell, i) => i === 0 && block.align[0] === 'left'
            ? <th key={i} scope="row"><Inline text={cell} /></th>
            : <td key={i} className={block.align[i] === 'right' ? 'num' : undefined}><Inline text={cell} /></td>)}</tr>)}</tbody>
        </table>
      </div>
    case 'fence':
      return block.lang === 'mermaid' ? <ArchitectureDiagram key={index} /> : <pre key={index}><code>{block.body}</code></pre>
  }
}

/** The "Scale and speed" table's first rows, shown as a strip of numbers at the top. */
export function keyNumbers(blocks: readonly Block[], count = 4): { label: string; value: string }[] {
  const at = blocks.findIndex((b) => b.kind === 'heading' && /scale/i.test(b.text))
  const table = blocks.slice(at + 1).find((b) => b.kind === 'table')
  return at >= 0 && table?.kind === 'table' ? table.rows.slice(0, count).map(([label, value]) => ({ label: label ?? '', value: value ?? '' })) : []
}

/** The section in view, for the contents list. */
function useSectionInView(ids: readonly string[]): string | null {
  const [current, setCurrent] = useState<string | null>(null)
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
      if (visible) setCurrent(visible.target.id)
    }, { rootMargin: '0px 0px -70% 0px' })
    ids.forEach((id) => { const element = document.getElementById(id); if (element) observer.observe(element) })
    return () => observer.disconnect()
  }, [ids])
  return current
}

const [title, ...blocks] = parseBlocks(source)
const sections = blocks.flatMap((b) => (b.kind === 'heading' && b.level <= 2 ? [{ id: slug(b.text), text: b.text }] : []))
const sectionIds = sections.map((s) => s.id)
const numbers = keyNumbers(blocks)

/** The case study: docs/case-study.md rendered in the report's typography, with contents. */
export function CaseStudyPage() {
  const current = useSectionInView(sectionIds)
  return <main className="case-study">
    <h1>Case study</h1>
    {title?.kind === 'heading' && <p className="intro">{title.text}</p>}
    {numbers.length > 0 && <dl className="cs-numbers">{numbers.map((n) => <div key={n.label}><dt>{n.label}</dt><dd className="figure-num">{n.value.replace(/\s*\(.*\)$/, '')}{/\(.*\)$/.test(n.value) && <small>{/\((.*)\)$/.exec(n.value)![1]}</small>}</dd></div>)}</dl>}
    <div className="cs-layout">
      <nav className="cs-toc" aria-label="Contents">
        <p className="cs-toc-title">Contents</p>
        <ol>{sections.map((s) => <li key={s.id}><a href={`#${s.id}`} aria-current={s.id === current ? 'location' : undefined}><Inline text={s.text} /></a></li>)}</ol>
      </nav>
      <article className="cs-body">{blocks.map(render)}</article>
    </div>
  </main>
}
