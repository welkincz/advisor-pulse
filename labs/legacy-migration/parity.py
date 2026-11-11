"""Reusable source-to-target parity harness (#324 lab).

Compares two row sets keyed on the same columns: row counts, duplicate keys, the key-set
difference (missing from / extra in the source) and a column-by-column compare with a
per-column tolerance. Rows are plain dicts, so any source can be fed in. Standard library only.
"""

from __future__ import annotations

import math
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

Row = Mapping[str, Any]
Key = tuple[Any, ...]


@dataclass(frozen=True)
class ColumnRule:
    tolerance: float = 0.0  # absolute; 0 means exact
    source_null_sentinel: Any = None  # a source value read as null before comparing


@dataclass(frozen=True)
class Spec:
    keys: tuple[str, ...]
    columns: Mapping[str, ColumnRule]


@dataclass(frozen=True)
class SourceMapping:
    """Legacy-to-target mapping decisions loaded from a TOML file."""

    keys: Mapping[str, str]  # target key column -> format template over source columns
    rename: Mapping[str, str]  # source column -> target column
    rules: Mapping[str, ColumnRule]

    @classmethod
    def load(cls, path: Path) -> SourceMapping:
        data = tomllib.loads(path.read_text())
        rules = {name: ColumnRule(**rule) for name, rule in data.get("columns", {}).items()}
        return cls(keys=data["keys"], rename=data["rename"], rules=rules)

    def apply(self, rows: Iterable[Row]) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            mapped = {key: tpl.format(**row) for key, tpl in self.keys.items()}
            mapped.update({target: row[source] for source, target in self.rename.items()})
            out.append(mapped)
        return out

    def spec(self, *, strict: bool = False) -> Spec:
        """Strict ignores the tolerance and sentinel decisions, to show what they resolve."""
        columns = {
            col: ColumnRule() if strict else self.rules.get(col, ColumnRule())
            for col in self.rename.values()
        }
        return Spec(keys=tuple(self.keys), columns=columns)


@dataclass(frozen=True)
class Mismatch:
    key: Key
    column: str
    source: Any
    target: Any

    @property
    def diff(self) -> float | None:
        if _is_num(self.source) and _is_num(self.target):
            return float(self.source) - float(self.target)
        return None


@dataclass
class Report:
    keys: tuple[str, ...]
    source_rows: int
    target_rows: int
    duplicate_source_keys: list[Key] = field(default_factory=list)
    duplicate_target_keys: list[Key] = field(default_factory=list)
    missing_in_source: list[Key] = field(default_factory=list)
    extra_in_source: list[Key] = field(default_factory=list)
    mismatches: list[Mismatch] = field(default_factory=list)
    compared_cells: int = 0

    @property
    def ok(self) -> bool:
        return not (
            self.duplicate_source_keys
            or self.duplicate_target_keys
            or self.missing_in_source
            or self.extra_in_source
            or self.mismatches
            or self.source_rows != self.target_rows
        )

    def render(self, limit: int = 50) -> str:
        fmt = ", ".join
        lines = [
            f"PARITY {'PASS' if self.ok else 'FAIL'}  keys=({fmt(self.keys)})",
            f"  rows        source={self.source_rows}  target={self.target_rows}",
            f"  key diff    missing_in_source={len(self.missing_in_source)}  "
            f"extra_in_source={len(self.extra_in_source)}",
            f"  duplicates  source={len(self.duplicate_source_keys)}  "
            f"target={len(self.duplicate_target_keys)}",
            f"  cells       compared={self.compared_cells}  mismatched={len(self.mismatches)}",
        ]
        for label, keys in (
            ("missing in source", self.missing_in_source),
            ("extra in source", self.extra_in_source),
            ("duplicate source key", self.duplicate_source_keys),
            ("duplicate target key", self.duplicate_target_keys),
        ):
            lines += [f"  {label}: {_key(self.keys, k)}" for k in keys[:limit]]
        for m in self.mismatches[:limit]:
            diff = "" if m.diff is None else f"  diff={m.diff:+g}"
            lines.append(
                f"  mismatch {_key(self.keys, m.key)} {m.column}: "
                f"source={m.source!r} target={m.target!r}{diff}"
            )
        hidden = max(0, len(self.mismatches) - limit)
        if hidden:
            lines.append(f"  … {hidden} more mismatches")
        return "\n".join(lines)


def reconcile(source: Iterable[Row], target: Iterable[Row], spec: Spec) -> Report:
    src, src_dups, n_src = _index(source, spec.keys)
    tgt, tgt_dups, n_tgt = _index(target, spec.keys)
    report = Report(
        keys=spec.keys,
        source_rows=n_src,
        target_rows=n_tgt,
        duplicate_source_keys=src_dups,
        duplicate_target_keys=tgt_dups,
        missing_in_source=sorted(tgt.keys() - src.keys(), key=_sort_key),
        extra_in_source=sorted(src.keys() - tgt.keys(), key=_sort_key),
    )
    for key in sorted(src.keys() & tgt.keys(), key=_sort_key):
        for column, rule in spec.columns.items():
            left, right = src[key].get(column), tgt[key].get(column)
            if rule.source_null_sentinel is not None and left == rule.source_null_sentinel:
                left = None
            report.compared_cells += 1
            if not _equal(left, right, rule.tolerance):
                report.mismatches.append(Mismatch(key, column, src[key].get(column), right))
    return report


def _index(rows: Iterable[Row], keys: tuple[str, ...]) -> tuple[dict[Key, Row], list[Key], int]:
    # A duplicate key keeps only its last row for the cell compare; the duplicate itself is
    # listed in the report and fails it, so the earlier rows are reported, not compared.
    index: dict[Key, Row] = {}
    dups: list[Key] = []
    count = 0
    for row in rows:
        count += 1
        key = tuple(row[k] for k in keys)
        if key in index:
            dups.append(key)
        index[key] = row
    return index, dups, count


def _equal(left: Any, right: Any, tolerance: float) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if _is_num(left) and _is_num(right):
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=tolerance + 1e-9)
    return bool(left == right)


def _is_num(value: Any) -> bool:
    return isinstance(value, int | float | Decimal) and not isinstance(value, bool)


def _sort_key(key: Key) -> tuple[str, ...]:
    return tuple(str(part) for part in key)


def _key(names: tuple[str, ...], key: Key) -> str:
    return "(" + ", ".join(f"{n}={v}" for n, v in zip(names, key, strict=True)) + ")"
