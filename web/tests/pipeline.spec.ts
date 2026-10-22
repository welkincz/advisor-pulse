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

test('replays the last weekly run, then can restart it', async ({ page }) => {
  await page.goto('/pipeline')
  await expect(page.getByText(/^Replaying weekly run of October 5, 2026/)).toBeVisible()
  await expect(page.locator('.line-diagram [data-node]')).toHaveCount(18)
  const replay = page.getByRole('button', { name: 'Replay run' })
  await expect(replay).toBeDisabled()
  await expect(page.getByText(/^Weekly run of October 5, 2026/)).toBeVisible({ timeout: 9000 })
  await expect(page.locator('[data-node="narrate"]')).toHaveAttribute('aria-label', /Warning/)
  await expect(page.locator('.timeline-row').first()).toContainText('Restore state')
  await replay.click()
  await expect(page.getByText(/^Replaying weekly run of October 5, 2026/)).toBeVisible()
})

test('a retried stage opens a panel with each attempt; checks list their results', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/pipeline')
  await page.getByRole('button', { name: /2026-W39/ }).click()
  await page.locator('[data-node="restore_state"]').click()
  const panel = page.getByRole('complementary')
  await expect(panel.getByRole('heading', { name: 'Restore state' })).toBeVisible()
  await page.locator('[data-node="ingest"]').focus()
  await page.keyboard.press('Enter')
  await expect(panel.getByRole('heading', { name: 'Ingest + validate' })).toBeVisible()
  await expect(panel).toContainText('after 2 attempts')
  await expect(panel.locator('tbody tr')).toHaveCount(2)
  await expect(panel).toContainText('Failed')
  await page.keyboard.press('Escape')
  await expect(panel).toHaveCount(0)
  await page.locator('[data-node="checks"]').focus()
  await page.keyboard.press('Enter')
  await expect(panel).toContainText('Check results')
})

test('history shows status with an icon and selecting a run updates the canvas', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/pipeline')
  const history = page.getByRole('region', { name: 'Run history' })
  await expect(history.getByRole('button')).toHaveCount(4)
  await expect(history.getByRole('button', { name: /2026-W40/ })).toHaveAttribute('aria-pressed', 'true')
  const older = history.getByRole('button', { name: /2026-W38/ })
  await expect(older).toContainText('✓')
  await expect(older).toContainText('Succeeded')
  await older.focus()
  await page.keyboard.press('Enter')
  await expect(older).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByText(/^Weekly run of September 21, 2026/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('history and replay identify manual and backfill runs', async ({ page }) => {
  const log = JSON.parse(readFileSync(resolve(exportsDir, 'run_log.json'), 'utf8'))
  log.runs[0].run_type = 'MANUAL'
  log.runs[1].run_type = 'BACKFILL'
  await page.route('**/data/run_log.json', (route) => route.fulfill({ json: log }))
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/pipeline')
  const history = page.getByRole('region', { name: 'Run history' })
  await expect(history.getByRole('button', { name: /2026-W40 Manual/ })).toBeVisible()
  await expect(page.getByText(/^Manual run of October 5, 2026/)).toBeVisible()
  await history.getByRole('button', { name: /2026-W39 Backfill/ }).click()
  await expect(page.getByText(/^Backfill run of September 28, 2026/)).toBeVisible()
})

test('reduced motion shows the final state with replay off', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/pipeline')
  await expect(page.getByText(/^Weekly run of October 5, 2026/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Replay run' })).toBeDisabled()
  await expect(page.locator('.line-edge.is-active')).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('the timeline opens a stage, and the page names the newest weekly run in a sentence', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/pipeline')
  await expect(page.locator('.intro')).toContainText(/^The weekly run for 2026-W40 finished with a warning in /)
  await page.locator('.timeline-row', { hasText: 'Ingest + validate' }).getByRole('button').click()
  await expect(page.getByRole('complementary').getByRole('heading', { name: 'Ingest + validate' })).toBeVisible()
  await expect(page.locator('[data-node="ingest"]')).toHaveAttribute('aria-pressed', 'true')
})

test('a station says what its stage does and what happened, by hover and by keyboard', async ({ page }) => {
  await page.goto('/pipeline')
  await expect(page.getByText(/^Weekly run of October 5, 2026/)).toBeVisible({ timeout: 9000 })
  await page.locator('[data-node="ingest"]').hover()
  const card = page.getByRole('tooltip')
  await expect(card).toContainText('quarantines rows that fail validation')
  await expect(card).toContainText(/Succeeded in|Warning in/)
  await page.mouse.move(0, 0)
  await expect(card).toBeHidden()
  // The warned stage answers why, from its own message.
  await page.locator('[data-node="narrate"]').focus()
  await page.keyboard.press('Shift+Tab')
  await page.keyboard.press('Tab')
  await expect(card).toContainText('Why a warning?')
  await expect(page.locator('[data-node="narrate"]')).toHaveAttribute('aria-describedby', await card.getAttribute('id') ?? '')
  // A time row says what share of the run its stage took.
  await page.locator('.timeline-row button').first().hover()
  await expect(card).toContainText('of the run’s time')
})

test('links to the dbt lineage graph as a full page, outside the app router', async ({ page }) => {
  await page.goto('/pipeline')
  await expect(page.getByRole('link', { name: 'dbt lineage graph' })).toHaveAttribute('href', '/lineage/')
})
