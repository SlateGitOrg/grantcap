"""The reference result laid out cell by cell, as the workbook should calculate it."""

from __future__ import annotations

from grantcap import layout as L
from grantcap.layout import Layout
from grantcap.models import MONTHS
from grantcap.reference import Result

Cells = dict[tuple[str, str], float | str]


def expected_cells(res: Result) -> Cells:
    lay = Layout(res.dataset)
    out: Cells = {}

    def put(sheet: str, column: str, row: int, value: float | str) -> None:
        out[(sheet, f"{column}{row}")] = value

    # Positions
    for i, p in enumerate(lay.positions):
        for m in range(1, MONTHS + 1):
            put(L.POSITIONS, lay.pos_month(m), lay.pos_row(i), res.cost[p.id][m - 1])
    for m in range(1, MONTHS + 1):
        total = sum(res.cost[p.id][m - 1] for p in lay.positions)
        put(L.POSITIONS, lay.pos_month(m), lay.pos_total_row, total)

    # Grants
    for gi, g in enumerate(lay.grants):
        gr = res.grants[g.id]
        put(L.GRANTS, "H", lay.grant_row(gi), gr.effective_rate)
        for m in range(1, MONTHS + 1):
            put(L.GRANTS, lay.grant_month(m), lay.grant_row(gi), gr.in_period[m - 1])

    # Charges
    pos_index = {p.id: i for i, p in enumerate(lay.positions)}
    grant_index = {g.id: i for i, g in enumerate(lay.grants)}
    for i, row in enumerate(res.rows):
        r = lay.charge_row(i)
        gr = res.grants[row.grant_id]
        put(L.CHARGES, "D", r, pos_index[row.position_id] + 1)
        put(L.CHARGES, "E", r, grant_index[row.grant_id] + 1)
        put(L.CHARGES, "F", r, gr.effective_rate)
        put(L.CHARGES, "G", r, gr.grant.award)
        put(L.CHARGES, "H", r, row.program)
        for m in range(1, MONTHS + 1):
            put(L.CHARGES, lay.chg_month(m), r, row.direct[m - 1])

    # Indirect
    for gi, g in enumerate(lay.grants):
        gr = res.grants[g.id]
        series = (gr.direct, gr.recovered, gr.under_recovery)
        for block, values in enumerate(series):
            r = lay.indirect_row(block, gi)
            put(L.INDIRECT, "B", r, gr.effective_rate)
            for m in range(1, MONTHS + 1):
                put(L.INDIRECT, lay.mc(m), r, values[m - 1])
    for block, attr in enumerate(("direct", "recovered", "under_recovery")):
        for m in range(1, MONTHS + 1):
            total = sum(getattr(res.grants[g.id], attr)[m - 1] for g in lay.grants)
            put(L.INDIRECT, lay.mc(m), lay.indirect_total_row(block), total)

    # Unrestricted
    for i, p in enumerate(lay.positions):
        for m in range(1, MONTHS + 1):
            put(L.UNRESTRICTED, lay.mc(m), lay.pos_row(i), res.shortfall[p.id][m - 1])
    for block, table in enumerate((res.program_shortfall, res.program_under)):
        for pi, prog in enumerate(lay.programs):
            for m in range(1, MONTHS + 1):
                put(L.UNRESTRICTED, lay.mc(m), lay.unr_prog_row(block, pi), table[prog][m - 1])
        for m in range(1, MONTHS + 1):
            put(
                L.UNRESTRICTED,
                lay.mc(m),
                lay.unr_prog_total_row(block),
                sum(table[prog][m - 1] for prog in lay.programs),
            )

    # Summary: gap table
    gap = res.program_gap()
    fy = lay.sum_total_col
    for pi, prog in enumerate(lay.programs):
        r = lay.sum_gap_row(pi)
        for m in range(1, MONTHS + 1):
            put(L.SUMMARY, lay.mc(m), r, gap[prog][m - 1])
        put(L.SUMMARY, fy, r, sum(gap[prog]))
    months = res.gap_by_month()
    for r, getter in (
        (lay.sum_gap_total_row, lambda g: g.total),
        (lay.sum_direct_row, lambda g: g.direct_shortfall),
        (lay.sum_under_row, lambda g: g.under_recovery),
    ):
        for m in range(1, MONTHS + 1):
            put(L.SUMMARY, lay.mc(m), r, getter(months[m - 1]))
        put(L.SUMMARY, fy, r, sum(getter(g) for g in months))
    # Summary: burn-down
    for gi, g in enumerate(lay.grants):
        gr = res.grants[g.id]
        r = lay.burn_row(gi)
        put(L.SUMMARY, "B", r, gr.grant.award)
        for m in range(1, MONTHS + 1):
            put(L.SUMMARY, lay.mc(m), r, gr.cumulative[m - 1])
        put(L.SUMMARY, fy, r, gr.charged)
        put(L.SUMMARY, L.col(lay.m0 + MONTHS + 1), r, gr.exhaustion_month)
        put(L.SUMMARY, L.col(lay.m0 + MONTHS + 2), r, gr.unspent)
    return out
