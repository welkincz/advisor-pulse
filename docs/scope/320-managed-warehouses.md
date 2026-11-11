# Out of scope: Snowflake, BigQuery and Redshift

- Status: Decided by the owner, 2026-11-11 ([decision on #320](https://github.com/welkincz/advisor-pulse/issues/320#issuecomment-6804403662))
- Issue: #320 (gap found by #299)

## Decision

Advisor Pulse stays on DuckDB. It will not run its models on Snowflake, BigQuery, Redshift
or another managed warehouse. The reviewer map keeps this competency graded **missing**.

## Why

- **It needs a cloud account (often paid beyond free tiers).** Credits, credentials, roles
  and warehouse sizing are a large part of the skill, and a public synthetic project has none
  of them. A trial account that expires would leave links that stop working.
- **DuckDB is the design, not a stand-in.** The same SQL engine runs in the pipeline and in
  the browser (DuckDB-WASM), so the site needs no backend and there is no dialect gap between
  the pipeline and the site. At about 2.2 million activity rows a single machine is enough
  ([baseline](../baseline.md)).
- **Names are not evidence.** The source called "Snowflake" is local Parquet files written by
  the generator. It imitates an extract, not a Snowflake connection, and is not claimed as
  Snowflake experience.

## What the project does show

Warehouse modelling that does not depend on the engine: a dbt star schema with enforced
contracts, SCD2 history from events and reconciled roll-ups, all built in CI on fixtures.
The case study lists what would change at real scale, including the warehouse
([case study](../case-study.md)).

## If it is revisited

The honest route is a separate lab that builds the same dbt project against a managed
warehouse, compares mart hashes with the DuckDB build and records cost and wall time, kept
out of the weekly pipeline. Nothing here claims managed-warehouse operations.
