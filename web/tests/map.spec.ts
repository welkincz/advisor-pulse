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

test('the national map flies to a region, then a district opens its report, by keyboard at 375 px', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: 'dark' })
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/map')
  await expect(page.getByRole('heading', { name: 'Map', exact: true })).toBeVisible()
  await expect(page.getByLabel('regions map')).toBeVisible()
  await expect(page.locator('.canada-map .map-province')).toHaveCount(13)
  await expect(page.locator('.map-swatch')).toHaveCount(7)
  // The fixtures cover Ontario and Quebec only: the other regions say so instead of going blank.
  await expect(page.locator('.map-rows li', { hasText: 'British Columbia' })).toContainText('–')
  await expect(page.locator('.map-label', { hasText: 'Nova Scotia' })).toContainText('No data')
  const ontario = page.getByRole('button', { name: /Ontario/ })
  await expect(ontario).toContainText('%')
  await ontario.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/map\?region=ON$/)
  await expect(page.getByRole('heading', { name: 'Districts in Ontario' })).toBeVisible()
  await expect(page.getByLabel('districts map')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open the Ontario report' })).toHaveAttribute('href', '/r/ON')

  await page.goto('/map?region=ON&week=2026-W39')
  const gta = page.getByRole('button', { name: /GTA/ })
  await gta.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/r\/ON\/d\/GTA\?week=2026-W39$/)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('the week player scrubs by keyboard and plays through the weeks', async ({ page }) => {
  await page.goto('/map')
  const slider = page.getByRole('slider', { name: /Week shown on the map/ })
  await expect(slider).toHaveAttribute('aria-valuetext', '2026-W40')
  await slider.focus()
  await page.keyboard.press('ArrowLeft')
  await expect(page).toHaveURL(/week=2026-W39/)
  await expect(page.locator('.map-readout-week')).toHaveText('2026-W39')
  const play = page.getByRole('button', { name: 'Play through the weeks' })
  await play.click()
  await expect(page.getByRole('button', { name: 'Pause the week player' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page).not.toHaveURL(/week=/, { timeout: 5000 })
  await expect(page.getByRole('button', { name: 'Play through the weeks' })).toHaveAttribute('aria-pressed', 'false')
})

test('FSA boundaries load only when the manifest enables them', async ({ page }) => {
  const requests: string[] = []
  page.on('request', (request) => { if (request.url().includes('/geo/fsa.topo.json')) requests.push(request.url()) })
  await page.goto('/map')
  await expect(page.getByLabel('regions map')).toBeVisible()
  await expect(page.getByRole('checkbox', { name: 'FSA layer' })).toHaveCount(0)
  expect(requests).toHaveLength(0)

  await page.route('**/data/manifest.json', (route) => {
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
    return route.fulfill({ json: { ...manifest, has_fsa_boundaries: true } })
  })
  await page.reload()
  await page.getByRole('checkbox', { name: 'FSA layer' }).check()
  await expect(page.getByLabel('fsa map')).toBeVisible()
  await expect.poll(() => requests.length).toBe(1)
})

test('FSA mode fixes the measure and exposes the mapped values as a table', async ({ page }) => {
  await page.route('**/data/manifest.json', (route) => {
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
    return route.fulfill({ json: { ...manifest, has_fsa_boundaries: true } })
  })
  await page.goto('/map')
  const measure = page.getByRole('combobox', { name: 'Measure' })
  await measure.selectOption('CALLS_OUT')
  await page.getByRole('checkbox', { name: 'FSA layer' }).check()
  // The fixtures have four weeks, so portfolio contact (12 months) has no value yet and the
  // layer shows activities with each area's clients instead.
  await expect(measure).toHaveValue('CLIENT_ACTIVITIES')
  await expect(measure).toBeDisabled()
  const table = page.getByRole('table', { name: /Activities with clients here by FSA/ })
  await expect(table.locator('tbody tr')).toHaveCount(122)
  await expect(table.locator('tbody tr').first().locator('td')).toHaveText(/^\d[\d,]*$/)
  const values = page.getByRole('region', { name: 'FSA values' })
  await values.focus()
  await page.keyboard.press('End')
  await expect.poll(() => values.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
  await expect(page.locator('.map-readout-kpi')).toHaveText('Activities with clients here')
  await expect(page.locator('.map-readout-value .figure-num')).toHaveText(/^\d[\d,]*$/)
  await page.getByRole('checkbox', { name: 'FSA layer' }).uncheck()
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
  await page.getByRole('checkbox', { name: 'FSA layer' }).check()
  await expect(page.getByText('We could not load FSA values just now.')).toBeVisible()
  await page.unroute('**/data/geo_weekly.parquet')
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByRole('table', { name: /by FSA/ })).toBeVisible()
})

test('a failed FSA shape load says so and retries', async ({ page }) => {
  await page.route('**/data/manifest.json', (route) => {
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
    return route.fulfill({ json: { ...manifest, has_fsa_boundaries: true } })
  })
  await page.route('**/geo/fsa.topo.json', (route) => route.fulfill({ status: 503, body: 'unavailable' }))
  await page.goto('/map')
  await page.getByRole('checkbox', { name: 'FSA layer' }).check()
  const alert = page.locator('.map-alert')
  await expect(alert).toContainText('The FSA shapes could not load')
  await page.unroute('**/geo/fsa.topo.json')
  await alert.getByRole('button', { name: 'Try again' }).click()
  await expect(alert).toHaveCount(0)
  await expect(page.locator('.canada-map .map-fsa')).toHaveCount(122)
})

test('a failed district activity query is reported instead of drawing equal circles silently', async ({ page }) => {
  let failed = false
  await page.route('**/data/org_weekly.parquet', (route) => {
    if (failed) return route.fallback()
    failed = true
    return route.fulfill({ status: 503, body: 'unavailable' })
  })
  await page.goto('/map')
  await expect(page.getByText(/could not load district activity/)).toBeVisible()
})

test('hovering a district circle names it, and clicking opens its report', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/map?region=ON')
  await expect(page.getByRole('button', { name: /Eastern Ontario/ })).toContainText('%')
  const circle = page.locator('.canada-map circle[data-hot="EON"]')
  await expect(circle).toBeVisible()
  // The fixture weeks are all warm-up (no usual level yet): a value with no comparison is a
  // solid neutral circle, not the dashed ring reserved for a missing value.
  await expect(circle).not.toHaveClass(/is-empty/)
  await expect(page.locator('.map-legend')).toContainText('No value this week')
  await circle.hover()
  await expect(page.locator('.map-tooltip')).toContainText('Eastern Ontario')
  await expect(page.locator('.map-rows li.is-hot')).toContainText('Eastern Ontario')
  await circle.click()
  await expect(page).toHaveURL(/\/r\/ON\/d\/EON$/)
})

test('the map pans by drag and zooms from the keyboard without leaving the route', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/map?region=ON')
  const map = page.locator('.canada-map')
  const layer = page.locator('.canada-map > g').first()
  await expect(page.locator('.canada-map circle[data-hot="EON"]')).toBeVisible()
  const parse = async () => {
    const value = (await layer.getAttribute('transform'))!
    const [, x, y, k] = /translate\(([-\d.]+) ([-\d.]+)\) scale\(([-\d.]+)\)/.exec(value)!.map(Number)
    return { x: x!, y: y!, k: k! }
  }
  const fitted = await parse()
  expect(fitted.k).toBeGreaterThan(1)
  const box = (await map.boundingBox())!
  await page.mouse.move(box.x + 40, box.y + 40)
  await page.mouse.down()
  await page.mouse.move(box.x + 140, box.y + 90, { steps: 5 })
  await page.mouse.up()
  const dragged = await parse()
  expect(dragged.x - fitted.x).toBeCloseTo(100, 0)
  expect(dragged.y - fitted.y).toBeCloseTo(50, 0)
  await map.focus()
  await page.keyboard.press('+')
  expect((await parse()).k).toBeCloseTo(fitted.k * 1.5, 3)
  await page.keyboard.press('0')
  expect(await parse()).toEqual(fitted)
  await page.keyboard.press('Escape')
  await expect(page).toHaveURL(/\/map$/)
})

