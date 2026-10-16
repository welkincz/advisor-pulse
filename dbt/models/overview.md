{% docs __overview__ %}

# Advisor Pulse

Model catalog and column lineage for the weekly warehouse behind the
[Maplecrest Bank dashboard](https://pulse.charliebuild.com/). Maplecrest Bank
is fictional. These pages are rebuilt with the weekly report and published at
`/lineage/` on that same site.

[Back to the dashboard](https://pulse.charliebuild.com/)

## Layers

Each folder builds into the warehouse schema of the same name.

| Layer | Schema | Materialization | What belongs here |
| --- | --- | --- | --- |
| Staging | `staging` | view | One model per source table. Rename to `snake_case`, cast, trim, and dedupe. No joins. |
| Intermediate | `intermediate` | table | Business logic: SCD2 advisor history, the weekly client book, and as-of attribution. |
| Marts | `marts` | table, contract enforced | Star schema (`dim_*`, `fct_*`) and weekly marts (`mart_*`) that the export reads. |

Sources are the warehouse tables in `raw`, `meta`, and `quarantine`.
`models/sources.yml` is generated from the pydantic contracts.

## Conventions

- One `.yml` per model, beside its `.sql`, with a description, column descriptions, and tests. Mart models also declare `data_type` on every column because the contract is enforced.
- Timestamps are UTC. Business dates use `America/Toronto`.
- Weeks are ISO weeks starting Monday. `iso_week_id` looks like `2026-W40`.
- `_sk` is a surrogate key. `_id` is a natural key.

## Lineage

The lineage graph is this project's DAG. Use the **View Lineage Graph** button to see parents and children: sources feed staging, staging feeds intermediate, and intermediate feeds marts.

{% enddocs %}
