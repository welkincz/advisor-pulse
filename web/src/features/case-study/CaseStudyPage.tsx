import source from '../../../../docs/case-study.md?raw'
import { ArchitectureDiagram } from './ArchitectureDiagram'
import { type Block, Inline, parseBlocks } from './markdown'
import './case-study.css'

function render(block: Block, index: number) {
  switch (block.kind) {
    case 'heading': {
      const Tag = block.level <= 2 ? 'h2' : 'h3'
      return <Tag key={index}><Inline text={block.text} /></Tag>
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

/** The case study: docs/case-study.md rendered in the report's typography. */
export function CaseStudyPage() {
  const [title, ...blocks] = parseBlocks(source)
  return <main className="case-study">
    <p className="eyebrow">Maplecrest Bank · fictional</p>
    <h1>Case study</h1>
    {title?.kind === 'heading' && <p className="intro">{title.text}</p>}
    <article className="cs-body">{blocks.map(render)}</article>
  </main>
}
