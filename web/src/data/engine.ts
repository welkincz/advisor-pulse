/** The SQL engine behind the data layer: DuckDB-WASM in the browser, DuckDB's Node binding in tests. */

export type Row = Record<string, unknown>

export interface QueryEngine {
  /** Make `bytes` (a Parquet file) queryable as the view `table`. */
  register(table: string, bytes: Uint8Array): Promise<void>
  query(sql: string): Promise<Row[]>
}

/** DuckDB returns BIGINT as bigint; every count in the contracts fits a JS number. */
export function plainRow(row: Row): Row {
  const out: Row = {}
  for (const [key, value] of Object.entries(row)) out[key] = typeof value === 'bigint' ? Number(value) : value
  return out
}

/** A single-quoted SQL string literal. Callers pass only node IDs, codes and week IDs. */
export function sqlString(value: string): string {
  return `'${value.replaceAll("'", "''")}'`
}
