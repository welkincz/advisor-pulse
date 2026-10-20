// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { act } from 'react'
import { type Root, createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { CaseStudyPage, keyNumbers, slug, uniqueSlugs } from './CaseStudyPage'
import { parseBlocks } from './markdown'

declare global { var IS_REACT_ACT_ENVIRONMENT: boolean }
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const docs = resolve(import.meta.dirname, '../../../../docs')
const caseStudy = readFileSync(resolve(docs, 'case-study.md'), 'utf8')
const baseline = readFileSync(resolve(docs, 'baseline.md'), 'utf8')

let container: HTMLDivElement
let root: Root
beforeEach(() => {
  container = document.createElement('div')
  root = createRoot(container)
})
afterEach(() => act(() => root.unmount()))

it('renders the case study with its diagram, tables and links', async () => {
  await act(async () => root.render(<MemoryRouter><CaseStudyPage /></MemoryRouter>))
  expect(container.querySelector('h1')?.textContent).toBe('Case study')
  const headings = [...container.querySelectorAll('h2')].map((h) => h.textContent)
  expect(headings).toContain('Architecture')
  expect(headings).toContain('Data quality, with ground truth')
  expect(container.querySelector('figure.cs-diagram ol')?.children).toHaveLength(7)
  expect(container.querySelectorAll('table').length).toBeGreaterThanOrEqual(3)
  const links = [...container.querySelectorAll('a')].map((a) => a.getAttribute('href'))
  expect(links).toContain('/pipeline')
  expect(links).toContain('https://github.com/welkincz/advisor-pulse')
  expect(container.textContent).not.toMatch(/\blive\b|real-time dashboard/i)
})

it('takes every grouped figure from the baseline', () => {
  const figures = caseStudy.match(/\b\d{1,3}(?:,\d{3})+\b/g) ?? []
  expect(figures.length).toBeGreaterThan(5)
  for (const figure of figures) expect(baseline, figure).toContain(figure)
})

it('reads in about eight minutes or less', () => {
  const words = caseStudy.replace(/```[\s\S]*?```/g, '').split(/\s+/).filter(Boolean).length
  expect(words / 230).toBeLessThanOrEqual(8)
})

it('parses tables with right-aligned numeric columns', () => {
  const [table] = parseBlocks('| Defect | Injected |\n|---|---:|\n| Null id | 2,957 |\n')
  expect(table).toEqual({ kind: 'table', header: ['Defect', 'Injected'], align: ['left', 'right'], rows: [['Null id', '2,957']] })
})

it('lists every section in the contents with a working anchor, and leads with the scale numbers', async () => {
  await act(async () => root.render(<MemoryRouter><CaseStudyPage /></MemoryRouter>))
  const toc = [...container.querySelectorAll('.cs-toc a')].map((a) => a.getAttribute('href')!.slice(1))
  const ids = [...container.querySelectorAll('h2')].map((h) => h.id)
  expect(toc).toEqual(ids)
  expect(new Set(ids).size).toBe(ids.length)
  expect(slug('What the integration run caught')).toBe('what-the-integration-run-caught')
  const numbers = keyNumbers(parseBlocks(caseStudy))
  expect(numbers.length).toBe(4)
  expect(container.querySelectorAll('.cs-numbers > div')).toHaveLength(4)
})

it('keeps anchors unique and non-empty, and finds no numbers without the scale table', () => {
  expect(uniqueSlugs(['Results', 'Results', '***'])).toEqual(['results', 'results-2', 'section'])
  expect(keyNumbers(parseBlocks('# T\n\n## Scale and speed\n\nNo table here.\n'))).toEqual([])
  expect(keyNumbers(parseBlocks('## Upscale ideas\n\n| a | b |\n|---|--:|\n| x | 1 |\n'))).toEqual([])
})
