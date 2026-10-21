"""The weekly recap video's input: a small JSON read from the published export.

It is derived only from contracted export files (``weekly_report.parquet``, ``manifest.json``
and ``narratives/<week>.json``), so the video shows exactly the numbers the site shows. The
Remotion composition in ``video/`` reads it as its input props (``video/src/props.ts``).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from pulse.contracts.enums import KpiCode
from pulse.narrative.prompt import KPI_LABELS, LOWER_IS_BETTER, RATE_KPIS

RECAP_VERSION = 1
# The four measures the video counts up, in the order the site's board lists them.
HEADLINE_KPIS = (KpiCode.ACT_PER_ADV, KpiCode.CALLS_OUT, KpiCode.APPT_BOOKED, KpiCode.SHOW_RATE)
# The measure regions are ranked on, as in the Overview's "What moved".
RANKED_KPI = KpiCode.ACT_PER_ADV
AVERAGES = frozenset({KpiCode.ACT_PER_ADV, KpiCode.AVG_MEET_MIN})
MAX_FLAGGED = 3


def format_kpi(code: KpiCode, value: float | None) -> str:
    """The value as the site prints it (web/src/data/kpi.ts ``formatKpi``)."""
    if value is None:
        return "–"
    if code in RATE_KPIS:
        return f"{value * 100:.1f}%"
    if code in AVERAGES or not float(value).is_integer():
        return f"{value:.1f}"
    return f"{int(value):,}"


def week_dates(iso_week_id: str) -> str:
    """'October 12 to 18, 2026': Monday to Sunday of the ISO week, as the site's header says."""
    year, week = int(iso_week_id[:4]), int(iso_week_id[-2:])
    monday, sunday = date.fromisocalendar(year, week, 1), date.fromisocalendar(year, week, 7)
    if monday.month == sunday.month:
        return f"{monday:%B} {monday.day} to {sunday.day}, {sunday.year}"
    if monday.year == sunday.year:
        return f"{monday:%B} {monday.day} to {sunday:%B} {sunday.day}, {sunday.year}"
    return f"{monday:%B} {monday.day}, {monday.year} to {sunday:%B} {sunday.day}, {sunday.year}"


def _better(code: KpiCode) -> str:
    return "lower" if code in LOWER_IS_BETTER else "higher"


# The national headline, ported from web/src/features/overview/headline.ts so the video and the
# Overview say the same thing. Keep the two in step (tests/export/test_recap.py pins examples).
NOTABLE_GAP = 8


def _moved(code: KpiCode, value: float | None, wow: float | None) -> str:
    if wow is None:
        return f"was {format_kpi(code, value)}"
    if abs(wow) < 0.005:
        return f"held steady at {format_kpi(code, value)}"
    return f"{'rose' if wow > 0 else 'fell'} {abs(wow) * 100:.1f}% to {format_kpi(code, value)}"


def extreme_since(series: list[tuple[str, float | None, float | None]], week: str) -> str:
    """'the lowest since 2025-W52' when the week is the most extreme for a while, else ''."""
    at = next((i for i, (w, _, _) in enumerate(series) if w == week), -1)
    if at < 0:
        return ""
    _, value, wow = series[at]
    if value is None or wow is None or abs(wow) < 0.005:
        return ""
    falling = wow < 0
    for i in range(at - 1, -1, -1):
        prior = series[i][1]
        if prior is None:
            continue
        if (prior <= value) if falling else (prior >= value):
            word = "lowest" if falling else "highest"
            return f"the {word} since {series[i][0]}" if at - i >= NOTABLE_GAP else ""
    word = "lowest" if falling else "highest"
    return f"the {word} in {at + 1} weeks on record" if at >= NOTABLE_GAP else ""


def _region_name(headline: str, node_id: str, name: str) -> str:
    """Some run summaries open with the region code ("NB activities..."); say its name."""
    return f"{name}{headline[len(node_id) :]}" if headline.startswith(f"{node_id} ") else headline