test('map code is fetched only on the map route', async ({ page }) => {
  const mapRequests: string[] = []
  page.on('request', (request) => { if (request.url().includes('/features/map/MapPage')) mapRequests.push(request.url()) })
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  expect(mapRequests).toHaveLength(0)
  await page.getByRole('link', { name: 'Map', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Map', exact: true })).toBeVisible()
  expect(mapRequests).toHaveLength(1)
})

test('the relief map is the default where WebGL and motion are welcome, and Flat switches back', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/map')
  const relief = page.locator('.relief canvas')
  test.skip(!(await page.evaluate(() => Boolean(document.createElement('canvas').getContext('webgl')))), 'no WebGL in this browser')
  await expect(relief).toBeVisible()
  await expect(relief).toHaveAttribute('aria-label', /in relief: height is the value, colour the comparison/)
  await expect(page.locator('.relief-label', { hasText: 'Ontario' })).toBeVisible()
  await expect(page.locator('.relief-leaders line')).toHaveCount(3)

  await page.getByRole('button', { name: /Ontario/ }).click()
  await expect(page).toHaveURL(/\/map\?region=ON$/)
  await expect(page.getByRole('heading', { name: 'Districts in Ontario' })).toBeVisible()
  await expect(relief).toBeVisible()

  await page.getByLabel('Flat').check()
  await expect(page).toHaveURL(/view=flat/)
  await expect(relief).toHaveCount(0)
  await expect(page.getByLabel('districts map')).toBeVisible()
})

test('the relief canvas keeps its size and name when the measure or week changes', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/map')
  const relief = page.locator('.relief canvas')
  await expect(relief).toBeVisible()
  const before = await relief.boundingBox()
  await page.getByRole('combobox', { name: 'Measure', exact: true }).selectOption('CALLS_OUT')
  await expect(relief).toHaveAttribute('aria-label', /Outbound calls by province/)
  await page.goto('/map?kpi=CALLS_OUT&week=2026-W39')
  await expect(relief).toHaveAttribute('aria-label', /2026-W39/)
  expect((await relief.boundingBox())?.width).toBeCloseTo(before!.width, 0)
  expect((await relief.boundingBox())?.height).toBeGreaterThan(200)
})

