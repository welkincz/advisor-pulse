# Advisor Pulse

A weekly-batch BI pipeline that tracks client activity by advisors at **Maplecrest Bank**, a fictional
Canadian bank: synthetic multi-source extracts → incremental ingestion with quarantine → dbt star
schema on DuckDB → grounded AI weekly narratives → an in-browser dashboard at
[pulse.charliebuild.com](https://pulse.charliebuild.com).

> **All data is synthetic.** The bank, its people, clients, schemas and business rules are invented.
> Only public geography (Statistics Canada FSA boundaries, province names) is real.
> This is a **weekly batch report**, not a real-time system.

## Status

Under construction. Work is tracked as [GitHub issues](https://github.com/welkincz/advisor-pulse/issues)
across eight milestones; see [`docs/BACKLOG.md`](docs/BACKLOG.md).

## Docs

- [`docs/PLAN.md`](docs/PLAN.md): architecture, data dictionary, KPIs, data-quality rules, failure handling
- [`AGENTS.md`](AGENTS.md): how humans and coding agents work in this repo

## Quickstart

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). Node 22 and pnpm are needed once the web app lands.

```bash
make setup     # install dependencies
make check     # lint, types, tests, contracts
uv run pulse --help
```

`make help` lists every target. Targets whose code has not landed yet name the issue that implements them.

## License

MIT
