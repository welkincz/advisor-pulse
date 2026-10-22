import json
import shutil
from pathlib import Path

import pytest

from pulse.contracts.enums import KpiCode
from pulse.export.recap import build_recap, extreme_since, format_kpi, week_dates, write_recap

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures/exports"
REPO = Path(__file__).resolve().parents[2]


def test_recap_matches_the_overview_for_the_fixture_week() -> None:
    recap = build_recap(FIXTURES)
    assert recap["week"] == "2026-W40"
    assert recap["dates"] == "September 28 to October 4, 2026"
    # Same sentence as the Overview's h1 (web/tests/overview.spec.ts).
    assert recap["headline"].startswith("Activities per advisor rose 14.6% to 11.5")
    assert [k["code"] for k in recap["kpis"]] == [
        "ACT_PER_ADV",  # no 12-month window in the fixtures, so the lead KPI has no card
        "CALLS_OUT",
        "SHOW_RATE",
        "APPT_BOOKED",
    ]
    assert recap["kpis"][0]["text"] == "11.5"
    # Regions best first against their usual week; the fixtures hold Ontario and Quebec.
    aways = [r["away"] for r in recap["regions"] if r["away"] is not None]
    assert aways == sorted(aways, reverse=True)
    assert {r["id"] for r in recap["regions"]} == {"ON", "QC"}
    assert all(f["name"] in {"Ontario", "Quebec"} for f in recap["flagged"])


def test_last_means_the_latest_week_and_an_unknown_week_fails() -> None:
    assert build_recap(FIXTURES, "last")["week"] == "2026-W40"
    with pytest.raises(ValueError, match="not in the export"):
        build_recap(FIXTURES, "2020-W01")


def test_summary_names_the_region_and_is_absent_without_narratives(tmp_path: Path) -> None:
    exports = tmp_path / "exports"
    shutil.copytree(FIXTURES, exports)
    week = "2026-W40"
    note = exports / "narratives" / f"{week}.json"
    document = json.loads(note.read_text())
    furthest = max(
        (r for r in build_recap(exports)["regions"] if r["away"] is not None),
        key=lambda r: abs(r["away"]),
    )
    for n in document["narratives"]:
        if n["node_id"] == furthest["id"]:
            n["headline"] = f"{furthest['id']} activities per advisor rose."
    note.write_text(json.dumps(document))
    assert build_recap(exports)["summary"] == f"{furthest['name']} activities per advisor rose."
    note.unlink()
    assert build_recap(exports)["summary"] is None
    out = write_recap(exports, tmp_path / "video" / "recap.json")
    assert json.loads(out.read_text())["week"] == week


def test_headline_helpers_match_the_site() -> None:
    series = [(f"2026-W{i:02d}", 17.0, 0.01) for i in range(1, 12)]
    series[2] = ("2026-W03", 15.0, -0.05)
    series.append(("2026-W12", 15.5, -0.076))
    assert extreme_since(series, "2026-W12") == "the lowest since 2026-W03"
    assert (
        extreme_since([*series[:11], ("2026-W12", 20.0, 0.15)], "2026-W12")
        == "the highest in 12 weeks on record"
    )
    assert format_kpi(KpiCode.SHOW_RATE, 0.9605) == "96.0%"
    assert format_kpi(KpiCode.APPT_BOOKED, 1676.0) == "1,676"
    assert format_kpi(KpiCode.ACT_PER_ADV, 16.0) == "16.0"
    assert format_kpi(KpiCode.CALLS_OUT, None) == "–"
    assert week_dates("2026-W05") == "January 26 to February 1, 2026"
    assert week_dates("2026-W01") == "December 29, 2025 to January 4, 2026"


def test_video_palette_matches_the_site_tokens() -> None:
    """video/src/theme.ts copies the light tokens; this fails when the two drift apart."""
    import re

    tokens = (REPO / "web/src/theme/tokens.css").read_text()
    light = tokens[: tokens.index("@media")]
    theme = (REPO / "video/src/theme.ts").read_text()
    copied = dict(re.findall(r"'?([\w-]+)'?: '(#[0-9A-Fa-f]{6})'", theme))
    assert copied, "no colours found in video/src/theme.ts"
    for name, value in copied.items():
        match = re.search(rf"--{re.escape(name)}: (#[0-9A-Fa-f]{{6}});", light)
        assert match, f"--{name} is not a light token"
        assert match.group(1).upper() == value.upper(), (
            f"--{name}: video {value}, site {match.group(1)}"
        )
