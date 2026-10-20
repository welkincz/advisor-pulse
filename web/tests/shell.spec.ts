import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'

const exportsDir = resolve(import.meta.dirname, '../../fixtures/exports')
test.beforeEach(async ({ page }) => {
  await page.route('http://127.0.0.1:43719/data/**', (route) => {
    const file = new URL(route.request().url()).pathname.split('/data/')[1]
    return route.fulfill({ path: resolve(exportsDir, file) })
  })
})

test('the skip link moves focus past the header to the report', async ({ page }) => {
  await page.goto('/pipeline')
  await page.keyboard.press('Tab')
  const skip = page.getByRole('link', { name: 'Skip to the report' })
  await expect(skip).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('#main')).toBeFocused()
})

test('the header names the report week and the run behind it', async ({ page }) => {
  await page.goto('/')
  const freshness = page.locator('.freshness')
  await expect(freshness).toContainText('2026-W40')
  await expect(freshness).toContainText('run Oct 5')
  await expect(freshness).toHaveAttribute('href', '/pipeline')
})

test('the palette opens from the keyboard, searches the network and navigates', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.freshness')).toBeVisible()
  await page.keyboard.press('/')
  const dialog = page.getByRole('dialog', { name: /Jump to/ })
  await expect(dialog).toBeVisible()
  const input = dialog.getByRole('combobox', { name: 'Search' })
  await expect(input).toBeFocused()
  await input.fill('gta')
  await expect(dialog.getByRole('option').first()).toContainText('GTA')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/r\/ON\/d\/GTA$/)
  await expect(dialog).toBeHidden()
  await page.keyboard.press('Control+k')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('combobox', { name: 'Search' }).fill('show rate')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/\?kpi=SHOW_RATE$/)
  await page.keyboard.press('Control+k')
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})

test('the colour scheme can be chosen, survives a reload, and returns to the system', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'light' })
  await page.goto('/')
  const toggle = page.locator('.theme-toggle')
  await expect(toggle).toHaveAccessibleName(/Colour scheme: System/)
  await toggle.click()
  await toggle.click()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe('dark')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  await page.locator('.theme-toggle').click()
  await expect(page.locator('html')).not.toHaveAttribute('data-theme', /./)
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe('light')
})
