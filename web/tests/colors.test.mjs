import assert from 'node:assert/strict'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'

import { findRawColors } from '../scripts/check-colors.mjs'

test('rejects raw hex outside tokens.css', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'pulse-colors-'))
  try {
    await writeFile(join(dir, 'component.css'), 'color: #fff;')
    assert.deepEqual(await findRawColors(dir), ['component.css: #fff'])
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
})

test('only theme/tokens.css may define raw hex', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'pulse-colors-'))
  try {
    await mkdir(join(dir, 'theme'))
    await mkdir(join(dir, 'features'))
    await writeFile(join(dir, 'theme/tokens.css'), 'color: #fff;')
    await writeFile(join(dir, 'features/tokens.css'), 'color: #abc;')
    assert.deepEqual(await findRawColors(dir), ['features/tokens.css: #abc'])
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
})

test('the system dark block and the chosen dark block hold the same tokens', async () => {
  const { readFile } = await import('node:fs/promises')
  const css = await readFile(new URL('../src/theme/tokens.css', import.meta.url), 'utf8')
  const block = (selector) => {
    const start = css.indexOf(selector)
    assert.ok(start >= 0, `missing ${selector}`)
    const open = css.indexOf('{', start)
    const close = css.indexOf('}', open)
    return css.slice(open + 1, close).split('\n').map((line) => line.trim()).filter(Boolean).join('\n')
  }
  assert.equal(block(":root:not([data-theme='light'])"), block(":root[data-theme='dark']"))
})
