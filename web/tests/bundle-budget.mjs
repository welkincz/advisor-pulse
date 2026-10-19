// Per-route initial-load JS budget (PLAN.md §12): JS ≤ 350 KB gzip per route on
// first load, excluding WASM. Lazy chunks count only when the route requests them.
// Expects a production build in dist/ with fixture exports staged in dist/data.
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { gzipSync } from 'node:zlib'
import { chromium } from '@playwright/test'

const limit = 350 * 1024
const port = 4174
const web = resolve(import.meta.dirname, '..')
const dist = resolve(web, 'dist')
const routes = ['/', '/r/ON', '/r/ON/d/GTA/b/BR-0412/a/AD-001', '/map', '/pipeline', '/quality', '/case-study']
if (!existsSync(resolve(dist, 'data/manifest.json'))) throw new Error('Stage fixture exports in dist/data first')

const server = spawn('pnpm', ['exec', 'vite', 'preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
  cwd: web,
  stdio: 'ignore',
})
const base = `http://127.0.0.1:${port}`
for (let i = 0; ; i++) {
  try {
    if ((await fetch(base)).ok) break
  } catch {
    // not listening yet
  }
  if (i > 100) throw new Error('vite preview did not start')
  await new Promise((done) => setTimeout(done, 100))
}

const gzipped = new Map()
async function gzipBytes(path) {
  if (!gzipped.has(path)) gzipped.set(path, gzipSync(await readFile(resolve(dist, `.${path}`))).length)
  return gzipped.get(path)
}

const browser = await chromium.launch()
let failed = false
try {
  for (const route of routes) {
    const page = await browser.newPage()
    const scripts = new Set()
    page.on('response', (response) => {
      const { pathname } = new URL(response.url())
      if (pathname.startsWith('/assets/') && /\.m?js$/.test(pathname)) scripts.add(pathname)
    })
    await page.goto(base + route, { waitUntil: 'networkidle' })
    await page.waitForTimeout(500)
    await page.close()
    let total = 0
    for (const path of scripts) total += await gzipBytes(path)
    const ok = total <= limit
    failed ||= !ok
    console.log(`${ok ? 'ok  ' : 'OVER'} ${route.padEnd(34)} ${String(total).padStart(8)} / ${limit} bytes gzip (${scripts.size} files)`)
    if (!ok) {
      const largest = await Promise.all([...scripts].map(async (path) => [await gzipBytes(path), path]))
      for (const [bytes, path] of largest.sort((a, b) => b[0] - a[0]).slice(0, 5)) console.log(`       ${bytes}  ${path}`)
    }
  }
} finally {
  await browser.close()
  server.kill()
}
if (failed) {
  console.error('Initial-load JS budget exceeded on at least one route.')
  process.exitCode = 1
}
