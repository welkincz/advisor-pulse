"""The hiring-evidence map counts posts once and rejects broken evidence links."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("reviewer_map", ROOT / "scripts/reviewer_map.py")
assert spec and spec.loader
reviewer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reviewer
spec.loader.exec_module(reviewer)


def test_aliases_and_repeated_mentions_count_once_per_post() -> None:
    posts = [
        {"id": "J01", "lane": "AE", "basis": "retrieved", "skills": ["SQL", "T-SQL", "sql"]},
        {"id": "J02", "lane": "DE", "basis": "owner_summary", "skills": ["SQL"]},
        {"id": "J03", "lane": "DE", "basis": "owner_summary", "skills": []},
    ]
    result = reviewer.counts(posts, ["sql"])
    assert result == {"total": 2, "retrieved": 1, "AE": 1, "DE": 1, "ids": ["J01", "J02"]}


@pytest.mark.parametrize("url", ["missing.py#L1", "README.md#L999999", "README.md#L0"])
def test_missing_files_and_out_of_range_line_anchors_fail(url: str) -> None:
    with pytest.raises(ValueError):
        reviewer.check_link(ROOT, url)


def test_site_routes_are_checked_against_the_router_not_its_catch_all() -> None:
    reviewer.check_link(ROOT, "https://pulse.charliebuild.com/quality")
    reviewer.check_link(ROOT, "https://pulse.charliebuild.com/r/ON/d/GTA")
    with pytest.raises(ValueError, match="route"):
        reviewer.check_link(ROOT, "https://pulse.charliebuild.com/not-a-route")


def test_line_links_cannot_escape_the_repository(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        reviewer.check_link(ROOT, "../outside.md#L1")


def test_every_committed_evidence_link_resolves_and_each_gap_has_an_issue() -> None:
    data = json.loads((ROOT / "docs/reviewer-skills.json").read_text())
    reviewer.validate(ROOT, data)
    for competency in data["competencies"]:
        if competency["strength"] != "strong":
            assert isinstance(competency["gap_issue"], int) and competency["gap_issue"] > 0


def test_the_committed_map_is_reproducible_from_extracted_skill_lists() -> None:
    data = json.loads((ROOT / "docs/reviewer-skills.json").read_text())
    assert (ROOT / "docs/reviewer-map.md").read_text() == reviewer.render(data)


def test_duplicate_source_ids_are_rejected() -> None:
    data = json.loads((ROOT / "docs/reviewer-skills.json").read_text())
    data["postings"][1]["id"] = data["postings"][0]["id"]
    with pytest.raises(ValueError, match="unique"):
        reviewer.validate(ROOT, data)


@pytest.mark.parametrize("filename", ["README.md", "docs/case-study.md"])
def test_a_broken_link_in_either_reviewers_path_fails(tmp_path: Path, filename: str) -> None:
    data = json.loads((ROOT / "docs/reviewer-skills.json").read_text())
    paths = {"README.md", "docs/case-study.md", "docs/reviewer-map.md", "web/src/app/App.tsx"}
    paths.update(
        link.split("#")[0]
        for c in data["competencies"]
        for link in c["evidence"]
        if not link.startswith("https:")
    )
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    reviewer.validate(tmp_path, data)
    source = tmp_path / filename
    source.write_text(
        source.read_text().replace(
            "https://pulse.charliebuild.com/)", "https://pulse.charliebuild.com/not-a-route)"
        )
    )
    with pytest.raises(ValueError, match="route"):
        reviewer.validate(tmp_path, data)
