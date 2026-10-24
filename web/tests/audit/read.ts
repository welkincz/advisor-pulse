/** Reading figures off a page, and the rules a figure must meet. */
import type { Locator, Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { KPI_LABELS, formatChange, formatKpi } from '../../src/data/kpi'
import type { KpiCode, WeeklyReport } from '../../src/data/generated/weekly_report'

/** Every disagreement found, written so the report alone says where to look. */
export class Ledger {
  readonly misses: string[] = []
  checked = 0
  /** `shown` must equal `expected`, character for character. */
  same(where: string, shown: string | null | undefined, expected: string) {
    this.checked++
    const text = (shown ?? '').replace(/\s+/g, ' ').trim()
    if (text !== expected) this.misses.push(`${where}: shows "${text}", the export says "${expected}"`)
  }
  fail(where: string, message: string) {
    this.checked++
    this.misses.push(`${where}: ${message}`)
  }
  ok(where: string, condition: boolean, message: string) {
    this.checked++
    if (!condition) this.misses.push(`${where}: ${message}`)
  }
}

/** The change as a delta, a table cell or a chart line shows it; "No prior week" without one. */
export const changeText = (share: number | null | undefined) => (share == null ? 'No prior week' : formatChange(share))

/**
 * wow_pct is stored unrounded, so it must equal value / prior_week_value − 1 up to floating
 * point: the change a reader recomputes is the change the site shows.
 */
export function wowTies(ledger: Ledger, where: string, row: Pick<WeeklyReport, 'value' | 'prior_week_value' | 'wow_pct'>) {
  const { value, prior_week_value: prior, wow_pct: wow } = row
  if (wow == null) return ledger.ok(where, value == null || prior == null || prior === 0, `has no change though value ${value} and prior ${prior} are both there`)
  if (value == null || prior == null || prior === 0) return ledger.fail(where, `shows a change of ${wow} with no prior week to compare`)
  const recomputed = value / prior - 1
  ledger.ok(where, Math.abs(wow - recomputed) <= 1e-9, `change ${wow} does not match ${value} / ${prior} − 1 = ${recomputed.toFixed(6)}`)
}

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const VALUE = '(–|[\\d,]+(?:\\.\\d+)?%?)'

/**
 * Check every "<measure> rose 3.4% to 10.4" / "held steady at" / "was" in a sentence the app
 * writes from the numbers. `label` maps a code to the name the page uses for it.
 */
export function checkSentence(ledger: Ledger, where: string, text: string, rowOf: (code: KpiCode) => { value: number | null | undefined; wow: number | null | undefined } | undefined, label: (code: KpiCode) => string = (c) => KPI_LABELS[c]) {
  const codes = Object.keys(KPI_LABELS) as KpiCode[]
  // Longest names first, so "Appointment conversion" is not read as part of another name.
  const names = codes.map((code) => [label(code), code] as const).sort((a, b) => b[0].length - a[0].length)
  const pattern = new RegExp(`(${names.map(([n]) => escape(n)).join('|')}) (?:(rose|fell) ([\\d.]+)% to ${VALUE}|held steady at ${VALUE}|was ${VALUE})`, 'g')
  let found = 0
  for (const match of text.matchAll(pattern)) {
    found++
    const code = names.find(([n]) => n === match[1])![1]
    const truth = rowOf(code)
    const at = `${where} · "${match[0]}"`
    if (!truth) { ledger.fail(at, 'names a measure the export has no row for'); continue }
    const value = (match[4] ?? match[5] ?? match[6] ?? '').replace(/[.,]$/, '')
    ledger.same(`${at} value`, value, formatKpi(code, truth.value))
    const wow = truth.wow
    if (match[2]) {
      ledger.ok(`${at} direction`, wow != null && (match[2] === 'rose') === (wow > 0), `says ${match[2]} but the change is ${wow}`)
      ledger.same(`${at} change`, `${match[3]}%`, wow == null ? 'none' : `${Math.abs(wow * 100).toFixed(1)}%`)
    } else if (match[5]) {
      ledger.ok(`${at} held`, wow != null && Math.abs(wow) < 0.005, `says held steady but the change is ${wow}`)
    } else {
      ledger.ok(`${at} no change`, wow == null, `gives no change but the export has ${wow}`)
    }
  }
  return found
}

/**
 * Hover a TrendChart at `week` and return its tooltip. The plot runs from 48 px in to 12 px
 * from the right edge; the first and last weeks are read off the tooltip, so the axis is learned
 * from the chart, not assumed.
 */
export async function hoverWeek(page: Page, svg: Locator, week: string, weeks: readonly string[]): Promise<Locator | null> {
  await svg.scrollIntoViewIfNeeded()
  const box = (await svg.boundingBox())!
  const y = box.y + box.height / 2
  const tip = page.locator('.trend-tip')
  const weekAt = async (x: number) => {
    await page.mouse.move(x, y)
    return tip.locator('[data-week]').getAttribute('data-week', { timeout: 5_000 })
  }
  const left = box.x + 48
  const right = box.x + box.width - 12
  const first = weeks.indexOf((await weekAt(left))!)
  const last = weeks.indexOf((await weekAt(right))!)
  const target = weeks.indexOf(week)
  if (first < 0 || last <= first || target < first || target > last) return null
  const shown = await weekAt(left + ((target - first) / (last - first)) * (right - left))
  return shown === week ? tip : null
}

/** RFC 4180 rows, header first; the BOM the download adds is dropped. */
export function parseCsv(path: string): Record<string, string>[] {
  const raw = readFileSync(path, 'utf8')
  const text = raw.charCodeAt(0) === 0xfeff ? raw.slice(1) : raw
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]!
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++ } else if (c === '"') quoted = false
      else cell += c
    } else if (c === '"') quoted = true
    else if (c === ',') { row.push(cell); cell = '' }
    else if (c === '\n') { row.push(cell.replace(/\r$/, '')); rows.push(row); row = []; cell = '' }
    else cell += c
  }
  const [header, ...body] = rows
  return body.map((r) => Object.fromEntries(header!.map((h, i) => [h, r[i] ?? ''])))
}

/** A CSV cell must be the export's number exactly: no rounding on the way out. */
export function sameNumber(ledger: Ledger, where: string, cell: string | undefined, value: number | null | undefined) {
  const expected = value == null ? '' : String(value)
  ledger.ok(where, (cell ?? '') === expected || (cell !== '' && value != null && Number(cell) === value), `holds "${cell}", the export has ${expected || 'nothing'}`)
}

/** The first number of each "What happened" line the shared card and chart tooltips write. */
export function checkHappened(ledger: Ledger, where: string, lines: readonly string[], code: KpiCode, row: WeeklyReport, settled: boolean) {
  const wow = row.wow_pct
  if (wow != null) {
    const expected = Math.abs(wow) < 0.0005 ? 'Level with last week.' : `${wow > 0 ? 'Up' : 'Down'} ${Math.abs(wow * 100).toFixed(1)}% on last week.`
    ledger.same(`${where} change line`, lines.find((l) => l.endsWith('last week.')), expected)
  }
  if (settled && row.trailing_13w_avg != null) {
    const usual = lines.find((l) => /usual \(/.test(l))
    ledger.same(`${where} usual`, /usual \(([^)]+)\)/.exec(usual ?? '')?.[1], formatKpi(code, row.trailing_13w_avg))
  }
}
