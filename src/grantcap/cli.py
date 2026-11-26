"""Command line interface: generate, build, verify, gap, burndown."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from grantcap import reports
from grantcap.io import load_dataset
from grantcap.models import DataError, Dataset, apply_renewal
from grantcap.recalc import verify_workbook
from grantcap.reference import run
from grantcap.synth import SEED, write_synthetic
from grantcap.workbook import build_workbook

app = typer.Typer(
    help="Charge salaries to restricted grants within each award's period and balance.",
    no_args_is_help=True,
    add_completion=False,
)

DataDir = Annotated[Path, typer.Option("--data", help="Directory with the input files.")]
Renew = Annotated[
    str | None, typer.Option("--renew", help="Grant id to extend with a renewal award.")
]
Amount = Annotated[float | None, typer.Option("--amount", help="Renewal award amount.")]
Through = Annotated[
    str | None,
    typer.Option("--through", help="Renewal end date (ISO); default is the fiscal year end."),
]
CsvDir = Annotated[
    Path | None, typer.Option("--csv-dir", help="Also write the report tables as CSV here.")
]


def _fail(message: str, code: int = 2) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code)


def _dataset(data: Path, renew: str | None, amount: float | None, through: str | None) -> Dataset:
    try:
        ds = load_dataset(data)
        if (renew is None) != (amount is None):
            raise DataError("--renew and --amount go together")
        if renew is not None and amount is not None:
            end = date.fromisoformat(through) if through else None
            ds = apply_renewal(ds, renew, amount, end)
        elif through:
            raise DataError("--through needs --renew and --amount")
    except StopIteration as exc:
        raise _fail(f"unknown grant {renew}") from exc
    except (DataError, ValueError) as exc:
        raise _fail(str(exc)) from exc
    return ds


@app.command()
def generate(
    out: Annotated[Path, typer.Option("--out", help="Directory to write the inputs to.")] = Path(
        "data"
    ),
    seed: Annotated[int, typer.Option(help="Random seed.")] = SEED,
) -> None:
    """Write synthetic positions, grants, allocations, org.yaml and truth.json."""
    ds = write_synthetic(out, seed)
    typer.echo(
        f"Wrote {len(ds.positions)} positions, {len(ds.grants)} grants and "
        f"{len(ds.allocations)} allocations to {out}"
    )


@app.command()
def build(
    data: DataDir = Path("data"),
    out: Annotated[Path, typer.Option("--out", help="Workbook to write.")] = Path(
        "out/position_budget.xlsx"
    ),
    renew: Renew = None,
    amount: Amount = None,
    through: Through = None,
) -> None:
    """Build the live-formula position budget workbook."""
    ds = _dataset(data, renew, amount, through)
    path = build_workbook(ds, out)
    typer.echo(f"Wrote {path}")


@app.command()
def verify(
    workbook: Annotated[Path, typer.Option("--workbook", help="Workbook to check.")] = Path(
        "out/position_budget.xlsx"
    ),
    data: DataDir = Path("data"),
    renew: Renew = None,
    amount: Amount = None,
    through: Through = None,
) -> None:
    """Recalculate the workbook and compare it with the reference; exit 1 on a difference."""
    ds = _dataset(data, renew, amount, through)
    if not workbook.exists():
        raise _fail(f"{workbook} not found; run `grantcap build` first")
    report = verify_workbook(workbook, ds)
    sheets = ", ".join(f"{name} {n}" for name, n in report.per_sheet.items())
    typer.echo(f"Compared {report.compared} formula cells with the reference ({sheets}).")
    typer.echo(f"Largest difference: ${report.max_difference:.4f}")
    typer.echo(f"Checks sheet: {report.checks_status or 'not found'}")
    if report.mismatches:
        typer.echo(f"{len(report.mismatches)} cells differ by more than $0.01:", err=True)
        for line in report.mismatches[:10]:
            typer.echo(f"  {line}", err=True)
    if not report.ok:
        raise typer.Exit(1)
    typer.echo("OK: workbook matches the reference.")


@app.command()
def gap(
    data: DataDir = Path("data"),
    renew: Renew = None,
    amount: Amount = None,
    through: Through = None,
    csv_dir: CsvDir = None,
) -> None:
    """Print the unrestricted gap by month and program and the positions carrying it."""
    res = run(_dataset(data, renew, amount, through))
    typer.echo(reports.gap_report(res))
    if csv_dir:
        reports.write_csvs(reports.gap_frames(res), csv_dir)


@app.command()
def burndown(
    data: DataDir = Path("data"),
    renew: Renew = None,
    amount: Amount = None,
    through: Through = None,
    csv_dir: CsvDir = None,
) -> None:
    """Print cumulative charges against each award, exhaustion months and unspent balances."""
    res = run(_dataset(data, renew, amount, through))
    typer.echo(reports.burndown_report(res))
    if csv_dir:
        reports.write_csvs(reports.burndown_frames(res), csv_dir)
