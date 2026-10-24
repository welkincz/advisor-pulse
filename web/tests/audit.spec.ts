/**
 * The forensic audit (docs/design.md, "Every number agrees"): for one week and one node per
 * level, read every figure each page shows for every measure (sentence, KPI card, chart
 * tooltip, "Show the numbers", the downloaded CSV, the map's list and tooltip, the narrative's
 * cited facts, the data quality page) and check each against the export, formatted with the
 * app's own formatters. Fixtures by default; `make web-audit-latest` runs it on the full export.
 */
import { type Locator, type Page, expect, test } from '@playwright/test'
import { resolve } from 'node:path'
import { KPI_LABELS, formatKpi, formatWow } from '../src/data/kpi'
import type { KpiCode } from '../src/data/generated/weekly_report'
import { ADVISOR_KPIS, ORG_KPIS, advisorValue } from '../src/features/leaderboard/rows'
import { KPI_CODES } from '../src/features/overview/kpis'
import { formatShare } from '../src/features/quality/checks'
import { Ledger, changeText, checkHappened, checkSentence, hoverWeek, parseCsv, sameNumber, wowTies } from './audit/read'
import { EXPORTS, type Truth, loadTruth } from './audit/truth'

const NATIONAL_ONLY = new Set<KpiCode>(['LATE_RATE', 'QUAR_RATE'])
const VALUE_LINE = /^[^:]+: (–|[\d,]+(?:\.\d+)?%?)\.$/

let truth: Truth
test.beforeAll(async () => { truth = await loadTruth() })
test.beforeEach(async ({ page }) => {
  await page.route('http://127.0.0.1:43719/data/**', (route) => {
    const file = new URL(route.request().url()).pathname.split('/data/')[1]!
    return route.fulfill({ path: resolve(EXPORTS, decodeURIComponent(file)) })
  })
  // Reduced motion: values are final at once (no tweens) and the map is the flat SVG one.
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 1280, height: 900 })
})

const weeks = () => truth.manifest.weeks_available
const settled = (week: string) => weeks().indexOf(week) >= 13
const query = (extra = '') => `?week=${truth.week}${extra}`

/** A figure that fills in once its data loads: give it time to reach `expected`, then read what it shows. */
async function loaded(figure: Locator, expected: string): Promise<string | null> {
  await expect(figure).toHaveText(expected, { timeout: 30_000 }).catch(() => undefined)
  return figure.textContent()
}

/** A Delta's text: its signed figure, or "No prior week". */
async function delta(scope: Locator): Promise<string> {
  const figure = scope.locator('.delta .figure-num')
  return ((await figure.count()) ? await figure.first().textContent() : await scope.locator('.delta').first().textContent()) ?? ''
}

/** The headline row of a node in the audited week, as a sentence reads it. */
const moveOf = (node: string) => (code: KpiCode) => {
  const row = truth.row(node, code)
  return row && { value: row.value, wow: row.wow_pct }
}

