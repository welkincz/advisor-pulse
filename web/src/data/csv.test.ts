import { expect, it } from 'vitest'
import { csvCell, toCsv } from './csv'

it('quotes only cells that need it and doubles inner quotes', () => {
  expect(csvCell('Ontario')).toBe('Ontario')
  expect(csvCell('King & Bay, Toronto')).toBe('"King & Bay, Toronto"')
  expect(csvCell('say "hi"')).toBe('"say ""hi"""')
  expect(csvCell('two\nlines')).toBe('"two\nlines"')
  expect(csvCell(null)).toBe('')
  expect(csvCell(0.0123)).toBe('0.0123')
  expect(csvCell(-0.07)).toBe('-0.07')
  expect(csvCell('=HYPERLINK("x")')).toBe('"\'=HYPERLINK(""x"")"')
  expect(csvCell('@SUM(A1)')).toBe("'@SUM(A1)")
})

it('writes a header and CRLF rows', () => {
  expect(toCsv(['week', 'value'], [['2026-W41', 15.6], ['2026-W42', null]])).toBe('week,value\r\n2026-W41,15.6\r\n2026-W42,\r\n')
})
