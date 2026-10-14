import assert from 'node:assert/strict'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
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