/** The chosen measure's hero: value and change, chart tooltip, "Show the numbers" and the CSV. */
async function auditHero(page: Page, ledger: Ledger, where: string, node: string, code: KpiCode, parent?: string) {
  const row = truth.row(node, code)!
  const hero = page.locator('section.hero')
  ledger.same(`${where} hero value`, await hero.locator('.hero-value').textContent(), formatKpi(code, row.value))
  ledger.same(`${where} hero change`, await delta(hero.locator('.hero-now')), changeText(row.wow_pct))
  wowTies(ledger, `${where} export row`, row)

  const tip = await hoverWeek(page, hero.locator('svg.trend-svg'), truth.week, weeks())
  if (!tip) ledger.fail(`${where} chart`, `no tooltip for ${truth.week}`)
  else {
    ledger.same(`${where} chart tooltip value`, await tip.locator('strong').textContent(), formatKpi(code, row.value))
    const lines = await tip.locator('.trend-tip-line').allTextContents()
    checkHappened(ledger, `${where} chart tooltip`, lines, code, row, settled(truth.week))
    const parentRow = parent ? truth.row(parent, code) : undefined
    if (parentRow?.value != null && row.value != null) ledger.same(`${where} chart tooltip parent`, VALUE_LINE.exec(lines.at(-1) ?? '')?.[1], formatKpi(code, parentRow.value))
  }
  await page.mouse.move(0, 0)

  const table = hero.locator('details.hero-table')
  if (!(await table.getAttribute('open'))) await table.locator('summary').click()
  const cells = table.locator(`tr[data-week="${truth.week}"] td`)
  ledger.same(`${where} table value`, await cells.nth(0).textContent(), formatKpi(code, row.value))
  ledger.same(`${where} table usual`, await cells.nth(1).textContent(), settled(truth.week) ? formatKpi(code, row.trailing_13w_avg) : '–')
  ledger.same(`${where} table change`, await cells.nth(2).textContent(), row.wow_pct == null ? '–' : changeText(row.wow_pct))

  const [download] = await Promise.all([page.waitForEvent('download'), hero.locator('.csv-button').click()])
  const csv = parseCsv((await download.path())!).find((r) => r.iso_week_id === truth.week)
  if (!csv) return ledger.fail(`${where} CSV`, `has no row for ${truth.week}`)
  for (const field of ['value', 'prior_week_value', 'wow_pct', 'trailing_13w_avg'] as const) sameNumber(ledger, `${where} CSV ${field}`, csv[field], row[field])
  ledger.same(`${where} CSV node`, csv.node_id, node)
  ledger.same(`${where} CSV measure`, csv.kpi_code, code)
}

/** Child rows that show a value and a change: region multiples, child multiples, What moved. */
async function auditChildren(ledger: Ledger, where: string, items: Locator, valueSelector: string, code: KpiCode) {
  for (const item of await items.all()) {
    const node = (await item.getAttribute('data-node'))!
    const row = truth.row(node, code)
    ledger.same(`${where} ${node} value`, await item.locator(valueSelector).first().textContent(), formatKpi(code, row?.value))
    ledger.same(`${where} ${node} change`, await delta(item), changeText(row?.wow_pct))
  }
}

async function chooseOnBoard(page: Page, code: KpiCode, title: string) {
  const button = page.locator(`[data-kpi="${code}"] button`)
  if ((await button.getAttribute('aria-pressed')) !== 'true') await button.click()
  await expect(page.locator(title)).toHaveText(KPI_LABELS[code])
}

/** The narrative's cited facts: each is a row of the report, written as the report writes it. */
async function auditNarrative(page: Page, ledger: Ledger, where: string, node: string) {
  const narrative = truth.narrative(node)
  if (!narrative) return
  const panel = page.locator('.narrative-panel')
  await expect(panel).toBeVisible({ timeout: 30_000 })
  for (const summary of await panel.locator('details.narrative-facts summary').all()) await summary.click()
  const facts = new Map(narrative.facts_used.map((f) => [f.fact_id, f]))
  for (const item of await panel.locator('[data-fact]').all()) {
    const id = (await item.getAttribute('data-fact'))!
    const fact = facts.get(id)
    const at = `${where} narrative fact ${id}`
    if (!fact) { ledger.fail(at, 'is cited but not among the facts used'); continue }
    const row = truth.row(fact.node_id, fact.kpi_code, fact.iso_week_id)
    if (!row) { ledger.fail(at, `${fact.node_id} ${fact.kpi_code} ${fact.iso_week_id} is not in the report`); continue }
    // Facts are rounded to four places on the way to the model; the report keeps more.
    for (const field of ['value', 'prior_week_value', 'wow_pct'] as const) {
      const a = fact[field] ?? null
      const b = row[field] ?? null
      ledger.ok(`${at} ${field}`, a === b || (a != null && b != null && Math.abs(a - b) <= 0.00005 + 1e-9), `cites ${a}, the report has ${b}`)
    }
    ledger.same(`${at} value`, await item.locator('dd .figure-num').textContent(), formatKpi(fact.kpi_code, row.value))
    const context = await item.locator('.narrative-fact-context').allTextContents()
    ledger.same(`${at} node and week`, context[0], `${fact.node_id}, ${fact.iso_week_id}`)
    if (row.prior_week_value != null) ledger.same(`${at} prior week`, context.find((t) => t.startsWith('Prior week')), `Prior week: ${formatKpi(fact.kpi_code, row.prior_week_value)}`)
    if (row.wow_pct != null) ledger.same(`${at} change`, context.find((t) => t.endsWith('WoW')), formatWow(row.wow_pct))
    if (fact.rank_in_parent != null && fact.peer_count != null) ledger.same(`${at} rank`, context.find((t) => t.startsWith('Rank')), `Rank ${row.rank_in_parent} of ${row.peer_count}`)
  }
}

