import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'

const exportsDir = resolve(import.meta.dirname, '../../fixtures/exports')
test.beforeEach(async ({ page }) => {
  await page.route('http://127.0.0.1:43719/data/**', (route) => {
    const file = new URL(route.request().url()).pathname.split('/data/')[1]
    return route.fulfill({ path: resolve(exportsDir, file) })
  })
})

test('overview shows all contracted KPIs, and choosing one plots it with its definition', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/')
  await expect(page.locator('[data-kpi]')).toHaveCount(12)
  await expect(page.locator('[data-kpi="ACT_PER_ADV"]')).toContainText('11.5')
  // The sentence needs DuckDB-WASM from the CDN, which can take a while on a CI runner.
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/^Activities per advisor rose 14\.6% to 11\.5/, { timeout: 30_000 })
  const showRate = page.locator('[data-kpi="SHOW_RATE"] button')
  await page.keyboard.press('Tab')
  await showRate.focus()
  // Keyboard focus opens the hover card: what the measure is, and what happened this week.
  const card = page.getByRole('tooltip')
  await expect(card).toContainText('Of the meetings due in the week')
  await expect(card).toContainText('Click to plot it in the chart above.')
  await expect(showRate).toHaveAttribute('aria-describedby', await card.getAttribute('id') ?? '')
  await page.keyboard.press('Escape')
  await expect(card).toBeHidden()
  await page.keyboard.press('Enter')
  await expect(showRate).toHaveAttribute('aria-pressed', 'true')
  await expect(page).toHaveURL(/kpi=SHOW_RATE/)
  await expect(page.getByRole('heading', { name: 'Show rate', level: 2 })).toBeVisible()
  await expect(page.locator('.hero-definition')).toContainText('Of the meetings due in the week')
  // The chart tooltip, at its widest, stays on a 375 px screen even at the last week.
  const hero = page.getByRole('img', { name: /Show rate, national/ })
  await hero.scrollIntoViewIfNeeded()
  const box = (await hero.boundingBox())!
  await page.mouse.move(box.x + box.width - 2, box.y + box.height / 2)
  await expect(page.locator('.trend-tip')).toBeVisible()
  const tip = (await page.locator('.trend-tip').boundingBox())!
  expect(tip.x + tip.width).toBeLessThanOrEqual(375)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
})

test('the hero chart circles an anomaly week and names it inside the plot at 375 px', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  // In the fixtures, Canada's only flagged week is a late-row rate.
  await page.goto('/?kpi=LATE_RATE')
  const hero = page.getByRole('img', { name: /national/ }).first()
  await hero.scrollIntoViewIfNeeded()
  const ring = page.locator('.trend-ring')
  await expect(ring).toHaveCount(1)
  await expect(ring.locator('text')).toHaveText(/^Anomaly W\d{2}$/)
  const label = (await ring.locator('text').boundingBox())!
  const plot = (await hero.boundingBox())!
  expect(label.x).toBeGreaterThanOrEqual(plot.x)
  expect(label.x + label.width).toBeLessThanOrEqual(plot.x + plot.width)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
})

test('the hero chart reads every fixture week and moves the report week by keyboard, in dark reduced motion', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
  await page.goto('/?kpi=LATE_RATE')
  const chart = page.getByRole('img', { name: /Late-arriving rate, national, 2026-W37 to 2026-W40/ })
  await expect(chart).toBeVisible()
  // The circled anomaly is there at once, with no draw-on, and the chart's name says which week it is.
  await expect(chart).toHaveAccessibleName(/Latest anomaly: 2026-W\d{2}\.$/)
  const ring = page.locator('.trend-ring-circle')
  expect(await ring.evaluate((el) => getComputedStyle(el).animationName)).toBe('none')
  expect(await ring.evaluate((el) => getComputedStyle(el).strokeDashoffset)).toMatch(/^0(px)?$/)
  await chart.focus()
  await page.keyboard.press('ArrowLeft')
  await expect(page).toHaveURL(/week=2026-W39/)
  // Keyboard users get the week's tooltip too, announced as the week moves.
  await expect(page.locator('.trend-tip')).toContainText('2026-W39')
  await expect(page.locator('.trend-tip')).toHaveAttribute('aria-live', 'polite')
  await expect(page.locator('.stepper-week')).toHaveValue('2026-W39')
  await expect(page.locator('[data-kpi]')).toHaveCount(12)
  await page.getByRole('button', { name: 'Next week' }).click()
  await expect(page).not.toHaveURL(/week=/)
  await expect(page.getByRole('button', { name: 'Next week' })).toBeDisabled()
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduced')
})

