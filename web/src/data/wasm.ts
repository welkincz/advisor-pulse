import { type QueryEngine, plainRow } from './engine'

/**
 * DuckDB-WASM in a worker, loaded on first use so it never blocks the first paint.
 * The binary (~34 MB) is over Cloudflare Pages' 25 MiB file limit, so it comes from
 * jsDelivr at the exact version in package.json.
 */
export async function createWasmEngine(): Promise<QueryEngine> {
  const duckdb = await import('@duckdb/duckdb-wasm')
  const bundle = await duckdb.selectBundle(duckdb.getJsDelivrBundles())
  // A cross-origin worker script has to be started from a same-origin blob.
  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], { type: 'text/javascript' }),
  )
  const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), new Worker(workerUrl))
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker)
  URL.revokeObjectURL(workerUrl)
  const connection = await db.connect()
  return {
    async register(table, bytes) {
      await db.registerFileBuffer(`${table}.parquet`, bytes)
      await connection.query(`create or replace view ${table} as select * from read_parquet('${table}.parquet')`)
    },
    async query(sql) {
      const result = await connection.query(sql)
      return result.toArray().map((row) => plainRow(row.toJSON()))
    },
  }
}