/** A leaderboard row per child, in the measure the board ranks by. */
async function auditLeaderboard(page: Page, ledger: Ledger, where: string, valueOf: (node: string, code: KpiCode) => { value: number | null; rank?: number | null }) {
  const board = page.locator('section[aria-labelledby="leaderboard-title"]')
  await expect(board.locator('tr[data-node]').first()).toBeVisible({ timeout: 30_000 })
  const code = (await board.locator('select').inputValue()) as KpiCode
  for (const tr of await board.locator('tr[data-node]').all()) {
    const node = (await tr.getAttribute('data-node'))!
    const truthRow = valueOf(node, code)
    ledger.same(`${where} leaderboard ${node} value`, await tr.locator('td').nth(2).textContent(), formatKpi(code, truthRow.value))
    if (truthRow.rank !== undefined) ledger.same(`${where} leaderboard ${node} rank`, await tr.locator('td').nth(0).textContent(), String(truthRow.rank ?? '–'))
  }
}

test('every figure agrees with the export on every page', async ({ page }) => {
  test.setTimeout(process.env.PULSE_AUDIT_EXPORTS ? 900_000 : 240_000)
  const ledger = new Ledger()
  const { region, district, branch, advisor } = truth.path
  const week = truth.week

  await test.step('overview', async () => {
    await page.goto(`/${query()}`)
    await expect(page.locator('h1')).not.toHaveText(/^The weekly report for/, { timeout: 60_000 })
    const sentence = `${await page.locator('h1').textContent()} ${await page.locator('.briefing-support').textContent()}`
    ledger.ok('overview headline', checkSentence(ledger, 'overview headline', sentence, moveOf('CA')) > 0, `reads no figure: "${sentence}"`)
    const codes = KPI_CODES.filter((code) => truth.row('CA', code)?.value != null)
    for (const code of codes) {
      const row = truth.row('CA', code)!
      const card = page.locator(`[data-kpi="${code}"]`)
      ledger.same(`overview card ${code} value`, await card.locator('.board-value').textContent(), formatKpi(code, row.value))
      ledger.same(`overview card ${code} change`, await delta(card.locator('.board-delta')), changeText(row.wow_pct))
    }
    for (const step of await page.locator('.funnel-step[data-step]').all()) {
      const code = (await step.getAttribute('data-step')) as KpiCode
      ledger.same(`overview funnel ${code}`, await step.locator('.funnel-step-rate').textContent(), formatKpi(code, truth.row('CA', code)?.value))
      ledger.same(`overview funnel ${code} change`, await delta(step), changeText(truth.row('CA', code)?.wow_pct))
    }
    const counts = await page.locator('.funnel-count').allTextContents()
    if (counts.length) {
      ledger.same('overview funnel calls', counts[0]!.replace('?', ''), formatKpi('CALLS_OUT', truth.row('CA', 'CALLS_OUT')?.value))
      ledger.same('overview funnel booked', counts[1]!.replace('?', ''), formatKpi('APPT_BOOKED', truth.row('CA', 'APPT_BOOKED')?.value))
    }
    for (const code of codes) {
      await chooseOnBoard(page, code, '#hero-title .term')
      await auditHero(page, ledger, `overview ${code}`, 'CA', code)
      if (NATIONAL_ONLY.has(code)) continue
      await expect(page.locator('.moved-row').first()).toBeVisible({ timeout: 30_000 })
      await auditChildren(ledger, `overview what moved ${code}`, page.locator('.moved-row[data-node]'), '.moved-value', code)
      for (const item of await page.locator('.moved-row[data-node]').all()) {
        const row = truth.row((await item.getAttribute('data-node'))!, code)
        const away = settled(week) && row?.value != null && row.trailing_13w_avg ? row.value / row.trailing_13w_avg - 1 : null
        ledger.same(`overview what moved ${code} vs usual`, (await item.locator('.moved-away').textContent())?.replace(' vs usual', ''), away === null ? '–' : changeText(away))
      }
      await auditChildren(ledger, `overview by region ${code}`, page.locator('.multiples:not(.child-multiples) > li[data-node]'), '.multiple-value', code)
    }
  })

  const orgPages = [
    { level: 'region', node: region, parent: 'CA', url: `/r/${region}` },
    { level: 'district', node: district, parent: region, url: `/r/${region}/d/${district}` },
    { level: 'branch', node: branch, parent: district, url: `/r/${region}/d/${district}/b/${branch}` },
  ]
  for (const { level, node, parent, url } of orgPages) {
    await test.step(`${level} ${node}`, async () => {
      const where = `${level} ${node}`
      await page.goto(`${url}${query()}`)
      const lede = page.locator('.drill-lede')
      await expect(lede).not.toHaveText(/^$|Reading/, { timeout: 60_000 })
      ledger.ok(`${where} sentence`, checkSentence(ledger, `${where} sentence`, (await lede.textContent()) ?? '', moveOf(node)) > 0, 'reads no figure')
      const codes = ORG_KPIS.filter((code) => truth.row(node, code)?.value != null)
      for (const code of codes) {
        const card = page.locator(`[data-kpi="${code}"]`)
        ledger.same(`${where} card ${code} value`, await card.locator('.board-value').textContent(), formatKpi(code, truth.row(node, code)!.value))
        ledger.same(`${where} card ${code} change`, await delta(card.locator('.board-delta')), changeText(truth.row(node, code)!.wow_pct))
      }
      for (const code of codes) {
        await chooseOnBoard(page, code, '#drill-hero-title .term')
        await auditHero(page, ledger, `${where} ${code}`, node, code, parent)
        if (level !== 'branch') {
          await expect(page.locator('.child-multiples li').first()).toBeVisible({ timeout: 30_000 })
          await auditChildren(ledger, `${where} children ${code}`, page.locator('.child-multiples > li[data-node]'), '.multiple-value', code)
        }
      }
      await auditNarrative(page, ledger, where, node)
      if (level === 'branch') {
        await auditLeaderboard(page, ledger, where, (id, code) => {
          const row = truth.advisors(node, week).find((a) => a.advisor_id === id)
          return { value: row ? advisorValue(code, row) : null }
        })
      } else {
        await auditLeaderboard(page, ledger, where, (id, code) => {
          const row = truth.row(id, code)
          return { value: row?.value ?? null, rank: row?.rank_in_parent ?? null }
        })
      }
    })
  }

  await test.step(`advisor ${advisor}`, async () => {
    const where = `advisor ${advisor}`
    await page.goto(`/r/${region}/d/${district}/b/${branch}/a/${advisor}${query()}`)
    const lede = page.locator('.drill-lede')
    await expect(lede).not.toHaveText(/^$|Reading/, { timeout: 60_000 })
    const prior = weeks()[weeks().indexOf(week) - 1]
    const now = truth.advisors(branch, week).find((a) => a.advisor_id === advisor)!
    const before = prior ? truth.advisors(branch, prior).find((a) => a.advisor_id === advisor) : undefined
    const tile = (code: KpiCode) => {
      const value = advisorValue(code, now)
      const was = before ? advisorValue(code, before) : null
      return { value, wow: value !== null && was ? Math.round(((value - was) / was) * 10000) / 10000 : null }
    }
    const label = (code: KpiCode) => (code === 'ACT_PER_ADV' ? 'Activities completed' : KPI_LABELS[code])
    ledger.ok(`${where} sentence`, checkSentence(ledger, `${where} sentence`, (await lede.textContent()) ?? '', tile, label) > 0, 'reads no figure')
    for (const code of ADVISOR_KPIS) {
      const stat = page.locator(`.stat[data-kpi="${code}"]`)
      ledger.same(`${where} tile ${code} value`, await stat.locator('.stat-value').textContent(), formatKpi(code, tile(code).value))
      ledger.same(`${where} tile ${code} change`, await delta(stat), changeText(tile(code).wow))
    }
    const chosen = (await page.locator('.advisor-pick select').inputValue()) as KpiCode
    const tip = await hoverWeek(page, page.locator('.advisor-trend svg.trend-svg'), week, weeks())
    if (!tip) ledger.fail(`${where} chart`, `no tooltip for ${week}`)
    else ledger.same(`${where} chart tooltip value`, await tip.locator('strong').textContent(), formatKpi(chosen, tile(chosen).value))
  })

  await test.step('map', async () => {
    await page.goto(`/map${query('&view=flat')}`)
    const rows = page.locator('.map-rows li[data-row]')
    const select = page.locator('.map-controls select')
    const lead = (await select.inputValue()) as KpiCode
    const auditRows = async (where: string, code: KpiCode, parent: string) => {
      await expect(rows.first().locator('.map-row-value')).not.toHaveText('–', { timeout: 30_000 })
      const comparing = (await page.locator('.map-rows-head span').nth(1).textContent()) ?? ''
      for (const item of await rows.all()) {
        const node = (await item.getAttribute('data-row'))!
        const row = truth.row(node, code)
        ledger.ok(`${where} ${node} parent`, !row || row.parent_id === parent, `belongs to ${row?.parent_id}`)
        ledger.same(`${where} ${node} value`, await item.locator('.map-row-value').textContent(), formatKpi(code, row?.value))
        const vsUsual = settled(week) && row?.value != null && row.trailing_13w_avg ? row.value / row.trailing_13w_avg - 1 : null
        const expected = row?.value == null ? 'No value' : comparing === 'vs usual' ? (!settled(week) ? 'No usual yet' : vsUsual === null ? 'No usual' : changeText(vsUsual)) : changeText(row.wow_pct)
        ledger.same(`${where} ${node} ${comparing}`, await delta(item), expected)
      }
    }
    /** Hover the shape for `id` where it is the topmost element, and read the shared card. */
    const auditTooltip = async (where: string, code: KpiCode, selector: string, id: string) => {
      const point = await page.locator(`${selector}[data-hot="${id}"]`).first().evaluate((shape, hot) => {
        shape.scrollIntoView({ block: 'center', inline: 'center' })
        const box = shape.getBoundingClientRect()
        for (let i = 1; i < 40; i++) for (let j = 1; j < 40; j++) {
          const x = box.left + (box.width * i) / 40
          const y = box.top + (box.height * j) / 40
          if (document.elementFromPoint(x, y)?.closest('[data-hot]')?.getAttribute('data-hot') === hot) return { x, y }
        }
        return null
      }, id)
      if (!point) return ledger.fail(`${where} ${id} tooltip`, 'has no spot on the map where it can be hovered')
      await page.mouse.move(point.x, point.y)
      const card = page.locator('.map-tooltip .hc')
      await expect(card).toBeVisible()
      const row = truth.row(id, code)!
      ledger.same(`${where} ${id} tooltip value`, await card.locator('.hc-value').textContent(), formatKpi(code, row.value))
      checkHappened(ledger, `${where} ${id} tooltip`, await card.locator('.hc-happened li').allTextContents(), code, row, settled(week))
      await page.mouse.move(0, 0)
    }
    for (const code of KPI_CODES.filter((c) => !NATIONAL_ONLY.has(c) && truth.row('CA', c)?.value != null)) {
      await select.selectOption(code)
      ledger.same(`map ${code} readout`, await loaded(page.locator('.map-readout-value .figure-num'), formatKpi(code, truth.row('CA', code)?.value)), formatKpi(code, truth.row('CA', code)?.value))
      await auditRows(`map ${code}`, code, 'CA')
      if (code === lead) for (const row of truth.children('CA', code)) await auditTooltip(`map ${code}`, code, 'path.map-province', row.node_id)
    }
    await page.goto(`/map${query(`&view=flat&region=${region}`)}`)
    ledger.same(`map ${region} readout`, await loaded(page.locator('.map-readout-value .figure-num'), formatKpi(lead, truth.row(region, lead)?.value)), formatKpi(lead, truth.row(region, lead)?.value))
    await auditRows(`map ${region} ${lead}`, lead, region)
    for (const row of truth.children(region, lead)) await auditTooltip(`map ${region} ${lead}`, lead, 'circle.map-mark', row.node_id)
  })

  await test.step('quality', async () => {
    await page.goto('/quality')
    const lastWeek = [...new Set(truth.dq.map((r) => r.iso_week_id))].sort().at(-1)!
    const rate = (rule: string, w = lastWeek) => {
      const row = truth.dq.find((r) => r.rule_id === rule && r.iso_week_id === w)
      return row && (row.rows_in_batch > 0 ? row.rows_affected / row.rows_in_batch : row.rate ?? null)
    }
    await expect(page.locator('.rule-list li').first()).toBeVisible({ timeout: 60_000 })
    for (const item of await page.locator('.rule-list li').all()) {
      const rule = (await item.locator('.rule-id').textContent())!
      ledger.same(`quality rule list ${rule}`, await item.locator('.rule-rate').textContent(), formatShare(rate(rule)!))
    }
    for (const tr of await page.locator('.quality-table tbody tr').all()) {
      const rule = (await tr.locator('th').textContent())!
      const r = rate(rule)
      if (r != null) ledger.same(`quality index ${rule}`, await tr.locator('td').nth(2).textContent(), formatShare(r))
    }
    const selected = (await page.locator('.rule-list button[aria-pressed="true"] .rule-id').textContent())!
    const tip = await hoverWeek(page, page.locator('.rule-detail svg.trend-svg'), lastWeek, [...new Set(truth.dq.map((r) => r.iso_week_id))].sort())
    if (!tip) ledger.fail('quality chart', `no tooltip for ${lastWeek}`)
    else ledger.same(`quality chart ${selected}`, await tip.locator('strong').textContent(), formatShare(rate(selected)!))
    await page.mouse.move(0, 0)
    const detail = page.locator('.rule-detail details')
    await detail.locator('summary').click()
    const cells = detail.locator('tbody tr').filter({ has: page.locator(`th:text-is("${lastWeek}")`) }).locator('td')
    const dqRow = truth.dq.find((r) => r.rule_id === selected && r.iso_week_id === lastWeek)!
    ledger.same(`quality table ${selected} affected`, await cells.nth(0).textContent(), dqRow.rows_affected.toLocaleString('en-CA'))
    ledger.same(`quality table ${selected} rate`, await cells.nth(2).textContent(), formatShare(rate(selected)!))
    ledger.ok(`quality caption ${selected}`, ((await page.locator('.rule-detail figcaption p').textContent()) ?? '').includes(`Latest: ${formatShare(rate(selected)!)} of the batch, ${dqRow.rows_affected.toLocaleString('en-CA')} rows.`), 'does not state the latest rate and rows')

    const run = truth.runLog?.runs.find((r) => r.run_type === 'WEEKLY') ?? truth.runLog?.runs[0]
    const check = run?.checks.find((c) => c.check_id === 'DQ032')
    const shown = await page.locator('.check[data-check="DQ032"] .check-value').textContent().catch(() => null)
    if (run && check?.observed != null && shown && shown !== 'No new rows') {
      const observed = check.observed > 1 ? check.observed / 100 : check.observed
      ledger.same('quality DQ032 check', shown, formatShare(observed))
      // The same rate is a KPI on the overview: both must read the same.
      const kpi = truth.row('CA', 'QUAR_RATE', run.iso_week_id)
      if (kpi?.value != null) ledger.same(`overview quarantine rate ${run.iso_week_id} vs the DQ032 check`, formatKpi('QUAR_RATE', kpi.value), formatShare(observed))
      const ingest = run.stages.filter((s) => s.stage === 'ingest').at(-1)
      const intro = (await page.locator('.intro').textContent()) ?? ''
      if (ingest?.rows_in && ingest.rows_quarantined != null && intro.includes('rows were quarantined')) {
        const expected = `${ingest.rows_quarantined.toLocaleString('en-CA')} of ${ingest.rows_in.toLocaleString('en-CA')} rows were quarantined (${formatShare(ingest.rows_quarantined / ingest.rows_in)})`
        ledger.ok('quality sentence', intro.includes(expected), `"${intro}" does not say "${expected}"`)
      }
    }
  })

  console.log(`Audit of ${week} (${region} › ${district} › ${branch} › ${advisor}) on ${EXPORTS}: ${ledger.checked} figures checked, ${ledger.misses.length} disagree.`)
  expect(ledger.misses, `${ledger.misses.length} of ${ledger.checked} figures disagree with the export`).toEqual([])
})
