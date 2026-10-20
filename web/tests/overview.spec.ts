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
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/^Activities per advisor rose 14\.6% to 11\.5/)
  const showRate = page.locator('[data-kpi="SHOW_RATE"] button')
  await showRate.focus()
  await page.keyboard.press('Enter')
  await expect(showRate).toHaveAttribute('aria-pressed', 'true')
  await expect(page).toHaveURL(/kpi=SHOW_RATE/)
  await expect(page.getByRole('heading', { name: 'Show rate', level: 2 })).toBeVisible()
  await expect(page.locator('.hero-definition')).toContainText('Held appointments divided by')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
})

test('the hero chart reads every fixture week and moves the report week by keyboard, in dark reduced motion', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
  await page.goto('/?kpi=LATE_RATE')
  const chart = page.getByRole('img', { name: /Late-arriving rate, national, 2026-W37 to 2026-W40/ })
  await expect(chart).toBeVisible()
  await chart.focus()
  await page.keyboard.press('ArrowLeft')
  await expect(page).toHaveURL(/week=2026-W39/)
  await expect(page.locator('.stepper-week')).toHaveText('2026-W39')
  await expect(page.locator('[data-kpi]')).toHaveCount(12)
  await page.getByRole('button', { name: 'Next week' }).click()
  await expect(page).not.toHaveURL(/week=/)
  await expect(page.getByRole('button', { name: 'Next week' })).toBeDisabled()
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduced')
})

test('the funnel, regional charts and every-week view draw from the export', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.funnel-stage')).toHaveCount(4)
  await expect(page.locator('.multiple')).toHaveCount(4)
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
