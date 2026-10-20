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
// Every inline script, with or without attributes; scripts with src are covered by 'self'.
for (const [, body] of html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)) {
  const hash = `'sha256-${createHash('sha256').update(body).digest('base64')}'`
  if (!csp.includes(hash)) throw new Error(`Inline script hash ${hash} is not in the CSP`)
}

const port = Number(process.env.CSP_CHECK_PORT ?? 4175)
const server = spawn('pnpm', ['exec', 'vite', 'preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: root, stdio: 'ignore' })
const base = `http://127.0.0.1:${port}`
let up = false
for (let i = 0; i < 50 && !up; i++) {
  try { up = (await fetch(base)).ok } catch { /* not up yet */ }
  if (!up) await new Promise((r) => setTimeout(r, 200))
}
if (!up) {
  server.kill()
  throw new Error(`vite preview did not start on port ${port}; set CSP_CHECK_PORT if it is taken`)
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

/** Load `path` under `policy`; true when the DuckDB-backed marker renders with no violation. */
async function renders(path, ready, policy, log) {
  const page = await browser.newPage()
  await page.addInitScript(() => {
    window.__csp = []
    document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`))
  })
  await page.route('**/*', async (route) => {
    if (route.request().resourceType() !== 'document') return route.fallback()
    const response = await route.fetch()
    return route.fulfill({ response, headers: { ...response.headers(), 'content-security-policy': policy } })
  })
  const errors = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto(base + path)
  let shown = true
  try { await page.waitForSelector(ready, { timeout: 30_000 }) } catch { shown = false }
  if (shown) await page.waitForTimeout(1500)
  const violations = await page.evaluate(() => window.__csp)
  if (log) console.log(`${shown && !violations.length ? 'ok  ' : 'FAIL'} ${path}${shown ? '' : `: never showed ${ready}`}${violations.length ? `: ${violations.join('; ')}` : ''}${!shown && errors.length ? ` ${errors.join(' | ')}` : ''}`)
  await page.close()
  return shown && !violations.length
}
try {
  for (const [path, ready] of pages) if (!(await renders(path, ready, csp, true))) failures++
  // Self-test: the same check must fail when DuckDB's extension host is not allowed, or it
  // has stopped measuring the header (that host is what broke the first draft, #187).
  const broken = csp.replace(' https://extensions.duckdb.org', '')
  if (broken === csp) throw new Error('Expected extensions.duckdb.org in connect-src')
  if (await renders('/quality', '.rule-list button', broken, false)) {
    console.log('FAIL self-test: the site rendered without the DuckDB extension host, so the check is not testing the CSP')
    failures++
  } else console.log('ok   self-test: without extensions.duckdb.org the check fails, as it should')
} finally {
  await browser.close()
  server.kill()
}
process.exitCode = failures ? 1 : 0
