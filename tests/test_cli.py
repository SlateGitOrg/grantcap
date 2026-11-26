"""Command line behaviour and report content."""

from __future__ import annotations

import csv

import pytest
from typer.testing import CliRunner

from grantcap.cli import app
from grantcap.reports import burndown_report, gap_frames, gap_report, short_names, table

runner = CliRunner()


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp("inputs")
    result = runner.invoke(app, ["generate", "--out", str(path)])
    assert result.exit_code == 0, result.output
    return path


def test_generate_writes_the_input_files(data_dir):
    names = sorted(p.name for p in data_dir.iterdir())
    assert names == ["allocations.csv", "grants.csv", "org.yaml", "positions.csv", "truth.json"]


def test_gap_prints_monthly_program_and_position_tables(data_dir):
    result = runner.invoke(app, ["gap", "--data", str(data_dir)])
    assert result.exit_code == 0
    out = result.output
    assert "Direct shortfall" in out and "Indirect under-recovery" in out
    assert "Mar-26" in out and "Counseling" in out
    assert "The 10 positions carrying most of the gap" in out
    assert out.count("\nP0") == 10


def test_burndown_prints_exhaustion_and_unspent(data_dir):
    result = runner.invoke(app, ["burndown", "--data", str(data_dir)])
    assert result.exit_code == 0
    g03 = next(line for line in result.output.splitlines() if line.startswith("G03"))
    assert "9 (Mar-26)" in g03
    g06 = next(line for line in result.output.splitlines() if line.startswith("G06"))
    assert "55,137" in g06


def test_renew_option_changes_the_april_gap(data_dir):
    base = runner.invoke(app, ["gap", "--data", str(data_dir)]).output
    renewed = runner.invoke(
        app, ["gap", "--data", str(data_dir), "--renew", "G05", "--amount", "90000"]
    ).output
    apr = lambda text: next(line for line in text.splitlines() if line.startswith("Apr-26"))  # noqa: E731
    assert apr(base) != apr(renewed)
    assert "136,077" in apr(base)


def test_csv_dir_writes_report_tables(data_dir, tmp_path):
    runner.invoke(app, ["gap", "--data", str(data_dir), "--csv-dir", str(tmp_path)])
    runner.invoke(app, ["burndown", "--data", str(data_dir), "--csv-dir", str(tmp_path)])
    with (tmp_path / "gap_by_month.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 12 and rows[0]["month"] == "Jul-25"
    with (tmp_path / "burndown_summary.csv").open() as f:
        summary = {r["grant"]: r for r in csv.DictReader(f)}
    assert summary["G03"]["exhaustion_month"] == "Mar-26"
    assert (tmp_path / "gap_top_positions.csv").exists()
    assert (tmp_path / "burndown_by_month.csv").exists()


def test_renew_without_amount_is_a_usage_error(data_dir):
    result = runner.invoke(app, ["gap", "--data", str(data_dir), "--renew", "G05"])
    assert result.exit_code == 2


def test_unknown_grant_and_missing_data_exit_with_an_error(data_dir, tmp_path):
    unknown = runner.invoke(
        app, ["gap", "--data", str(data_dir), "--renew", "G99", "--amount", "1000"]
    )
    assert unknown.exit_code == 2
    missing = runner.invoke(app, ["gap", "--data", str(tmp_path / "nothing")])
    assert missing.exit_code == 2


def test_build_then_verify_round_trip_and_mismatch_exit_code(tiny, tmp_path):
    from grantcap.io import write_dataset

    write_dataset(tiny, tmp_path / "in")
    book = tmp_path / "out" / "book.xlsx"
    built = runner.invoke(
        app, ["build", "--data", str(tmp_path / "in"), "--out", str(book), "--renew", "T1",
              "--amount", "10000"]
    )  # fmt: skip
    assert built.exit_code == 0 and book.exists()
    ok = runner.invoke(
        app, ["verify", "--data", str(tmp_path / "in"), "--workbook", str(book), "--renew", "T1",
              "--amount", "10000"]
    )  # fmt: skip
    assert ok.exit_code == 0, ok.output
    assert "Checks sheet: PASS" in ok.output and "OK" in ok.output
    stale = runner.invoke(app, ["verify", "--data", str(tmp_path / "in"), "--workbook", str(book)])
    assert stale.exit_code == 1  # the workbook was built with a renewal this run does not apply
    assert "differ by more than $0.01" in stale.output


def test_verify_without_a_workbook_fails_cleanly(data_dir, tmp_path):
    result = runner.invoke(
        app, ["verify", "--data", str(data_dir), "--workbook", str(tmp_path / "none.xlsx")]
    )
    assert result.exit_code == 2


def test_table_alignment_and_short_names():
    text = table(["Name", "Value"], [["a", "1"], ["bbb", "22"]])
    assert text.splitlines()[0] == "Name  Value"
    assert text.splitlines()[3].endswith("22")
    assert short_names(["Early Learning", "Early Support", "Housing"]) == [
        "Early Learning",
        "Early Support",
        "Housing",
    ]


def test_report_functions_agree_with_the_reference(res):
    frames = gap_frames(res)
    assert frames["gap_by_month"]["total"].sum() == pytest.approx(
        sum(g.total for g in res.gap_by_month()), abs=0.05
    )
    assert frames["gap_top_positions"]["share_of_gap"].sum() < 1
    assert "Year" in gap_report(res)
    assert "*" in burndown_report(res)
