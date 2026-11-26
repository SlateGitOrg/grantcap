"""Recalculation and verification on the small fixture, including a tampered workbook."""

from __future__ import annotations

from dataclasses import replace

import pytest
from openpyxl import load_workbook

from grantcap import layout as L
from grantcap.layout import Layout
from grantcap.models import apply_renewal
from grantcap.recalc import recalculate, verify_workbook
from grantcap.workbook import build_workbook, direct_charge_formula


@pytest.fixture(scope="module")
def tiny_book(tiny, tmp_path_factory):
    return build_workbook(tiny, tmp_path_factory.mktemp("tiny") / "book.xlsx")


def test_tiny_workbook_recalculates_to_the_hand_worked_numbers(tiny, tiny_book):
    lay = Layout(tiny)
    v = recalculate(tiny_book)
    t1_a = lay.charge_row(0)  # Alice on T1
    t1_b = lay.charge_row(1)  # Bob on T1
    assert v[(L.CHARGES, f"{lay.chg_month(4)}{t1_a}")] == pytest.approx(6562.5)
    assert v[(L.CHARGES, f"{lay.chg_month(4)}{t1_b}")] == pytest.approx(437.5 / 1.1)
    assert v[(L.CHARGES, f"{lay.chg_month(5)}{t1_b}")] == 0
    assert v[(L.CHARGES, f"{lay.chg_month(1)}{lay.charge_row(2)}")] == 0  # T2 not yet in period
    assert v[(L.GRANTS, f"H{lay.grant_row(0)}")] == pytest.approx(0.10)
    assert v[(L.SUMMARY, f"{lay.mc(1)}{lay.sum_gap_total_row}")] == pytest.approx(6875)
    assert v[(L.SUMMARY, f"{L.col(lay.m0 + 12 + 1)}{lay.burn_row(0)}")] == 4  # T1 exhaustion
    assert v[(L.SUMMARY, f"{L.col(lay.m0 + 12 + 1)}{lay.burn_row(1)}")] == 8  # T2 exhaustion


def test_verify_passes_on_the_tiny_workbook(tiny, tiny_book):
    report = verify_workbook(tiny_book, tiny)
    assert report.mismatches == []
    assert report.checks_status == "PASS"
    assert report.compared > 400
    assert report.ok


def test_verify_catches_a_hardcoded_charge(tiny, tiny_book, tmp_path):
    lay = Layout(tiny)
    tampered = tmp_path / "tampered.xlsx"
    wb = load_workbook(tiny_book)
    cell = f"{lay.chg_month(4)}{lay.charge_row(1)}"
    wb[L.CHARGES][cell] = 1562.5  # the figure someone would type if the award were ignored
    wb.save(tampered)
    report = verify_workbook(tampered, tiny)
    assert not report.ok
    assert any(m.startswith(f"{L.CHARGES}!{cell}") for m in report.mismatches)


def test_verify_notices_a_workbook_built_for_different_inputs(tiny, tiny_book):
    other = apply_renewal(tiny, "T1", 5000)
    report = verify_workbook(tiny_book, other)
    assert not report.ok
    assert report.mismatches


def test_renewed_workbook_recalculates_to_the_reference(tiny, tmp_path):
    renewed = apply_renewal(tiny, "T1", 10000, tiny.org.month_bounds()[-1][1])
    path = build_workbook(renewed, tmp_path / "renewed.xlsx")
    report = verify_workbook(path, renewed)
    assert report.ok, report.mismatches[:3]
    v = recalculate(path)
    lay = Layout(renewed)
    # With 10,000 more, T1 keeps charging after month 4 instead of stopping.
    assert v[(L.CHARGES, f"{lay.chg_month(5)}{lay.charge_row(0)}")] > 0


def test_a_grant_that_cannot_be_afforded_in_month_one_charges_zero(tiny, tmp_path):
    poor = replace(tiny, grants=(replace(tiny.grants[0], award=1.0), tiny.grants[1]))
    path = build_workbook(poor, tmp_path / "poor.xlsx")
    assert verify_workbook(path, poor).ok


def test_first_row_of_a_block_has_no_rows_above_and_month_one_no_history(tiny):
    lay = Layout(tiny)
    first_row = lay.charge_blocks()["T1"][0]
    formula = direct_charge_formula(lay, first_row, 1, first_row, first_row + 1)
    assert formula.count("SUM(") == 0  # nothing charged yet: remaining is the whole award
    later = direct_charge_formula(lay, first_row + 1, 3, first_row, first_row + 1)
    assert later.count("SUM(") == 2  # earlier months for the block, and the row above
