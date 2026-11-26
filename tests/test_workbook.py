"""The generated workbook: structure, formula discipline and the recalculated numbers."""

from __future__ import annotations

import re
from datetime import datetime

import pytest
from openpyxl import load_workbook

from grantcap import layout as L
from grantcap.models import MONTHS
from grantcap.recalc import COMPUTED_SHEETS, verify_workbook

WHITELIST = {"SUM", "SUMPRODUCT", "IF", "MIN", "MAX", "ROUND", "INDEX", "MATCH", "AND"}
CENT = 0.01


def _formulas(path):
    wb = load_workbook(path)
    for ws in wb:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    yield ws.title, cell.coordinate, cell.value


def test_sheets_are_present_in_order(workbook_path):
    assert load_workbook(workbook_path).sheetnames == L.SHEETS


def test_only_whitelisted_functions_are_used(workbook_path):
    used = set()
    for _, _, formula in _formulas(workbook_path):
        used |= set(re.findall(r"([A-Z][A-Z0-9.]*)\(", formula))
    assert used <= WHITELIST
    assert {"SUMPRODUCT", "INDEX", "MATCH", "MIN", "MAX", "IF", "AND", "SUM", "ROUND"} <= used


def test_formula_count_stays_small(workbook_path):
    count = sum(1 for _ in _formulas(workbook_path))
    assert 3000 <= count <= 3500


def test_computed_sheets_hold_no_typed_numbers(workbook_path):
    """Everything numeric on the calculation sheets is a formula; only labels and month
    numbers are typed."""
    wb = load_workbook(workbook_path)
    for name in (L.CHARGES, L.INDIRECT, L.UNRESTRICTED, L.SUMMARY):
        ws = wb[name]
        for row in ws.iter_rows(min_row=L.FIRST):
            for cell in row:
                if cell.column <= 3 and name == L.CHARGES:
                    continue  # position, grant and requested % are the allocation inputs
                if ws.cell(row=cell.row, column=1).value in ("Grant", "Program"):
                    continue  # month-number header rows
                assert not isinstance(cell.value, (int, float)), (name, cell.coordinate)


def test_charges_are_grouped_contiguously_in_priority_order(ds, workbook_path):
    ws = load_workbook(workbook_path)[L.CHARGES]
    grants = [ws.cell(row=r, column=2).value for r in range(L.FIRST, L.FIRST + len(ds.allocations))]
    order = [g.id for g in ds.ordered_grants()]
    collapsed = [g for i, g in enumerate(grants) if i == 0 or grants[i - 1] != g]
    assert collapsed == [g for g in order if g in grants]  # each grant appears in one block


def test_inputs_sheet_carries_org_parameters(workbook_path):
    ws = load_workbook(workbook_path)[L.INPUTS]
    assert ws["B4"].value == 0.27 and ws["B5"].value == 0.18
    assert ws["C10"].value == datetime(2025, 7, 1)
    assert ws["D21"].value == datetime(2026, 6, 30)


def test_every_formula_cell_equals_the_reference(ds, workbook_path):
    report = verify_workbook(workbook_path, ds)
    assert report.mismatches == []
    assert report.compared >= 3000
    assert set(report.per_sheet) == set(COMPUTED_SHEETS)
    assert report.max_difference <= CENT
    assert report.checks_status == "PASS"


def test_recalculated_workbook_funds_every_position_month(ds, layout, recalculated):
    v = recalculated
    for i, p in enumerate(layout.positions):
        rows = [
            layout.charge_row(j) for j, a in enumerate(layout.allocations) if a.position_id == p.id
        ]
        for m in range(1, MONTHS + 1):
            cost = v[(L.POSITIONS, f"{layout.pos_month(m)}{layout.pos_row(i)}")]
            charged = sum(v[(L.CHARGES, f"{layout.chg_month(m)}{r}")] for r in rows)
            unrestricted = v[(L.UNRESTRICTED, f"{layout.mc(m)}{layout.pos_row(i)}")]
            assert charged + unrestricted == pytest.approx(cost, abs=CENT)


def test_recalculated_g03_exhausts_in_month_nine(layout, recalculated, truth):
    v = recalculated
    gi = [g.id for g in layout.grants].index("G03")
    r = layout.burn_row(gi)
    award = v[(L.SUMMARY, f"B{r}")]
    assert v[(L.SUMMARY, f"{layout.mc(9)}{r}")] == pytest.approx(award, abs=CENT)
    assert v[(L.SUMMARY, f"{L.col(layout.m0 + MONTHS + 1)}{r}")] == truth["g03"]["exhaustion_month"]
    for m in (10, 11, 12):
        assert v[(L.INDIRECT, f"{layout.mc(m)}{layout.indirect_row(0, gi)}")] == 0


def test_recalculated_g05_charges_nothing_after_march(layout, recalculated):
    v = recalculated
    block = layout.charge_blocks()["G05"]
    for r in range(block[0], block[1] + 1):
        for m in (10, 11, 12):
            assert v[(L.CHARGES, f"{layout.chg_month(m)}{r}")] == 0
        assert v[(L.CHARGES, f"{layout.chg_month(9)}{r}")] > 0


def test_recalculated_summary_matches_truth(layout, recalculated, truth):
    v = recalculated
    for m, expected in enumerate(truth["gap_by_month"], start=1):
        total = v[(L.SUMMARY, f"{layout.mc(m)}{layout.sum_gap_total_row}")]
        direct = v[(L.SUMMARY, f"{layout.mc(m)}{layout.sum_direct_row}")]
        assert total == pytest.approx(expected["total"], abs=CENT)
        assert direct == pytest.approx(expected["direct_shortfall"], abs=CENT)
    gi = [g.id for g in layout.grants].index("G06")
    unspent = v[(L.SUMMARY, f"{L.col(layout.m0 + MONTHS + 2)}{layout.burn_row(gi)}")]
    assert unspent == pytest.approx(truth["g06"]["unspent_balance"], abs=CENT)
