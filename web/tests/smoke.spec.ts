import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'

const routes = [
  ['/', 'Overview'],
  ['/r/ON', 'Region'],
  ['/r/ON/d/GTA', 'District'],
  ['/r/ON/d/GTA/b/BR-0412', 'Branch'],
  ['/r/ON/d/GTA/b/BR-0412/a/AD-001', 'Advisor'],
  ['/map', 'Map'],
  ['/pipeline', 'Pipeline'],
  ['/quality', 'Data quality'],
  ['/case-study', 'Case study'],
] as const

for (const [path, heading] of routes) {
  test(`${path} renders ${heading}`, async ({ page }) => {
    await page.goto(path)
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
    await expect(page.getByText('Weekly batch report · synthetic data · fictional bank')).toBeVisible()
  })
}

test('navigation works by keyboard at 375 px', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Map', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
})

test('system dark mode and reduced motion are reflected globally', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduced')
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe('dark')
})

test('dev data path serves fixture exports', async ({ request }) => {
  const response = await request.get('/data/probe.txt')
  expect(response.ok()).toBe(true)
  expect(await response.text()).toBe('fixture export probe\n')
})

test('fixture URLs accept query parameters', async ({ request }) => {
  const response = await request.get('/data/probe.txt?v=1')
  expect(response.ok()).toBe(true)
  expect(await response.text()).toBe('fixture export probe\n')
})

test('missing fixture URLs return 404 instead of the app shell', async ({ request }) => {
  const response = await request.get('/data/missing.json')
  expect(response.status()).toBe(404)
  expect(await response.text()).toBe('Not found')
})

const exportsDir = resolve(import.meta.dirname, '../../fixtures/exports')

test('overview paints KPI values from the manifest before DuckDB-WASM loads', async ({ page }) => {
  const wasmRequests: string[] = []
  // Hold every jsDelivr request open: the summary must not wait for the engine.
  await page.route('https://cdn.jsdelivr.net/**', (route) => { wasmRequests.push(route.request().url()) })
  await page.route('**/data/manifest.json', (route) => route.fulfill({ path: resolve(exportsDir, 'manifest.json') }))
  await page.goto('/')
  const kpi = page.locator('[data-kpi="ACT_PER_ADV"]')
  await expect(kpi).toContainText('Activities per advisor')
  await expect(kpi).toContainText('11.5')
  await expect(kpi).toContainText('+14.6% WoW')
  await expect(page.getByRole('heading', { name: 'National, week 2026-W40' })).toBeVisible()
})

test('a failed manifest fetch shows a calm notice with the last run time', async ({ page }) => {
  await page.route('**/data/manifest.json', (route) => route.fulfill({ status: 503, body: 'down' }))
  await page.route('**/data/run_log.json', (route) => route.fulfill({ path: resolve(exportsDir, 'run_log.json') }))
  await page.goto('/')
  await expect(page.getByText("We could not load this week's report just now.")).toBeVisible()
  await expect(page.getByText(/Last weekly run: Oct 5, 2026/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
})

test('a failed manifest fetch on a drill page shows a retryable notice', async ({ page }) => {
  await page.route('**/data/manifest.json', (route) => route.fulfill({ status: 503, body: 'down' }))
  await page.route('**/data/run_log.json', (route) => route.fulfill({ path: resolve(exportsDir, 'run_log.json') }))
  await page.goto('/r/ON')
  await expect(page.getByText("We could not load this week's report just now.")).toBeVisible()
  await expect(page.getByText(/Last weekly run: Oct 5, 2026/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible()
})
for (const colorScheme of ['light', 'dark'] as const) {
  test(`kitchen sink renders primitives and themed charts in ${colorScheme}`, async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.emulateMedia({ colorScheme })
    await page.goto('/_kitchen-sink')
    await expect(page.getByRole('heading', { name: 'Kitchen sink', exact: true })).toBeVisible()
    await expect(page.getByRole('navigation', { name: 'Breadcrumb' }).locator('[aria-current="page"]')).toHaveText('BR-0412')
    await expect(page.getByLabel('−29.7%, better than last week')).toBeVisible()
    await expect(page.locator('.chart svg')).toHaveCount(2)
    // The ECharts theme takes its series colours from tokens.css for the active scheme.
    const series1 = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--series-1').trim())
    await expect(page.locator(`.chart svg path[stroke="${series1}" i]`).first()).toBeAttached()
    expect(errors).toEqual([])
  })
}
