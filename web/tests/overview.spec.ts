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
