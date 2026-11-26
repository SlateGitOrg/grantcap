"""Recalculates the workbook with the `formulas` engine and compares it with the reference."""

from __future__ import annotations

import os
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

from grantcap import layout as L
from grantcap.expected import expected_cells
from grantcap.models import Dataset
from grantcap.reference import run

TOLERANCE = 0.01
COMPUTED_SHEETS = [
    L.POSITIONS,
    L.GRANTS,
    L.CHARGES,
    L.INDIRECT,
    L.UNRESTRICTED,
    L.SUMMARY,
]
_KEY = re.compile(r"^'\[.+?\](.+?)'!([A-Z]+[0-9]+)$")


@dataclass
class VerifyReport:
    compared: int = 0
    max_difference: float = 0.0
    mismatches: list[str] = field(default_factory=list)
    checks_status: str = ""
    per_sheet: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.mismatches and self.checks_status == "PASS"


def recalculate(path: Path | str) -> dict[tuple[str, str], object]:
    """Every single-cell result of the workbook, keyed by (sheet name, address)."""
    os.environ.setdefault("TQDM_DISABLE", "1")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import formulas

        model = formulas.ExcelModel().loads(str(path)).finish()
        solution = model.calculate()
    sheet_names = {name.upper(): name for name in L.SHEETS}
    values: dict[tuple[str, str], object] = {}
    for key, rng in solution.items():
        match = _KEY.match(key)
        if not match or match.group(1) not in sheet_names:
            continue
        value = rng.value
        values[(sheet_names[match.group(1)], match.group(2))] = value[0, 0]
    return values


def _formula_cells(path: Path | str) -> dict[str, list[str]]:
    wb = load_workbook(path)
    return {
        ws.title: [
            cell.coordinate
            for row in ws.iter_rows()
            for cell in row
            if isinstance(cell.value, str) and cell.value.startswith("=")
        ]
        for ws in wb
    }


def _checks_status(path: Path | str, values: dict[tuple[str, str], object]) -> str:
    ws = load_workbook(path)[L.CHECKS]
    for row in ws.iter_rows(min_col=1, max_col=1):
        if row[0].value == "All checks":
            return str(values.get((L.CHECKS, f"C{row[0].row}"), ""))
    return ""


def verify_workbook(path: Path | str, ds: Dataset) -> VerifyReport:
    """Compare each formula cell of the computed sheets with the reference, to $0.01."""
    report = VerifyReport()
    values = recalculate(path)
    expected = expected_cells(run(ds))
    formula_cells = _formula_cells(path)
    for sheet in COMPUTED_SHEETS:
        formulas_here = set(formula_cells.get(sheet, []))
        wanted = {addr: want for (name, addr), want in expected.items() if name == sheet}
        for address in sorted(formulas_here - set(wanted)):
            report.mismatches.append(f"{sheet}!{address}: no reference value")
        for address in sorted(set(wanted) - formulas_here):
            report.mismatches.append(f"{sheet}!{address}: expected a formula, found a typed value")
        count = 0
        for address in sorted(formulas_here & set(wanted)):
            want = wanted[address]
            got = values.get((sheet, address))
            count += 1
            if isinstance(want, str):
                if got != want:
                    report.mismatches.append(f"{sheet}!{address}: expected {want!r}, got {got!r}")
                continue
            try:
                diff = abs(float(got) - float(want))
            except (TypeError, ValueError):
                report.mismatches.append(f"{sheet}!{address}: expected {want:.2f}, got {got!r}")
                continue
            report.max_difference = max(report.max_difference, diff)
            if diff > TOLERANCE:
                report.mismatches.append(
                    f"{sheet}!{address}: expected {want:.2f}, got {float(got):.2f}"
                )
        report.per_sheet[sheet] = count
        report.compared += count
    report.checks_status = _checks_status(path, values)
    return report
