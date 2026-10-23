// Play a deployment's recap video for at least two seconds in Chromium and WebKit.
// Usage: node tests/recap-playback.mjs https://<deployment>.advisor-pulse.pages.dev
// Needs the browsers: pnpm exec playwright install chromium webkit. Exits 1 if either fails.
import { chromium, webkit } from '@playwright/test'

const origin = process.argv[2]?.replace(/\/$/, '')
if (!origin) {
  console.error('usage: node tests/recap-playback.mjs <deployment URL>')
  process.exit(2)
}

let failed = false
for (const browserType of [chromium, webkit]) {
  const browser = await browserType.launch()
  const page = await browser.newPage()
  const requests = []
  page.on('response', (r) => {
    if (r.url().endsWith('/recap/recap.mp4')) {
      requests.push(`${r.request().headers().range ?? 'no range'} -> ${r.status()} ${r.headers()['content-type'] ?? ''}`)
    }
  })
  // Same origin as the site, so the page's Content-Security-Policy applies to the video too.
  await page.goto(`${origin}/recap/recap.json`)
  const result = await page.evaluate(async () => {
    const video = document.createElement('video')
    video.muted = true
    video.playsInline = true
    video.src = '/recap/recap.mp4'
    document.documentElement.appendChild(video)
    try {
      await Promise.race([video.play(), new Promise((_, reject) => setTimeout(() => reject(new Error('play() timed out')), 15_000))])
      await new Promise((resolve) => setTimeout(resolve, 2_500))
      return { currentTime: video.currentTime, duration: video.duration, error: video.error?.code ?? null }
    } catch (error) {
      return { currentTime: video.currentTime, duration: video.duration, error: String(error) }
    }
  })
  const ok = result.error === null && result.currentTime >= 2
  failed ||= !ok
  console.log(`${ok ? 'PASS' : 'FAIL'} ${browserType.name()} played ${result.currentTime.toFixed(2)} s of ${result.duration} s`
    + `${result.error === null ? '' : `, error ${result.error}`}; requests: ${requests.join(', ')}`)
  await browser.close()
}
process.exit(failed ? 1 : 0)
