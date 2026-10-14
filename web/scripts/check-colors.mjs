import { readdir, readFile } from 'node:fs/promises'
import { relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const source = resolve(fileURLToPath(new URL('../src/', import.meta.url)))
const rawHex = /#[\da-f]{3,8}\b/gi

export async function findRawColors(root) {
  const violations = []
  async function visit(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const path = resolve(dir, entry.name)
      if (entry.isDirectory()) await visit(path)
      else if (/\.(css|ts|tsx)$/.test(entry.name) && entry.name !== 'tokens.css') {
        const matches = (await readFile(path, 'utf8')).match(rawHex) ?? []
        for (const value of matches) violations.push(`${relative(root, path)}: ${value}`)
      }
    }
  }
  await visit(root)
  return violations.sort()
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const violations = await findRawColors(source)
  if (violations.length) {
    console.error(`Raw hex colours outside tokens.css:\n${violations.join('\n')}`)
    process.exitCode = 1
  }
}
