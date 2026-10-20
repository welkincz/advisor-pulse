// Load the built site under the Content-Security-Policy from public/_headers and fail on any
// violation. Pages serves that header in production; `vite preview` does not, so this check
// adds it to every document response. DuckDB-WASM comes from jsDelivr, as it does live.
// Usage (after `pnpm build` and staging fixture exports in dist/data): node tests/csp-check.mjs
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { chromium } from '@playwright/test'

const root = resolve(import.meta.dirname, '..')
const headers = readFileSync(resolve(root, 'public/_headers'), 'utf8')
const csp = /Content-Security-Policy: (.+)/.exec(headers)?.[1]
if (!csp) throw new Error('No Content-Security-Policy in public/_headers')

// The pre-paint theme script is allowed by hash; a changed script must change the header too.
const html = readFileSync(resolve(root, 'dist/index.html'), 'utf8')
for (const [, body] of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) {
  const hash = `'sha256-${createHash('sha256').update(body).digest('base64')}'`
  if (!csp.includes(hash)) throw new Error(`Inline script hash ${hash} is not in the CSP`)
}

const port = 4175
const server = spawn('pnpm', ['exec', 'vite', 'preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: root, stdio: 'ignore' })
const base = `http://127.0.0.1:${port}`
for (let i = 0; i < 50; i++) {
  try { if ((await fetch(base)).ok) break } catch { /* not up yet */ }
  await new Promise((r) => setTimeout(r, 200))
}

const pages = [
  // Each marker needs DuckDB-WASM, so a blocked worker or wasm compile shows up as a timeout.
  ['/', '.trend-line[d^="M"]'],
  ['/map', '.map-rows li'],
  ['/quality', '.rule-list button'],
  ['/pipeline', '.line-diagram'],
]
const browser = await chromium.launch()
let failures = 0
try {
  for (const [path, ready] of pages) {
    const page = await browser.newPage()
    await page.addInitScript(() => {
      window.__csp = []
      document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`))
    })
    await page.route('**/*', async (route) => {
      if (route.request().resourceType() !== 'document') return route.fallback()
      const response = await route.fetch()
      return route.fulfill({ response, headers: { ...response.headers(), 'content-security-policy': csp } })
    })
    const errors = []
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
    page.on('pageerror', (e) => errors.push(e.message))
    await page.goto(base + path)
    try {
      await page.waitForSelector(ready, { timeout: 30_000 })
    } catch {
      console.log(`FAIL ${path}: never showed ${ready}; ${(await page.evaluate(() => window.__csp)).join('; ')} ${errors.join(' | ')}`)
      failures++
      await page.close()
      continue
    }
    await page.waitForTimeout(1500)
    const violations = await page.evaluate(() => window.__csp)
    console.log(`${violations.length ? 'FAIL' : 'ok  '} ${path}${violations.length ? `: ${violations.join('; ')}` : ''}`)
    failures += violations.length
    await page.close()
  }
} finally {
  await browser.close()
  server.kill()
}
process.exitCode = failures ? 1 : 0
