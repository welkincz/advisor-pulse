# Advisor Pulse web scaffold

Run `make web-dev` from the repository root for the Vite route shells. During development,
`/data/*` serves matching files from `fixtures/exports/`. The weekly export pipeline will
create that directory; until then, the route shells do not show report data.

`make web-types` generates one committed TypeScript file per JSON Schema in
`contracts/schemas/`. `make web-check` checks those files for drift, runs ESLint and the
raw-colour guard, typechecks, builds, and runs Chromium smoke tests. The colour values
from charliebuild are confined to `src/theme/tokens.css`.

## Data layer (`src/data/`)

Pages read the weekly export through hooks from `src/data`: `useManifest`, `useOrgWeekly`,
`useWeeklyReport`, `useGeoWeekly`, `useRunLog` and `useNarrative`. Each returns
`{ status: 'loading' | 'empty' | 'ready' | 'error', data?, error?, retry }`; show
`<DataNotice onRetry={result.retry} />` on error.

- The manifest is fetched first. Its `summary` paints the overview KPIs without DuckDB.
- DuckDB-WASM loads in a worker on the first SQL query (the overview warms it when idle).
  The binary is over Cloudflare Pages' 25 MiB file limit, so it comes from jsDelivr at
  the exact `@duckdb/duckdb-wasm` version in `package.json`.
- Every Parquet and narrative file is checked against the manifest's sha256 before use.
- `pnpm -C web test` runs the same code in Node against `fixtures/exports`, with DuckDB's
  Node binding standing in for the WASM engine (`src/data/testing/fixtures.ts`).
