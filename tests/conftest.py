from __future__ import annotations

from datetime import date

import pytest

from grantcap.layout import Layout
from grantcap.models import Allocation, Dataset, Grant, Org, Position
from grantcap.recalc import recalculate
from grantcap.reference import Result, run
from grantcap.synth import build_truth, generate
from grantcap.workbook import build_workbook


@pytest.fixture(scope="session")
def ds() -> Dataset:
    return generate()


@pytest.fixture(scope="session")
def res(ds: Dataset) -> Result:
    return run(ds)


@pytest.fixture(scope="session")
def truth(ds: Dataset) -> dict:
    return build_truth(ds)


@pytest.fixture(scope="session")
def layout(ds: Dataset) -> Layout:
    return Layout(ds)


@pytest.fixture(scope="session")
def workbook_path(ds: Dataset, tmp_path_factory: pytest.TempPathFactory):
    return build_workbook(ds, tmp_path_factory.mktemp("book") / "position_budget.xlsx")


@pytest.fixture(scope="session")
def recalculated(workbook_path) -> dict:
    """Every cell of the full workbook as calculated by the `formulas` engine (run once)."""
    return recalculate(workbook_path)


def tiny_dataset() -> Dataset:
    """Two positions, two grants; every expected number in the tests is worked out by hand.

    Alice costs 12,500 a month (120,000 / 12 x 1.25) and 13,125 from month 4 (5% merit).
    Bob costs 3,125 a month (60,000 / 12 x 0.5 x 1.25) and starts in month 3.
    T1 (30,000, effective indirect 10%) and T2 (20,000, 20%, September to February).
    """
    org = Org(date(2025, 7, 1), fringe_rate=0.25, negotiated_indirect_rate=0.20, name="Tiny")
    positions = (
        Position("A", "X", "Analyst", 120000, 1.0, 1, 0.05, 4),
        Position("B", "Y", "Aide", 60000, 0.5, 3),
    )
    grants = (
        Grant("T1", "First", "foundation", 30000, date(2025, 7, 1), date(2026, 6, 30), 0.10, 1),
        Grant("T2", "Second", "state", 20000, date(2025, 9, 1), date(2026, 2, 28), 0.30, 2),
    )
    allocations = (
        Allocation("A", "T1", 0.5),
        Allocation("B", "T1", 0.5),
        Allocation("A", "T2", 0.25),
    )
    return Dataset(org, positions, grants, allocations)


@pytest.fixture(scope="session")
def tiny() -> Dataset:
    return tiny_dataset()
