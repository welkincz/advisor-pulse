import { readdir, readFile, mkdir, unlink, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { compile } from 'json-schema-to-typescript'

const web = fileURLToPath(new URL('../', import.meta.url))
const schemas = resolve(web, '../contracts/schemas')
const output = resolve(web, 'src/data/generated')
await mkdir(output, { recursive: true })
const check = process.argv.includes('--check')

const files = (await readdir(schemas)).filter((name) => name.endsWith('.schema.json')).sort()
const expected = new Set()
const stale = []
for (const file of files) {
  const schema = JSON.parse(await readFile(resolve(schemas, file), 'utf8'))
  const stem = file.replace('.schema.json', '')
  const name = stem.split(/[._-]/).map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join('')
  const types = await compile(schema, name, { bannerComment: `/* Generated from contracts/schemas/${file}. Do not edit. */\n` })
  const target = `${stem.replaceAll('.', '_')}.ts`
  expected.add(target)
  if (check) {
    const current = await readFile(resolve(output, target), 'utf8').catch(() => '')
    if (current !== types) stale.push(target)
  } else {
    await writeFile(resolve(output, target), types)
  }
}
for (const file of await readdir(output)) {
  if (file.endsWith('.ts') && !expected.has(file)) {
    if (check) stale.push(file)
    else await unlink(resolve(output, file))
  }
}
if (stale.length) {
  console.error(`Stale generated types: ${stale.join(', ')}`)
  process.exitCode = 1
} else {
  console.log(`${check ? 'Checked' : 'Generated'} ${files.length} TypeScript contract files.`)
}
