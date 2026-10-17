import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'

const manifestPath = resolve(import.meta.dirname, '../../fixtures/exports/manifest.json')
const exportsDir = resolve(import.meta.dirname, '../../fixtures/exports')

test.beforeEach(async ({ page }) => {
  await page.route('http://127.0.0.1:43719/data/**', (route) => {
    const file = new URL(route.request().url()).pathname.split('/data/')[1]
    return route.fulfill({ path: resolve(exportsDir, file) })
  })
})

test('fixture choropleth has a seven-step legend and keyboard drill to region and district', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: 'dark' })
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/map')
  await expect(page.getByRole('heading', { name: 'Map', exact: true })).toBeVisible()
  await expect(page.getByLabel('regions choropleth')).toBeVisible()
  await expect(page.locator('.map-swatch')).toHaveCount(7)
  const ontario = page.getByRole('button', { name: /Ontario/ })
  await expect(ontario).toContainText('%')
  await ontario.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/r\/ON$/)

  await page.goto('/map?region=ON&week=2026-W39')
  await expect(page.getByLabel('districts choropleth')).toBeVisible()
  const gta = page.getByRole('button', { name: /GTA/ })
  await gta.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/r\/ON\/d\/GTA\?week=2026-W39$/)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('FSA boundaries load only when the manifest enables them', async ({ page }) => {
  const requests: string[] = []
  page.on('request', (request) => { if (request.url().includes('/geo/fsa.topo.json')) requests.push(request.url()) })
  await page.goto('/map')
  await expect(page.getByLabel('regions choropleth')).toBeVisible()
  await expect(page.getByRole('checkbox', { name: 'FSA coverage layer' })).toHaveCount(0)
  expect(requests).toHaveLength(0)

  await page.route('**/data/manifest.json', (route) => {
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
    return route.fulfill({ json: { ...manifest, has_fsa_boundaries: true } })
  })
  await page.reload()
  await page.getByRole('checkbox', { name: 'FSA coverage layer' }).check()
  await expect(page.getByLabel('fsa choropleth')).toBeVisible()
  await expect.poll(() => requests.length).toBe(1)
})

test('FSA mode fixes the measure to coverage and exposes the mapped values as a table', async ({ page }) => {
  await page.route('**/data/manifest.json', (route) => {
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
    return route.fulfill({ json: { ...manifest, has_fsa_boundaries: true } })
  })
  await page.goto('/map')
  const measure = page.getByRole('combobox', { name: 'Measure' })
  await measure.selectOption('CALLS_OUT')
  await page.getByRole('checkbox', { name: 'FSA coverage layer' }).check()
  await expect(measure).toHaveValue('COVERAGE_13W')
  await expect(measure).toBeDisabled()
  const table = page.getByRole('table', { name: /13-week coverage by FSA/ })
  await expect(table.locator('tbody tr')).toHaveCount(122)
  await expect(table.locator('tbody tr').first()).toContainText('%')
  await page.getByRole('checkbox', { name: 'FSA coverage layer' }).uncheck()
  await expect(measure).toHaveValue('CALLS_OUT')
  await expect(measure).toBeEnabled()
})

test('FSA data failure has a retry instead of an empty map', async ({ page }) => {
  await page.route('**/data/manifest.json', (route) => {
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
    return route.fulfill({ json: { ...manifest, has_fsa_boundaries: true } })
  })
  await page.route('**/data/geo_weekly.parquet', (route) => route.fulfill({ status: 503, body: 'unavailable' }))
  await page.goto('/map')
  await page.getByRole('checkbox', { name: 'FSA coverage layer' }).check()
  await expect(page.getByText('We could not load FSA coverage just now.')).toBeVisible()
  await expect(page.getByText('FSA coverage is unavailable.')).toBeVisible()
  await page.unroute('**/data/geo_weekly.parquet')
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByRole('table', { name: /13-week coverage by FSA/ })).toBeVisible()
})

test('clicking a district polygon opens its report', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/map?region=ON')
  await expect(page.getByRole('button', { name: /Eastern Ontario/ })).toContainText('%')
  const canvas = page.locator('.map-canvas')
  const box = await canvas.boundingBox()
  expect(box).not.toBeNull()
  // This point lies inside the Eastern Ontario polygon in the shipped fixture geography.
  await page.mouse.move(box!.x + 568, box!.y + 177)
  await expect(page.locator('.deck-tooltip')).toHaveText('Eastern Ontario')
  await page.mouse.click(box!.x + 568, box!.y + 177)
  await expect(page).toHaveURL(/\/r\/ON\/d\/EON$/)
})

test('map code is fetched only on the map route', async ({ page }) => {
  const mapRequests: string[] = []
  page.on('request', (request) => { if (request.url().includes('/features/map/MapPage')) mapRequests.push(request.url()) })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
  expect(mapRequests).toHaveLength(0)
  await page.getByRole('link', { name: 'Map' }).click()
  await expect(page.getByRole('heading', { name: 'Map', exact: true })).toBeVisible()
  expect(mapRequests).toHaveLength(1)
})