test('the every-week grid works from the keyboard and batch-only rates skip the regional split', async ({ page }) => {
  await page.goto('/?kpi=NO_SHOW_RATE')
  await expect(page.locator('.section-lede').filter({ hasText: 'better or worse than its usual' })).toBeVisible()
  const grid = page.getByRole('group', { name: /No-show rate by area and week/ })
  await grid.focus()
  await expect(page.locator('.heat-cursor')).toBeVisible()
  await page.keyboard.press('ArrowLeft')
  await expect(page.locator('.heat-live')).toContainText('2026-W39')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/week=2026-W39/)
  await page.goto('/?kpi=QUAR_RATE')
  await expect(page.getByText(/measured on the whole weekly batch/)).toBeVisible()
  await expect(page.locator('.multiple')).toHaveCount(0)
  await page.getByText('Show the numbers').first().click()
  await expect(page.getByRole('region', { name: 'Quarantine rate by week' }).locator('tbody tr')).toHaveCount(4)
})

test('the funnel, regional charts and every-week view draw from the export', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.funnel-stage')).toHaveCount(4)
  // Each region against its usual week, with the run summary on hover, replaces the paragraphs.
  await expect(page.locator('.moved-row')).toHaveCount(2)
  await page.locator('.moved-link').first().hover()
  await expect(page.getByRole('tooltip')).toContainText(/Click to open the (Ontario|Quebec) report/)
  // Fixtures cover Ontario and Quebec; regions with no rows are left out.
  await expect(page.locator('.multiple')).toHaveCount(2)
  await expect(page.getByRole('link', { name: /Ontario/ }).first()).toHaveAttribute('href', '/r/ON')
  const heat = page.getByRole('img', { name: /regions and districts over 4 weeks/ })
  await expect(heat).toBeVisible()
  await heat.locator('rect').first().click()
  await expect(page).toHaveURL(/week=2026-W37/)
})

test('a failed newest run shows a banner above the previous week\'s KPIs', async ({ page }) => {
  const runLog = JSON.parse(readFileSync(resolve(exportsDir, 'run_log.json'), 'utf8'))
  const failed = { ...runLog.runs[0], run_id: 'weekly-2026-W41-1', iso_week_id: '2026-W41', status: 'FAILED', started_at: '2026-10-12T11:00:00Z' }
  await page.route('http://127.0.0.1:43719/data/run_log.json', (route) =>
    route.fulfill({ json: { ...runLog, runs: [failed, ...runLog.runs].slice(0, 12) } }))
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/')
  const banner = page.locator('.run-status-banner')
  await expect(banner).toContainText('The last weekly run failed.')
  await expect(banner).toContainText('still shows the 2026-W40 report')
  await expect(page.locator('[data-kpi]')).toHaveCount(12)
  await banner.getByRole('link', { name: 'See which stage failed' }).focus()
  await expect(banner.getByRole('link')).toBeFocused()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
})

test('a warn newest run shows no failure banner', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('[data-kpi]')).toHaveCount(12)
  await expect(page.locator('.run-status-banner')).toHaveCount(0)
})

test('the hero series downloads as CSV with raw values', async ({ page }) => {
  await page.goto('/?kpi=SHOW_RATE')
  await expect(page.getByRole('img', { name: /Show rate, national/ })).toBeVisible()
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download CSV' }).click()])
  expect(download.suggestedFilename()).toBe('advisor-pulse_CA_SHOW_RATE.csv')
  const text = await (await import('node:fs/promises')).readFile((await download.path())!, 'utf8')
  const lines = text.replace(/^\uFEFF/, '').trim().split('\r\n')
  expect(lines[0]).toBe('iso_week_id,node_id,node_name,kpi_code,value,prior_week_value,wow_pct,trailing_13w_avg,flag')
  expect(lines).toHaveLength(5)
  expect(lines[1]).toMatch(/^2026-W37,CA,Canada,SHOW_RATE,0\.\d+/)
})

