import { resolve } from 'node:path'
import { mkdir } from 'node:fs/promises'
import { expect, test } from '@playwright/test'

const exportsDir = resolve(import.meta.dirname, '../../fixtures/exports')
const recordingDir = resolve(import.meta.dirname, '../../docs/recordings/issue-53')

test.use({ video: process.env.RECORD_MOTION ? 'on' : 'off' })

test.afterEach(async ({ page }, info) => {
  if (!process.env.RECORD_MOTION) return
  await mkdir(recordingDir, { recursive: true })
  const video = page.video()
  await page.close()
  await video?.saveAs(resolve(recordingDir, `${info.title.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}.webm`))
})

test.beforeEach(async ({ page }) => {
  if (process.env.RECORD_MOTION) await mkdir(recordingDir, { recursive: true })
  await page.route('http://127.0.0.1:43719/data/**', (route) => {
    const file = new URL(route.request().url()).pathname.split('/data/')[1]
    return route.fulfill({ path: resolve(exportsDir, file) })
  })
})

test('week change tweens a KPI without shifting the report', async ({ page }) => {
  await page.goto('/r/ON')
  const value = page.locator('[data-kpi="ACT_PER_ADV"] .stat-value')
  await expect(value.locator('[data-motion-number]')).toBeVisible()
  await expect(page.locator('.section[data-reveal-order]')).toHaveCount(3)
  if (process.env.RECORD_MOTION) await page.screenshot({ path: resolve(recordingDir, 'week-before.png'), fullPage: true })
  const before = await value.textContent()
  await page.evaluate(() => {
    const shifts: number[] = []
    const values: string[] = []
    const visual = document.querySelector('[data-kpi="ACT_PER_ADV"] .motion-number-visual')!
    new MutationObserver(() => values.push(visual.textContent ?? '')).observe(visual, { childList: true, characterData: true, subtree: true })
    Object.assign(window, { __motionShifts: shifts, __motionValues: values })
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        const shift = entry as PerformanceEntry & { value: number; hadRecentInput: boolean }
        if (!shift.hadRecentInput) shifts.push(shift.value)
      }
    }).observe({ type: 'layout-shift' })
  })
  await page.getByRole('combobox', { name: /^Week/ }).selectOption('2026-W39')
  await expect.poll(async () => value.textContent()).not.toBe(before)
  await page.waitForTimeout(700)
  const measurements = await page.evaluate(() => {
    const state = window as Window & { __motionShifts: number[]; __motionValues: string[] }
    return { cls: state.__motionShifts.reduce((sum, shift) => sum + shift, 0), distinctValues: new Set(state.__motionValues).size }
  })
  expect(measurements.distinctValues).toBeGreaterThan(2)
  const cls = measurements.cls
  expect(cls).toBeLessThan(0.05)
  if (process.env.RECORD_MOTION) await page.screenshot({ path: resolve(recordingDir, 'week-after.png'), fullPage: true })
})

test('reduced motion shows final values and sections without animation', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: 'dark' })
  await page.goto('/r/ON')
  const value = page.locator('[data-kpi="ACT_PER_ADV"] .stat-value')
  await expect(page.getByRole('heading', { name: 'Ontario', exact: true })).toBeVisible()
  await expect(value).toContainText('10.4')
  await expect(value.locator('[data-motion-number]')).toHaveCount(0)
  const sections = page.locator('.section[data-reveal-order]')
  await expect(sections).toHaveCount(3)
  for (const section of await sections.all()) {
    expect(await section.evaluate((element) => getComputedStyle(element).opacity)).toBe('1')
  }
  await page.getByRole('combobox', { name: /^Week/ }).selectOption('2026-W39')
  await expect(value.locator('[data-motion-number]')).toHaveCount(0)
  await expect(value).toContainText('10.1')
  if (process.env.RECORD_MOTION) await page.screenshot({ path: resolve(recordingDir, 'reduced-375.png'), fullPage: true })
})

test('narrative reveals only on the first report view', async ({ page }) => {
  await page.goto('/r/ON')
  const narrative = page.locator('section[aria-labelledby="weekly-narrative-title"]')
  await expect(narrative).toHaveAttribute('data-reveal-order', '1')
  const week = page.getByRole('combobox', { name: /^Week/ })
  await week.selectOption('2026-W39')
  await expect(narrative).toHaveCount(0)
  await week.selectOption('2026-W40')
  await expect(narrative).toBeVisible()
  await expect(narrative).not.toHaveAttribute('data-reveal-order', /./)
})

test('drill shares a title transition and bypasses it for reduced motion', async ({ page }) => {
  if (process.env.RECORD_MOTION) {
    await page.goto('/r/ON')
    await expect(page.getByRole('table').getByRole('link').first()).toBeVisible()
    expect(await page.evaluate(() => typeof document.startViewTransition)).toBe('function')
    await page.getByRole('table').getByRole('link').first().click()
    await expect(page).toHaveURL(/\/r\/ON\/d\//)
    await page.waitForTimeout(400)
    await page.goBack()
  }
  await page.addInitScript(() => {
    Object.assign(window, { __transitionCount: 0 })
    ;(document as Document & { startViewTransition?: (update: () => void) => { ready: Promise<void>; finished: Promise<void> } }).startViewTransition = (update) => {
      const state = window as Window & { __transitionCount: number }
      state.__transitionCount += 1
      update()
      return { ready: Promise.resolve(), finished: Promise.resolve() }
    }
  })
  await page.goto('/r/ON')
  await page.getByRole('table').getByRole('link').first().click()
  await expect(page).toHaveURL(/\/r\/ON\/d\//)
  expect(await page.evaluate(() => (window as Window & { __transitionCount: number }).__transitionCount)).toBe(1)

  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/r/ON')
  await page.getByRole('table').getByRole('link').first().click()
  await expect(page).toHaveURL(/\/r\/ON\/d\//)
  expect(await page.evaluate(() => (window as Window & { __transitionCount: number }).__transitionCount)).toBe(0)
})
