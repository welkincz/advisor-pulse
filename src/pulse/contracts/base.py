"""Base class and column introspection shared by every contract.

A contract is a pydantic model. Its *columns* are its fields, named by alias when one is set
(source systems use names like ``_EXTRACTED_AT`` that cannot be Python attributes).
Tabular contracts map to Arrow and DuckDB types from their annotations, so the generator,
ingestion and export all derive physical schemas from one definition.
"""

from __future__ import annotations

import types
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal, Union, get_args, get_origin

import pyarrow as pa
from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = "1.0.0"

ContractKind = Literal["table", "document"]


class Contract(BaseModel):
    """A row (``kind = "table"``) or a whole file (``kind = "document"``)."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=False,
        use_enum_values=False,
    )

    contract_name: ClassVar[str]
    contract_kind: ClassVar[ContractKind] = "table"
    contract_description: ClassVar[str] = ""


@dataclass(frozen=True)
class Column:
    name: str
    python_type: type
    nullable: bool
    description: str


def _strip_annotated(annotation: Any) -> Any:
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    return annotation


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    annotation = _strip_annotated(annotation)
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        nullable = len(args) != len(get_args(annotation))
        if len(args) != 1:
            raise TypeError(f"Unsupported union annotation: {annotation!r}")
        return _strip_annotated(args[0]), nullable
    return annotation, False


def columns(model: type[Contract]) -> list[Column]:
    """Columns of a tabular contract, in declaration order."""
    if model.contract_kind != "table":
        raise TypeError(f"{model.__name__} is a document contract, not a table")
    out: list[Column] = []
    for field_name, info in model.model_fields.items():
        base, nullable = _unwrap_optional(info.annotation)
        if not isinstance(base, type):
            raise TypeError(f"{model.__name__}.{field_name}: unsupported type {base!r}")
        out.append(
            Column(
                name=info.alias or field_name,
                python_type=base,
                nullable=nullable,
                description=info.description or "",
            )
        )
    return out


def column_names(model: type[Contract]) -> list[str]:
    return [c.name for c in columns(model)]


# bool must be checked before int (bool subclasses int); datetime before date.
_ARROW_TYPES: list[tuple[type, pa.DataType]] = [
    (bool, pa.bool_()),
    (StrEnum, pa.string()),
    (str, pa.string()),
    (int, pa.int64()),
    (float, pa.float64()),
    (datetime, pa.timestamp("us", tz="UTC")),
    (date, pa.date32()),
]

_DUCKDB_TYPES: list[tuple[type, str]] = [
    (bool, "BOOLEAN"),
    (StrEnum, "VARCHAR"),
    (str, "VARCHAR"),
    (int, "BIGINT"),
    (float, "DOUBLE"),
    (datetime, "TIMESTAMP WITH TIME ZONE"),
    (date, "DATE"),
]


def _lookup[T](python_type: type, table: list[tuple[type, T]]) -> T:
    for candidate, physical in table:
        if issubclass(python_type, candidate):
            return physical
    raise TypeError(f"No physical type for {python_type!r}")


def arrow_schema(model: type[Contract]) -> pa.Schema:
    """Arrow schema for a tabular contract (used for Parquet files)."""
    return pa.schema(
        [
            pa.field(c.name, _lookup(c.python_type, _ARROW_TYPES), nullable=c.nullable)
            for c in columns(model)
        ],
        metadata={
            b"contract": model.contract_name.encode(),
            b"schema_version": SCHEMA_VERSION.encode(),
        },
    )


def duckdb_columns(model: type[Contract]) -> list[tuple[str, str, bool]]:
    """``(name, duckdb_type, nullable)`` for a tabular contract (used for DDL)."""
    return [(c.name, _lookup(c.python_type, _DUCKDB_TYPES), c.nullable) for c in columns(model)]
