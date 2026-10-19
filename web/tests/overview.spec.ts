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

test('overview shows all contracted KPIs with keyboard-accessible definitions', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/')
  await expect(page.locator('[data-kpi]')).toHaveCount(12)
  await expect(page.getByText('11.5', { exact: true })).toBeVisible()
  const definition = page.locator('[data-kpi="ACT_PER_ADV"] details')
  await definition.locator('summary').focus()
  await page.keyboard.press('Enter')
  await expect(definition).toContainText('Completed activities')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
})

test('overview trend reads fixture weeks and marks an anomaly in dark reduced-motion mode', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
  await page.goto('/')
  await page.getByLabel('Trend KPI').selectOption('LATE_RATE')
  await expect(page.getByRole('img', { name: /Late-arriving rate.*2026-W37.*2026-W40/ })).toBeVisible()
  await expect(page.getByText('Anomaly in 2026-W40')).toBeVisible()
  await page.getByText('Show the numbers').click()
  await expect(page.locator('.figure-table tbody tr')).toHaveCount(4)
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduced')
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
