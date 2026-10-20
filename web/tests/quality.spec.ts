import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'

const exportsDir = resolve(import.meta.dirname, '../../fixtures/exports')

test.beforeEach(async ({ page }) => {
  for (const name of ['manifest.json', 'dq_weekly.parquet', 'run_log.json']) {
    await page.route(`**/data/${name}`, (route) => route.fulfill({ path: resolve(exportsDir, name) }))
  }
})

test('quality page lists all documented rules, recorded trends, and latest run checks', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/quality')
  await expect(page.getByRole('heading', { name: 'Data quality', exact: true })).toBeVisible()
  await expect(page.locator('.intro')).toHaveText(/^All 4 run checks passed for 2026-W40\./)
  await expect(page.getByRole('table', { name: 'Data quality rule index' }).getByRole('link', { name: 'DQ033' })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Data quality rule index' }).locator('tbody tr')).toHaveCount(18)
  await expect(page.locator('.check')).toHaveCount(4)
  await expect(page.locator('[data-check="DQ032"] .check-value')).toHaveText('1.56%')
  await expect(page.locator('[data-check="DQ032"] .bullet-bar')).not.toHaveClass(/is-fail/)
  await page.getByRole('list', { name: 'Measured rules' }).getByRole('button', { name: /DQ010/ }).click()
  await expect(page).toHaveURL(/rule=DQ010/)
  await expect(page.getByRole('img', { name: /DQ010 weekly affected rate/ })).toBeVisible()
  await page.locator('.rule-detail').getByText('Show the numbers').click()
  await expect(page.getByRole('table', { name: 'DQ010 weekly values' }).locator('tbody tr')).toHaveCount(4)
  await page.locator('#quality-volume-title').locator('xpath=ancestor::section').getByText('Show the numbers').click()
  await expect(page.getByRole('region', { name: 'Rows held back by week' }).locator('tbody tr')).toHaveCount(4)
  await expect(page.getByRole('img', { name: /Rows caught by data quality rules per week/ })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
})

test('quality page stays usable with keyboard, dark mode, and reduced motion', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
  await page.goto('/quality')
  const rule = page.getByRole('list', { name: 'Measured rules' }).getByRole('button', { name: /DQ002/ })
  await rule.focus()
  await page.keyboard.press('Enter')
  await expect(rule).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduced')
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe('dark')
})
