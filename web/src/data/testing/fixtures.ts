/** Test doubles: DuckDB's Node binding as the engine, and fetch served from fixtures/exports. */
import { DuckDBInstance } from '@duckdb/node-api'
import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { type QueryEngine, plainRow } from '../engine'
import type { Fetch } from '../manifest'
import { PulseData } from '../store'

export const FIXTURES = resolve(import.meta.dirname, '../../../../fixtures/exports')

export async function createNodeEngine(): Promise<QueryEngine> {
  const connection = await (await DuckDBInstance.create(':memory:')).connect()
  const dir = await mkdtemp(join(tmpdir(), 'pulse-data-'))
  return {
    async register(table, bytes) {
      const path = join(dir, `${table}.parquet`)
      await writeFile(path, bytes)
      await connection.run(`create or replace view ${table} as select * from read_parquet('${path}')`)
    },
    async query(sql) {
      return (await connection.runAndReadAll(sql)).getRowObjectsJS().map(plainRow)
    },
  }
}

/** Serves `/data/<file>` from fixtures/exports; `override` can replace or break single files. */
export function fixtureFetch(override: Record<string, () => Response | Promise<Response>> = {}): Fetch & { calls: string[] } {
  const calls: string[] = []
  const fetcher = async (url: string) => {
    calls.push(url)
    const name = url.replace(/^\/data\//, '')
    if (override[name]) return override[name]()
    try {
      return new Response(await readFile(join(FIXTURES, name)))
    } catch {
      return new Response('Not found', { status: 404 })
    }
  }
  return Object.assign(fetcher, { calls })
}

export function fixtureData(fetcher: Fetch = fixtureFetch(), engine: () => Promise<QueryEngine> = createNodeEngine): PulseData {
  return new PulseData({ fetch: fetcher, engine })
}
