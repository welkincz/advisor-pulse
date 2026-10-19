import { readdir, readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { gzipSync } from 'node:zlib'

const limit = 350 * 1024
const assets = resolve(import.meta.dirname, '../dist/assets')
const files = (await readdir(assets)).filter((name) => /\.(?:m?js)$/.test(name))
if (files.length === 0) throw new Error('No built JavaScript assets found')

const sizes = await Promise.all(files.map(async (name) => ({
  name,
  bytes: gzipSync(await readFile(resolve(assets, name))).length,
})))
const total = sizes.reduce((sum, file) => sum + file.bytes, 0)
console.log(`JavaScript gzip: ${total} / ${limit} bytes (${files.length} files; WASM excluded)`)
if (total > limit) {
  console.error('JS gzip budget exceeded. Largest bundles:')
  for (const file of sizes.sort((a, b) => b.bytes - a.bytes).slice(0, 5)) {
    console.error(`  ${file.bytes} bytes  ${file.name}`)
  }
  process.exitCode = 1
}
