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

test('the overview reads the fiscal quarter to date, by region, at 375 px', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/?kpi=CALLS_OUT')
  const section = page.locator('section', { has: page.getByRole('heading', { name: 'Fiscal quarters', level: 2 }) })
  // DuckDB-WASM comes from the CDN, which can take a while on a CI runner.
  await expect(section.getByRole('heading', { name: 'Q4 FY26', exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(section).toContainText('The fiscal year starts on 1 November.')
  await expect(section).toContainText('Aug 2026 – Oct 2026')
  await expect(section).toContainText('To date: 4 of 13 weeks')
  await expect(section.locator('.quarters-value')).toHaveText('92.5 a week')
  await expect(section.locator('.quarters-col.is-to-date')).toHaveCount(1)
  await expect(section.getByRole('img', { name: /Outbound calls a week, Canada, by fiscal quarter/ })).toBeVisible()
  await expect(section.getByRole('link', { name: 'Ontario' })).toHaveAttribute('href', '/r/ON')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)

  // Distinct clients only grow through a quarter, so they wait for it to close.
  await page.goto('/?kpi=CLIENTS_CONTACTED')
  await expect(section.locator('.quarters-head')).toContainText('None yet', { timeout: 30_000 })
  await page.goto('/?kpi=LATE_RATE')
  await expect(section).toContainText('has no quarterly figure', { timeout: 30_000 })
})

test('a region page lists its districts for the quarter, in dark reduced motion', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: 'dark' })
  await page.goto('/r/ON')
  await expect(page.getByRole('heading', { name: 'Districts in Q4 FY26' })).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.quarters-children tbody tr').first()).toBeVisible()
  const chart = page.getByRole('img', { name: /Ontario, by fiscal quarter/ })
  await chart.focus()
  await page.keyboard.press('End')
  await expect(page.locator('.quarters-col.is-chosen')).toHaveCount(1)
})

test('an export made before the quarterly mart leaves the section out', async ({ page }) => {
  const manifest = JSON.parse(readFileSync(resolve(exportsDir, 'manifest.json'), 'utf8'))
  manifest.files = manifest.files.filter((f: { name: string }) => f.name !== 'org_quarterly.parquet')
  await page.route('http://127.0.0.1:43719/data/manifest.json', (route) => route.fulfill({ json: manifest }))
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Every measure' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /^Activities per advisor/, level: 1 })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('heading', { name: 'Fiscal quarters' })).toHaveCount(0)
})
