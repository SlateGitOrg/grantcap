"""Where everything lives in the workbook.

The builder writes cells at these addresses and the verifier reads the reference values back
from the same ones, so the two cannot drift apart.
"""

from __future__ import annotations

from openpyxl.utils import get_column_letter

from grantcap.models import MONTHS, Dataset

INPUTS = "Inputs"
POSITIONS = "Positions"
GRANTS = "Grants"
CHARGES = "Charges"
INDIRECT = "Indirect"
UNRESTRICTED = "Unrestricted"
SUMMARY = "Summary"
CHECKS = "Checks"
SHEETS = [INPUTS, POSITIONS, GRANTS, CHARGES, INDIRECT, UNRESTRICTED, SUMMARY, CHECKS]

HEADER = 4  # header row of every table sheet
FIRST = 5  # first data row

# Inputs
FRINGE = "Inputs!$B$4"
NEGOTIATED = "Inputs!$B$5"
MONTH_HEADER = 9
MONTH_FIRST = 10


def col(index: int) -> str:
    return get_column_letter(index)


def month_col(first_month_col: int, month: int) -> str:
    """Column letter of fiscal month `month` (1-12) for a table whose month 1 is at that column."""
    return col(first_month_col + month - 1)


class Layout:
    def __init__(self, ds: Dataset) -> None:
        self.ds = ds
        self.positions = list(ds.positions)
        self.grants = ds.ordered_grants()
        self.allocations = ds.ordered_allocations()
        self.programs = ds.programs()
        self.n_p = len(self.positions)
        self.n_g = len(self.grants)
        self.n_a = len(self.allocations)
        self.n_r = len(self.programs)

        # Positions: A-H inputs, months in I..T
        self.pos_first_month = 9
        self.pos_last_row = HEADER + self.n_p
        self.pos_total_row = self.pos_last_row + 1
        # Grants: A-I inputs, flags in J..U
        self.grant_first_month = 10
        self.grant_last_row = HEADER + self.n_g
        # Charges: A-H inputs and lookups, months in I..T
        self.chg_first_month = 9
        self.chg_last_row = HEADER + self.n_a
        # Indirect, Unrestricted and Summary: months in C..N
        self.m0 = 3

    # ---- helpers -------------------------------------------------------------------------
    def pos_month(self, m: int) -> str:
        return month_col(self.pos_first_month, m)

    def grant_month(self, m: int) -> str:
        return month_col(self.grant_first_month, m)

    def chg_month(self, m: int) -> str:
        return month_col(self.chg_first_month, m)

    def mc(self, m: int) -> str:
        """Month column on the Indirect, Unrestricted and Summary sheets."""
        return month_col(self.m0, m)

    def pos_row(self, index: int) -> int:
        return FIRST + index

    def grant_row(self, index: int) -> int:
        return FIRST + index

    def charge_row(self, index: int) -> int:
        return FIRST + index

    # ---- Charges blocks --------------------------------------------------------------------
    def charge_blocks(self) -> dict[str, tuple[int, int]]:
        """Grant id -> (first row, last row) of its contiguous block on Charges."""
        blocks: dict[str, tuple[int, int]] = {}
        for i, a in enumerate(self.allocations):
            row = self.charge_row(i)
            first = blocks.get(a.grant_id, (row, row))[0]
            blocks[a.grant_id] = (first, row)
        return blocks

    # ---- Indirect --------------------------------------------------------------------------
    def indirect_header(self, block: int) -> int:
        """Header row of block 0 (direct), 1 (recovered) or 2 (under-recovery)."""
        return HEADER + block * (self.n_g + 4)

    def indirect_row(self, block: int, grant_index: int) -> int:
        return self.indirect_header(block) + 1 + grant_index

    def indirect_total_row(self, block: int) -> int:
        return self.indirect_header(block) + self.n_g + 1

    # ---- Unrestricted ----------------------------------------------------------------------
    @property
    def unr_last_row(self) -> int:
        return HEADER + self.n_p

    def unr_prog_header(self, block: int) -> int:
        """Header row of program block 0 (direct shortfall) or 1 (under-recovery)."""
        return self.unr_last_row + 3 + block * (self.n_r + 4)

    def unr_prog_row(self, block: int, program_index: int) -> int:
        return self.unr_prog_header(block) + 1 + program_index

    def unr_prog_total_row(self, block: int) -> int:
        return self.unr_prog_header(block) + self.n_r + 1

    # ---- Summary ---------------------------------------------------------------------------
    def sum_gap_row(self, program_index: int) -> int:
        return FIRST + program_index

    @property
    def sum_gap_total_row(self) -> int:
        return FIRST + self.n_r

    @property
    def sum_direct_row(self) -> int:
        return self.sum_gap_total_row + 1

    @property
    def sum_under_row(self) -> int:
        return self.sum_gap_total_row + 2

    @property
    def sum_total_col(self) -> str:
        return col(self.m0 + MONTHS)  # fiscal-year column O

    @property
    def burn_header(self) -> int:
        return self.sum_under_row + 3

    def burn_row(self, grant_index: int) -> int:
        return self.burn_header + 1 + grant_index