test('the week in 20 seconds plays only when asked and has a transcript, for its own week only', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  const recap = readFileSync(resolve(import.meta.dirname, '../../video/src/sample.json'), 'utf8')
  await page.route('**/recap/recap.json', (route) => route.fulfill({ body: recap, contentType: 'application/json' }))
  await page.goto('/')
  const section = page.getByRole('region', { name: 'The week in 20 seconds' })
  await expect(section).toBeVisible()
  const video = section.locator('video')
  await expect(video).toHaveAttribute('poster', /recap\/poster\.jpg$/)
  expect(await video.evaluate((el: HTMLVideoElement) => el.paused && !el.autoplay)).toBe(true)
  await section.getByText('What the video shows').click()
  await expect(section.locator('.recap-transcript')).toContainText(JSON.parse(recap).headline)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
  // Another week has no video: the recap covers only the week it was rendered for.
  await page.goto('/?week=2026-W39')
  await expect(page.getByRole('heading', { name: 'Activities per advisor', level: 2 })).toBeVisible()
  await expect(page.getByRole('region', { name: 'The week in 20 seconds' })).toHaveCount(0)
})

test.describe('on a touch screen', () => {
  test.use({ hasTouch: true, viewport: { width: 375, height: 812 } })

  test('the first tap on a region opens its card; the second follows the link', async ({ page }) => {
    await page.goto('/')
    const link = page.locator('.moved-link').first()
    await expect(link).toBeVisible({ timeout: 30_000 })
    await link.scrollIntoViewIfNeeded()
    await link.tap()
    await expect(page.getByRole('tooltip')).toContainText(/Click to open the (Ontario|Quebec) report/)
    await expect(page).toHaveURL(/\/$/)
    await link.tap()
    await expect(page).toHaveURL(/\/r\/(ON|QC)/)
  })
})

test('once the summary has a 12-month value, the overview opens on portfolio contacted', async ({ page }) => {
  // The fixtures span four weeks, so their lead KPI is null and activities leads; a summary
  // with a value (a report with a year of history behind it) switches the default.
  const manifest = JSON.parse(readFileSync(resolve(exportsDir, 'manifest.json'), 'utf8'))
  const summary = manifest.summary.map((row: { kpi_code: string }) =>
    row.kpi_code === 'PRTF_CONTACT_12M' ? { ...row, value: 0.84, prior_week_value: 0.85, wow_pct: -0.0118 } : row)
  await page.route('http://127.0.0.1:43719/data/manifest.json', (route) => route.fulfill({ json: { ...manifest, summary } }))
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/')
  await expect(page.locator('#hero-title')).toHaveText('Portfolio contacted (12 months)')
  await expect(page.locator('.hero-definition')).toContainText('heard from an advisor at least once in the last 12 months')
  await page.goto('/?kpi=ACT_PER_ADV')
  await expect(page.locator('#hero-title')).toHaveText('Activities per advisor')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
})

test('the first screen holds the title, the lead figure, a chart sized to its question and every measure', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/^Activities per advisor rose 14\.6% to 11\.5\.$/, { timeout: 30_000 })
  const chart = page.getByRole('img', { name: /Activities per advisor, national/ })
  const plot = (await chart.boundingBox())!
  expect(plot.height).toBeGreaterThanOrEqual(200)
  expect(plot.height).toBeLessThanOrEqual(260)
  // The chart takes about two thirds of the width, the figure beside it.
  const hero = (await page.locator('.hero').boundingBox())!
  expect(plot.width / hero.width).toBeLessThan(0.75)
  // The board's heading and its first row, the measure the title is about, start on the first screen.
  const first = page.locator('[data-kpi]').first()
  await expect(first).toHaveAttribute('data-kpi', 'ACT_PER_ADV')
  expect((await page.getByRole('heading', { name: 'Every measure', level: 2 }).boundingBox())!.y).toBeLessThan(900)
  expect((await first.boundingBox())!.y).toBeLessThan(900 - 48)
  // The lead figure agrees with the title and is the largest figure on the page.
  await expect(page.locator('.hero-value')).toHaveText('11.5')
  const sizes = await page.locator('.figure-num').evaluateAll((els) => els.map((el) => parseFloat(getComputedStyle(el).fontSize)))
  const lead = await page.locator('.hero-value').evaluate((el) => parseFloat(getComputedStyle(el).fontSize))
  expect(Math.max(...sizes)).toBe(lead)

  // A phone is its own composition: the title in two lines at most, the figure, then a shorter chart.
  await page.setViewportSize({ width: 390, height: 844 })
  const title = page.getByRole('heading', { level: 1 })
  const lines = await title.evaluate((el) => Math.round(el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight)))
  expect(lines).toBeLessThanOrEqual(2)
  await expect.poll(async () => (await chart.boundingBox())!.height).toBeLessThanOrEqual(200)
  expect((await chart.boundingBox())!.height).toBeGreaterThanOrEqual(160)
  expect((await page.locator('.hero-value').boundingBox())!.y).toBeLessThan((await chart.boundingBox())!.y)
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
})