test('reduced motion keeps the flat map, even when the link asks for relief', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/map?view=relief')
  await expect(page.getByLabel('regions map')).toBeVisible()
  await expect(page.locator('.relief canvas')).toHaveCount(0)
  await expect(page.getByRole('group', { name: 'View' })).toHaveCount(0)
})

test('the relief map fits a 375 px screen without sideways scrolling', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/map?view=relief')
  await expect(page.locator('.relief canvas')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('the list shows the comparison the colours show, and each row explains itself on hover', async ({ page }) => {
  await page.goto('/map?view=flat')
  // Four fixture weeks have no usual yet, so the colours fall back to value and the list says it compares with last week.
  await expect(page.locator('.map-legend')).not.toContainText('usual week')
  await expect(page.locator('.map-rows-head')).toContainText('vs last week')
  // A region with no rows says it has no value, not that it is warming up.
  await expect(page.locator('.map-rows li', { hasText: 'British Columbia' })).toContainText('No value')
  const ontario = page.locator('.map-rows li', { hasText: 'Ontario' })
  await ontario.locator('button').hover()
  const card = page.getByRole('tooltip')
  // The map opens on the lead KPI; the 4-week fixtures have no 12-month window, so activities leads.
  await expect(card).toContainText('Calls, meetings and reviews the average advisor completed')
  await expect(card).toContainText('Click to fly to its districts.')
})
