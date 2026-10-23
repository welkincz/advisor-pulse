import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

// docs/design.md §3: three weights, through tokens only. tokens.css is the one place that holds numbers.
const SRC = join(import.meta.dirname, '..')
const TOKEN_FILE = 'theme/tokens.css'

// CSS `font-weight: x`, SVG/JSX attribute `font-weight="x"`, style object `fontWeight: x`, and the `font:` shorthand.
const WEIGHT = /\b(?:font-weight|fontWeight)\s*[:=]\s*\{?\s*['"]?([^;'"},\n]+)/g
const SHORTHAND = /(?:^|[\s;{])font\s*:\s*([^;}\n]+)/g
const ALLOWED = /^(?:var\(--weight-(?:regular|medium|strong)\)|inherit)$/

export function rawWeights(file: string, text: string): string[] {
  const found: string[] = []
  for (const [, value] of text.matchAll(WEIGHT)) {
    if (!ALLOWED.test(value.trim())) found.push(`${file}: ${value.trim()}`)
  }
  for (const [, value] of text.matchAll(SHORTHAND)) {
    if (/\b(?:[1-9]00|bold|bolder|lighter)\b/.test(value)) found.push(`${file}: font: ${value.trim()}`)
  }
  return found
}

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return sources(path)
    return /\.(css|tsx?)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : []
  })
}

describe('font weights', () => {
  it('route every weight in web/src through the three tokens', () => {
    const violations = sources(SRC)
      .map((path) => relative(SRC, path))
      .filter((file) => file !== TOKEN_FILE)
      .flatMap((file) => rawWeights(file, readFileSync(join(SRC, file), 'utf8')))
    expect(violations).toEqual([])
  })

  it('catches raw numbers, keywords and unknown tokens in every form', () => {
    expect(rawWeights('a.css', '.x { font-weight:700; }')).toEqual(['a.css: 700'])
    expect(rawWeights('a.css', '.x { font-weight: bold; }')).toEqual(['a.css: bold'])
    expect(rawWeights('a.css', '.x { font-weight: var(--weight-heavy); }')).toEqual(['a.css: var(--weight-heavy)'])
    expect(rawWeights('a.css', '.x { font: 600 1rem/1.2 serif; }')).toEqual(['a.css: font: 600 1rem/1.2 serif'])
    expect(rawWeights('a.tsx', "<p style={{ fontWeight: 600, margin: 0 }} />")).toEqual(['a.tsx: 600'])
    expect(rawWeights('a.tsx', '<text font-weight="700">x</text>')).toEqual(['a.tsx: 700'])
    expect(rawWeights('a.tsx', '<text fontWeight={500}>x</text>')).toEqual(['a.tsx: 500'])
  })

  it('accepts the three tokens', () => {
    const ok = '.a { font-weight: var(--weight-regular); } .b { font-weight: var(--weight-medium); } .c { font-weight: var(--weight-strong); }'
    expect(rawWeights('a.css', ok)).toEqual([])
    expect(rawWeights('a.tsx', "<p style={{ fontWeight: 'var(--weight-strong)' }} />")).toEqual([])
  })
})
