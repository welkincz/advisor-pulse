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
  await expect(page.locator('.react-flow__node')).toHaveCount(18)
  const replay = page.getByRole('button', { name: 'Replay run' })
  await expect(replay).toBeDisabled()
  await expect(page.getByText(/^Weekly run of October 5, 2026/)).toBeVisible({ timeout: 9000 })
  await expect(page.locator('.react-flow__node[data-id="narrate"]')).toContainText('Warning')
  await replay.click()
  await expect(page.getByText(/^Replaying weekly run of October 5, 2026/)).toBeVisible()
})

test('a retried stage opens a panel with each attempt; checks list their results', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/pipeline')
  await page.getByRole('button', { name: /2026-W39/ }).click()
  // Nodes off the canvas edge cannot be clicked, so the mouse takes the leftmost stage and
  // the keyboard (focus, Enter) reaches the rest.
  await page.locator('.react-flow__node[data-id="restore_state"]').click()
  const panel = page.getByRole('complementary')
  await expect(panel.getByRole('heading', { name: 'Restore state' })).toBeVisible()
  await page.locator('.react-flow__node[data-id="ingest"]').focus()
  await page.keyboard.press('Enter')
  await expect(panel.getByRole('heading', { name: 'Ingest + validate' })).toBeVisible()
  await expect(panel).toContainText('after 2 attempts')
  await expect(panel.locator('tbody tr')).toHaveCount(2)
  await expect(panel).toContainText('Failed')
  await page.keyboard.press('Escape')
  await expect(panel).toHaveCount(0)
  await page.locator('.react-flow__node[data-id="checks"]').focus()
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

test('reduced motion shows the final state with replay off', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/pipeline')
  await expect(page.getByText(/^Weekly run of October 5, 2026/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Replay run' })).toBeDisabled()
  await expect(page.locator('.pipe-particle')).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
