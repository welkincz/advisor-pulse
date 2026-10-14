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
