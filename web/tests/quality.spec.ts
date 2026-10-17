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
  await expect(page.getByRole('table', { name: 'Data quality rule index' }).getByRole('link', { name: 'DQ033' })).toBeVisible()
  await expect(page.getByRole('table', { name: 'Data quality rule index' }).locator('tbody tr')).toHaveCount(18)
  await expect(page.getByRole('table', { name: 'Latest run checks' }).locator('tbody tr')).toHaveCount(4)
  await page.getByLabel('Trend rule').selectOption('DQ010')
  await expect(page.getByRole('img', { name: /DQ010.*weekly/i })).toBeVisible()
  await page.getByText('Show the numbers').click()
  await expect(page.getByRole('table', { name: 'DQ010 weekly values' }).locator('tbody tr')).toHaveCount(4)
  await page.getByLabel('Trend rule').selectOption('DQ033')
  await expect(page.getByText(/No weekly trend data.*DQ033/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
})

test('quality page stays usable with keyboard, dark mode, and reduced motion', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
  await page.goto('/quality')
  const picker = page.getByLabel('Trend rule')
  await picker.focus()
  await expect(picker).toBeFocused()
  await picker.selectOption('DQ002')
  await expect(picker).toHaveValue('DQ002')
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduced')
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe('dark')
})
