"""`pulse` command-line entry point.

Subcommands are stubs until their issues land; each one names the issue that implements it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pulse import __version__
from pulse.contracts.enums import RunType
from pulse.warehouse import data_dir

app = typer.Typer(
    name="pulse",
    help="Advisor Pulse: weekly-batch BI pipeline for a fictional bank. All data is synthetic.",
    no_args_is_help=True,
    add_completion=False,
)

WeekOption = Annotated[
    str | None, typer.Option("--week", help="ISO week to process, e.g. 2026-W40, or 'last'.")
]
FromOption = Annotated[str, typer.Option("--from", help="First ISO week, e.g. 2024-W41.")]
ToOption = Annotated[str, typer.Option("--to", help="Last ISO week, inclusive.")]


def _not_implemented(command: str, issue: int) -> None:
    typer.echo(f"pulse {command}: not implemented yet (see issue #{issue}).")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """Advisor Pulse pipeline commands."""


@app.command()
def generate(
    week: WeekOption = None,
    backfill: Annotated[
        bool, typer.Option("--backfill", help="Generate every week from --from to --to.")
    ] = False,
    first: Annotated[
        str | None, typer.Option("--from", help="First ISO week of a backfill.")
    ] = None,
    last: Annotated[str | None, typer.Option("--to", help="Last ISO week of a backfill.")] = None,
    seed: Annotated[
        int | None, typer.Option("--seed", help="Generator seed (default: $PULSE_SEED).")
    ] = None,
) -> None:
    """Generate synthetic 'Snowflake' and 'Teradata' extracts for a week (or a range)."""
    from datetime import date

    from pulse.generate.cli import default_seed, generate_weeks, week_range
    from pulse.runner.run import resolve_week

    try:
        if backfill:
            if week is not None or first is None or last is None:
                raise ValueError("--backfill needs --from and --to, and no --week")
            weeks = week_range(first, last)
        else:
            if first is not None or last is not None:
                raise ValueError("--from and --to need --backfill")
            weeks = [resolve_week(week, date.today())]
            week_range(weeks[0], weeks[0])
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    generate_weeks(
        data_dir(), weeks, seed=default_seed() if seed is None else seed, echo=typer.echo
    )


@app.command()
def ingest(week: WeekOption = None) -> None:
    """Load new source files into raw tables, quarantining bad rows."""
    _not_implemented("ingest", 21)


@app.command()
def run(
    week: WeekOption = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print the plan only.")] = False,
    run_type: Annotated[
        RunType, typer.Option("--run-type", help="Recorded in run_log.", case_sensitive=False)
    ] = RunType.MANUAL,
) -> None:
    """Run the full weekly pipeline for one week (default: the last complete week)."""
    from pulse.runner.command import run_week

    try:
        code = run_week(
            week, data_dir=data_dir(), run_type=run_type, dry_run=dry_run, echo=typer.echo
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--week") from exc
    raise typer.Exit(code)


@app.command()
def backfill(
    from_week: FromOption,
    to_week: ToOption,
    rebuild: Annotated[bool, typer.Option("--rebuild", help="Start from empty state.")] = False,
) -> None:
    """Run the weekly pipeline for every week in a range."""
    from pulse.runner.backfill import backfill_range

    try:
        code = backfill_range(
            from_week, to_week, data_dir=data_dir(), rebuild=rebuild, echo=typer.echo
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    raise typer.Exit(code)


@app.command()
def export() -> None:
    """Export marts to Parquet and JSON for the web app."""
    _not_implemented("export", 46)


@app.command()
def recap(
    week: WeekOption = None,
    exports: Annotated[
        Path, typer.Option("--exports", help="Published export folder to read.")
    ] = Path("web/public/data"),
    out: Annotated[Path, typer.Option("--out", help="Where to write the JSON.")] = Path(
        "video/public/recap.json"
    ),
) -> None:
    """Write the weekly recap video's input from the published export."""
    from pulse.export.recap import write_recap

    try:
        written = write_recap(exports, out, week)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"pulse recap: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Wrote {written}")


@app.command()
def narrate(week: WeekOption = None) -> None:
    """Generate grounded weekly narratives per region and district."""
    _not_implemented("narrate", 47)
