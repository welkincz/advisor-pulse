// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { act } from 'react'
import { type Root, createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { type Recap, WeekRecap, loadRecap } from './WeekRecap'

declare global { var IS_REACT_ACT_ENVIRONMENT: boolean }
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const sample = readFileSync(join(import.meta.dirname, '../../../../video/src/sample.json'), 'utf8')
const recap = JSON.parse(sample) as Recap

/** A fetch that answers recap.json and recap.mp4 as given; anything else is a 404. */
function fetcher(json: Response | null, mp4: Response | null): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const url = String(input)
    const response = url.endsWith('recap.json') ? json : url.endsWith('recap.mp4') ? mp4 : null
    return response ?? new Response('not found', { status: 404 })
  }) as typeof fetch
}
const mp4 = () => new Response(null, { headers: { 'content-type': 'video/mp4' } })
const html = () => new Response('<!doctype html>', { headers: { 'content-type': 'text/html; charset=utf-8' } })

describe('loadRecap', () => {
  it('returns the recap when the video is there', async () => {
    expect((await loadRecap(fetcher(new Response(sample), mp4())))?.week).toBe(recap.week)
  })

  it('returns null when the video path falls through to the site page', async () => {
    expect(await loadRecap(fetcher(new Response(sample), html()))).toBeNull()
  })

  it('returns null when the video or the recap is missing', async () => {
    expect(await loadRecap(fetcher(new Response(sample), null))).toBeNull()
    expect(await loadRecap(fetcher(null, mp4()))).toBeNull()
  })

  it('returns null for JSON that is not a recap, or a failed request', async () => {
    expect(await loadRecap(fetcher(new Response(JSON.stringify({ week: '2026-W40' })), mp4()))).toBeNull()
    expect(await loadRecap(fetcher(new Response('<!doctype html>'), mp4()))).toBeNull()
    expect(await loadRecap((() => Promise.reject(new Error('offline'))) as typeof fetch)).toBeNull()
  })
})

describe('WeekRecap', () => {
  let container: HTMLDivElement
  let root: Root
  beforeEach(() => {
    container = document.createElement('div')
    root = createRoot(container)
  })
  afterEach(() => act(() => root.unmount()))

  it('shows a player that does not play on its own, with a closed transcript', async () => {
    await act(async () => root.render(<WeekRecap recap={recap} />))
    const video = container.querySelector('video')!
    expect(video.getAttribute('src')).toMatch(/recap\/recap\.mp4$/)
    expect(video.autoplay).toBe(false)
    expect(container.querySelector('details')!.open).toBe(false)
  })

  it('swaps a video that fails for the poster, one plain line and the open transcript', async () => {
    await act(async () => root.render(<WeekRecap recap={recap} />))
    await act(async () => { container.querySelector('video')!.dispatchEvent(new Event('error')) })
    expect(container.querySelector('video')).toBeNull()
    expect(container.querySelector('img.recap-video')!.getAttribute('src')).toMatch(/recap\/poster\.jpg$/)
    expect(container.querySelector('[role="status"]')!.textContent).toBe('The video did not load. The transcript below says what it shows.')
    const details = container.querySelector('details')!
    expect(details.open).toBe(true)
    expect(details.textContent).toContain(recap.headline)
  })

  it('drops the poster too when it is missing, and keeps the transcript', async () => {
    await act(async () => root.render(<WeekRecap recap={recap} />))
    await act(async () => { container.querySelector('video')!.dispatchEvent(new Event('error')) })
    await act(async () => { container.querySelector('img')!.dispatchEvent(new Event('error')) })
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('details')!.textContent).toContain(recap.headline)
  })
})