def build_recap(export_dir: Path, week: str | None = None) -> dict[str, Any]:
    """The recap for ``week`` (default: the manifest's latest week)."""
    manifest = json.loads((export_dir / "manifest.json").read_text())
    week = manifest["latest_week"] if week in (None, "last") else week
    if week not in manifest["weeks_available"]:
        raise ValueError(f"{week} is not in the export (latest is {manifest['latest_week']})")

    rows = duckdb.execute(
        "select level, node_id, node_name, kpi_code, value, wow_pct, trailing_13w_avg, flag "
        "from read_parquet(?) where iso_week_id = ? and level in ('NATIONAL', 'REGION') "
        "order by node_id, kpi_code",
        [str(export_dir / "weekly_report.parquet"), week],
    ).fetchall()
    national = {r[3]: r for r in rows if r[0] == "NATIONAL"}
    regions = [r for r in rows if r[0] == "REGION"]

    kpis = []
    for code in HEADLINE_KPIS:
        row = national.get(code.value)
        value = row[4] if row else None
        kpis.append(
            {
                "code": code.value,
                "label": KPI_LABELS[code],
                "value": value,
                "text": format_kpi(code, value),
                "wow": row[5] if row else None,
                "better": _better(code),
                "flag": bool(row and row[7] == "ANOMALY"),
            }
        )

    # Away from usual as a share, as the map and What moved show it; null with no usual yet.
    ranked = []
    for r in regions:
        if r[3] != RANKED_KPI.value:
            continue
        away = r[4] / r[6] - 1 if r[4] is not None and r[6] else None
        ranked.append(
            {
                "id": r[1],
                "name": r[2],
                "away": away,
                "text": format_kpi(RANKED_KPI, r[4]),
                "flag": r[7] == "ANOMALY",
            }
        )
    ranked.sort(key=lambda r: (r["away"] is None, -(r["away"] or 0), r["name"]))

    flagged = sorted(
        (
            {"name": r[2], "label": KPI_LABELS[KpiCode(r[3])], "wow": r[5]}
            for r in regions
            if r[7] == "ANOMALY"
        ),
        key=lambda f: (-abs(f["wow"] or 0), f["name"], f["label"]),
    )[:MAX_FLAGGED]

    # The run summary of the region furthest from its usual week, when the run wrote one.
    summary = None
    narratives_path = export_dir / "narratives" / f"{week}.json"
    furthest = max(
        (r for r in ranked if r["away"] is not None), key=lambda r: abs(r["away"]), default=None
    )
    if furthest and narratives_path.is_file():
        notes = json.loads(narratives_path.read_text())["narratives"]
        found = next((n["headline"] for n in notes if n["node_id"] == furthest["id"]), None)
        summary = found and _region_name(found, furthest["id"], furthest["name"])

    lead_code = HEADLINE_KPIS[0]
    series = duckdb.execute(
        "select iso_week_id, value, wow_pct from read_parquet(?) "
        "where level = 'NATIONAL' and kpi_code = ? order by iso_week_id",
        [str(export_dir / "weekly_report.parquet"), lead_code.value],
    ).fetchall()
    lead = national.get(lead_code.value)
    since = extreme_since(series, week)
    moved = _moved(lead_code, lead[4] if lead else None, lead[5] if lead else None)
    headline = f"{KPI_LABELS[lead_code]} {moved}"
    headline += f", {since}." if since else "."
    others = sorted(
        (
            r
            for r in national.values()
            if r[3] != lead_code.value and r[7] == "ANOMALY" and r[5] is not None
        ),
        key=lambda r: -abs(r[5]),
    )
    if others:
        top = others[0]
        code = KpiCode(top[3])
        support = f"{KPI_LABELS[code]} {_moved(code, top[4], top[5])}, outside its usual range"
        support += f", one of {len(others)} measures flagged this week." if len(others) > 1 else "."
    else:
        support = "Every other measure stayed within its usual range."

    return {
        "version": RECAP_VERSION,
        "week": week,
        "dates": week_dates(week),
        "headline": headline,
        "support": support,
        "kpis": kpis,
        "rankedLabel": KPI_LABELS[RANKED_KPI],
        "regions": ranked,
        "flagged": flagged,
        "summary": summary,
    }


def write_recap(export_dir: Path, out: Path, week: str | None = None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build_recap(export_dir, week), indent=2) + "\n")
    return out
