import { Fragment, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

/**
 * Block-level parse of the small Markdown subset docs/case-study.md uses: headings,
 * paragraphs, bullet and numbered lists, pipe tables and fenced blocks.
 */
export type Block =
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'list'; ordered: boolean; items: string[] }
  | { kind: 'table'; header: string[]; align: ('left' | 'right')[]; rows: string[][] }
  | { kind: 'fence'; lang: string; body: string }

const cells = (line: string) => line.trim().replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim())

export function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  const blocks: Block[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) { i++; continue }
    const fence = line.match(/^```(\w*)/)
    if (fence) {
      const body: string[] = []
      for (i++; i < lines.length && !lines[i].startsWith('```'); i++) body.push(lines[i])
      blocks.push({ kind: 'fence', lang: fence[1], body: body.join('\n') })
      i++
      continue
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/)
    if (heading) {
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2] })
      i++
      continue
    }
    if (line.startsWith('|')) {
      const header = cells(line)
      const align = cells(lines[i + 1] ?? '').map((cell) => (cell.endsWith(':') ? 'right' : 'left') as 'left' | 'right')
      const rows: string[][] = []
      for (i += 2; i < lines.length && lines[i].startsWith('|'); i++) rows.push(cells(lines[i]))
      blocks.push({ kind: 'table', header, align, rows })
      continue
    }
    const item = /^(?:- |\d+\. )/
    if (item.test(line)) {
      const ordered = /^\d/.test(line)
      const items: string[] = []
      for (; i < lines.length && item.test(lines[i]); i++) items.push(lines[i].replace(item, ''))
      blocks.push({ kind: 'list', ordered, items })
      continue
    }
    const text: string[] = []
    for (; i < lines.length && lines[i].trim() && !/^(#|\||```|- |\d+\. )/.test(lines[i]); i++) text.push(lines[i].trim())
    blocks.push({ kind: 'paragraph', text: text.join(' ') })
  }
  return blocks
}

/** Inline Markdown: **bold**, `code` and [links](href); internal links stay in the app. */
export function Inline({ text }: { text: string }) {
  const parts: ReactNode[] = []
  const pattern = /\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)/g
  let last = 0
  for (const match of text.matchAll(pattern)) {
    const at = match.index ?? 0
    if (at > last) parts.push(text.slice(last, at))
    const [, bold, code, label, href] = match
    if (bold !== undefined) parts.push(<strong key={at}><Inline text={bold} /></strong>)
    else if (code !== undefined) parts.push(<code key={at}>{code}</code>)
    else if (href.startsWith('/')) parts.push(<Link key={at} to={href}>{label}</Link>)
    else parts.push(<a key={at} href={href}>{label}</a>)
    last = at + match[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return <>{parts.map((part, index) => <Fragment key={index}>{part}</Fragment>)}</>
}
