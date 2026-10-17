import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'

const exportsDir = resolve(import.meta.dirname, '../../fixtures/exports')
test.beforeEach(async ({ page }) => {
  await page.route('http://127.0.0.1:43719/data/**', (route) => {
    const file = new URL(route.request().url()).pathname.split('/data/')[1]
    return route.fulfill({ path: resolve(exportsDir, file) })
  })
})

const levels = [
  ['/r/ON', 'Region', 'Ontario'],
  ['/r/ON/d/GTA', 'District', null],
  ['/r/ON/d/GTA/b/BR-0101', 'Branch', null],
  ['/r/ON/d/GTA/b/BR-0101/a/ADV-10003', 'Advisor', 'ADV-10003'],
] as const

for (const [path, level, name] of levels) {
  test(`${level} deep link renders KPIs on a fresh load`, async ({ page }) => {
    await page.goto(path)
    await expect(page.getByText(level, { exact: true })).toBeVisible()
    if (name) await expect(page.getByRole('heading', { level: 1, name })).toBeVisible()
    await expect(page.locator('[data-kpi="ACT_PER_ADV"]')).toContainText('Activities per advisor')
    await expect(page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('listitem')).toHaveCount(levels.findIndex(([p]) => p === path) + 2)
  })
}

test('children drill down; breadcrumb and back button return', async ({ page }) => {
  await page.goto('/r/ON')
  await page.getByRole('table').getByRole('link').first().click()
  await expect(page).toHaveURL(/\/r\/ON\/d\/[A-Z]+$/)
  await expect(page.getByText('District', { exact: true })).toBeVisible()
  await page.goBack()
  await expect(page).toHaveURL(/\/r\/ON$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Ontario' })).toBeVisible()
  await page.goto('/r/ON/d/GTA/b/BR-0101')
  await page.getByRole('navigation', { name: 'Breadcrumb' }).getByRole('link', { name: 'Ontario' }).click()
  await expect(page).toHaveURL(/\/r\/ON$/)
})

test('the week lives in the URL and follows the drill', async ({ page }) => {
  await page.goto('/r/ON')
  await page.getByRole('combobox', { name: /^Week/ }).selectOption('2026-W39')
  await expect(page).toHaveURL(/\?week=2026-W39$/)
  await expect(page.getByRole('heading', { name: 'Ontario, week 2026-W39' })).toBeVisible()
  await expect(page.getByRole('table')).toContainText('week 2026-W39')
  const child = page.getByRole('table').getByRole('link').first()
  await expect(child).toHaveAttribute('href', /\?week=2026-W39$/)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Ontario, week 2026-W39' })).toBeVisible()
})

test('children sort by any KPI from the keyboard at 375 px', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto('/r/ON')
  const picker = page.getByRole('combobox', { name: /^Rank by/ })
  await picker.focus()
  await picker.selectOption('NO_SHOW_RATE')
  await expect(page.getByRole('table')).toContainText('No-show rate under Ontario')
  await page.getByRole('table').getByRole('link').first().focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/r\/ON\/d\//)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})
