"""dbt/models/sources.yml is generated from the warehouse contracts and kept current."""

from __future__ import annotations

import yaml

from pulse.contracts import column_names
from pulse.dbt_sources import DBT_SOURCES, render
from pulse.warehouse import TABLES


def test_committed_sources_yml_is_current() -> None:
    assert DBT_SOURCES.read_text(encoding="utf-8") == render()


def test_every_warehouse_table_is_a_source_with_contract_columns() -> None:
    document = yaml.safe_load(render())
    declared = {
        f"{source['schema']}.{table['name']}": table
        for source in document["sources"]
        for table in source["tables"]
    }
    assert set(declared) == {spec.name for spec in TABLES}
    for spec in TABLES:
        table = declared[spec.name]
        assert table["description"]
        assert [c["name"] for c in table["columns"]] == column_names(spec.model)
        if spec.name.startswith("raw."):
            assert table["loaded_at_field"] == "_loaded_at"
            assert table["freshness"]["error_after"]["period"] == "day"
