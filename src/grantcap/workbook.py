"""Writes the position budget as an .xlsx whose numbers are all live formulas."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.worksheet import Worksheet

from grantcap import layout as L
from grantcap.layout import FIRST, HEADER, Layout, col
from grantcap.models import MONTHS, Dataset

MONEY = '#,##0.00;[Red]-#,##0.00;"-"'
PCT = "0.0%"
DATE = "yyyy-mm-dd"
BOLD = Font(bold=True)
INPUT_FONT = Font(color="1F4E9C")
HEAD_FILL = PatternFill("solid", fgColor="E7ECF3")
TOTAL_FILL = PatternFill("solid", fgColor="F3F3F3")

EXCEL_EPOCH = date(1899, 12, 30)


def serial(d: date) -> int:
    """Excel's day number for a date (written as a number so every engine reads it alike)."""
    return (d - EXCEL_EPOCH).days


def _head(ws: Worksheet, row: int, labels: dict[int, object]) -> None:
    for c, text in labels.items():
        cell = ws.cell(row=row, column=c, value=text)
        cell.font = BOLD
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(horizontal="center", wrap_text=True)


def _title(ws: Worksheet, text: str, note: str = "") -> None:
    ws["A1"] = text
    ws["A1"].font = Font(bold=True, size=14)
    if note:
        ws["A2"] = note
        ws["A2"].font = Font(italic=True, color="666666")


def _widths(ws: Worksheet, widths: dict[str, float]) -> None:
    for letter, width in widths.items():
        ws.column_dimensions[letter].width = width


def _month_headers(ws: Worksheet, first_col: int, labels: list[str], row: int = HEADER) -> None:
    for m in range(1, MONTHS + 1):
        c = ws.cell(row=row, column=first_col + m - 1, value=m)
        c.font = BOLD
        c.fill = HEAD_FILL
        c.alignment = Alignment(horizontal="center")
        label = ws.cell(row=row - 1, column=first_col + m - 1, value=labels[m - 1])
        label.alignment = Alignment(horizontal="center")
        ws.column_dimensions[col(first_col + m - 1)].width = 12


def _money(ws: Worksheet, rows: range, cols: range) -> None:
    for r in rows:
        for c in cols:
            ws.cell(row=r, column=c).number_format = MONEY


def build_workbook(ds: Dataset, path: Path | str) -> Path:
    lay = Layout(ds)
    labels = ds.org.month_labels()
    wb = Workbook()
    wb.remove(wb.active)
    sheets = {name: wb.create_sheet(name) for name in L.SHEETS}
    _inputs(sheets[L.INPUTS], ds, labels)
    _positions(sheets[L.POSITIONS], lay, labels)
    _grants(sheets[L.GRANTS], lay, labels)
    _charges(sheets[L.CHARGES], lay, labels)
    _indirect(sheets[L.INDIRECT], lay, labels)
    _unrestricted(sheets[L.UNRESTRICTED], lay, labels)
    _summary(sheets[L.SUMMARY], lay, labels)
    _checks(sheets[L.CHECKS], lay)
    wb.calculation.fullCalcOnLoad = True
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ---- Inputs -------------------------------------------------------------------------------
def _inputs(ws: Worksheet, ds: Dataset, labels: list[str]) -> None:
    _title(
        ws, ds.org.name, "Blue cells are inputs; every other number in the workbook is a formula."
    )
    ws["A4"], ws["B4"] = "Fringe rate", ds.org.fringe_rate
    ws["A5"], ws["B5"] = "Negotiated indirect rate", ds.org.negotiated_indirect_rate
    ws["A6"], ws["B6"] = "Fiscal year start", serial(ds.org.fiscal_year_start)
    for ref in ("B4", "B5", "B6"):
        ws[ref].font = INPUT_FONT
    ws["B4"].number_format = ws["B5"].number_format = PCT
    ws["B6"].number_format = DATE
    _head(ws, L.MONTH_HEADER, {1: "Month", 2: "Label", 3: "First day", 4: "Last day"})
    for i, (first, last) in enumerate(ds.org.month_bounds()):
        r = L.MONTH_FIRST + i
        ws.cell(row=r, column=1, value=i + 1)
        ws.cell(row=r, column=2, value=labels[i])
        for c, d in ((3, first), (4, last)):
            cell = ws.cell(row=r, column=c, value=serial(d))
            cell.number_format = DATE
    _widths(ws, {"A": 28, "B": 14, "C": 14, "D": 14})


# ---- Positions ----------------------------------------------------------------------------
def _positions(ws: Worksheet, lay: Layout, labels: list[str]) -> None:
    _title(ws, "Positions", "Monthly loaded cost: salary / 12 x FTE x merit factor x (1 + fringe).")
    _head(
        ws,
        HEADER,
        {
            1: "Position",
            2: "Program",
            3: "Title",
            4: "Annual salary",
            5: "FTE",
            6: "Hire month",
            7: "Merit %",
            8: "Merit month",
        },
    )
    _month_headers(ws, lay.pos_first_month, labels)
    for i, p in enumerate(lay.positions):
        r = lay.pos_row(i)
        for c, v in enumerate(
            (p.id, p.program, p.title, p.salary, p.fte, p.hire_month, p.merit_pct, p.merit_month),
            start=1,
        ):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = INPUT_FONT
        ws.cell(row=r, column=4).number_format = "#,##0"
        ws.cell(row=r, column=7).number_format = PCT
        for m in range(1, MONTHS + 1):
            mc = lay.pos_month(m)
            ws[f"{mc}{r}"] = (
                f"=IF({mc}${HEADER}<$F{r},0,"
                f"$D{r}/12*$E{r}*IF({mc}${HEADER}>=$H{r},1+$G{r},1)*(1+{L.FRINGE}))"
            )
    t = lay.pos_total_row
    ws.cell(row=t, column=1, value="Total").font = BOLD
    for m in range(1, MONTHS + 1):
        mc = lay.pos_month(m)
        ws[f"{mc}{t}"] = f"=SUM({mc}{FIRST}:{mc}{lay.pos_last_row})"
        ws[f"{mc}{t}"].font = BOLD
    _money(ws, range(FIRST, t + 1), range(lay.pos_first_month, lay.pos_first_month + MONTHS))
    _widths(ws, {"A": 10, "B": 24, "C": 30, "D": 14, "E": 7, "F": 10, "G": 9, "H": 11})
    ws.freeze_panes = ws.cell(row=FIRST, column=4)


# ---- Grants -------------------------------------------------------------------------------
def _grants(ws: Worksheet, lay: Layout, labels: list[str]) -> None:
    _title(ws, "Grants", "A month is in period when the award period covers the whole month.")
    _head(
        ws,
        HEADER,
        {
            1: "Grant",
            2: "Name",
            3: "Funder",
            4: "Award (direct + indirect)",
            5: "Period start",
            6: "Period end",
            7: "Indirect cap",
            8: "Effective indirect rate",
            9: "Priority",
        },
    )
    _month_headers(ws, lay.grant_first_month, labels)
    last_month_row = L.MONTH_FIRST + MONTHS - 1
    starts = f"Inputs!$C${L.MONTH_FIRST}:$C${last_month_row}"
    ends = f"Inputs!$D${L.MONTH_FIRST}:$D${last_month_row}"
    for i, g in enumerate(lay.grants):
        r = lay.grant_row(i)
        values = (
            g.id,
            g.name,
            g.funder_type,
            g.award,
            serial(g.start),
            serial(g.end),
            g.indirect_cap,
        )
        for c, v in enumerate(values, start=1):
            ws.cell(row=r, column=c, value=v).font = INPUT_FONT
        ws.cell(row=r, column=9, value=g.priority).font = INPUT_FONT
        ws.cell(row=r, column=4).number_format = "#,##0"
        for c in (5, 6):
            ws.cell(row=r, column=c).number_format = DATE
        ws.cell(row=r, column=7).number_format = PCT
        ws[f"H{r}"] = f"=MIN({L.NEGOTIATED},G{r})"
        ws[f"H{r}"].number_format = PCT
        for m in range(1, MONTHS + 1):
            mc = lay.grant_month(m)
            ws[f"{mc}{r}"] = (
                f"=IF(AND($E{r}<=INDEX({starts},{mc}${HEADER}),"
                f"$F{r}>=INDEX({ends},{mc}${HEADER})),1,0)"
            )
    _widths(ws, {"A": 8, "B": 46, "C": 12, "D": 16, "E": 12, "F": 12, "G": 10, "H": 12, "I": 8})
    ws.freeze_panes = ws.cell(row=FIRST, column=3)


# ---- Charges ------------------------------------------------------------------------------
def direct_charge_formula(lay: Layout, row: int, month: int, first: int, last: int) -> str:
    """One monthly direct charge: flag x MIN(requested, what is left of the award / (1 + rate))."""
    mc = lay.chg_month(month)
    first_col = lay.chg_month(1)
    flag = (
        f"INDEX(Grants!${lay.grant_month(1)}${FIRST}:${lay.grant_month(MONTHS)}${lay.grant_last_row},"
        f"$E{row},{mc}${HEADER})"
    )
    cost = (
        f"INDEX(Positions!${lay.pos_month(1)}${FIRST}:${lay.pos_month(MONTHS)}${lay.pos_last_row},"
        f"$D{row},{mc}${HEADER})"
    )
    spent = []
    if month > 1:
        prev = lay.chg_month(month - 1)
        spent.append(f"SUM(${first_col}${first}:{prev}${last})")
    if row > first:
        spent.append(f"SUM({mc}${first}:{mc}{row - 1})")
    if spent:
        left = f"MAX(0,$G{row}-({'+'.join(spent)})*(1+$F{row}))"
    else:
        left = f"MAX(0,$G{row})"
    return f"={flag}*MIN($C{row}*{cost},{left}/(1+$F{row}))"


def _charges(ws: Worksheet, lay: Layout, labels: list[str]) -> None:
    _title(
        ws,
        "Charges",
        "One row per allocation, grouped by grant in priority order; rows higher in a block are "
        "charged first.",
    )
    _head(
        ws,
        HEADER,
        {
            1: "Position",
            2: "Grant",
            3: "Requested % of cost",
            4: "Position row",
            5: "Grant row",
            6: "Effective indirect rate",
            7: "Award",
            8: "Program",
        },
    )
    _month_headers(ws, lay.chg_first_month, labels)
    blocks = lay.charge_blocks()
    pos_ids = f"Positions!$A${FIRST}:$A${lay.pos_last_row}"
    grant_ids = f"Grants!$A${FIRST}:$A${lay.grant_last_row}"
    for i, a in enumerate(lay.allocations):
        r = lay.charge_row(i)
        first, last = blocks[a.grant_id]
        ws.cell(row=r, column=1, value=a.position_id).font = INPUT_FONT
        ws.cell(row=r, column=2, value=a.grant_id).font = INPUT_FONT
        ws.cell(row=r, column=3, value=a.pct).font = INPUT_FONT
        ws.cell(row=r, column=3).number_format = PCT
        ws[f"D{r}"] = f"=MATCH($A{r},{pos_ids},0)"
        ws[f"E{r}"] = f"=MATCH($B{r},{grant_ids},0)"
        ws[f"F{r}"] = f"=INDEX(Grants!$H${FIRST}:$H${lay.grant_last_row},$E{r})"
        ws[f"G{r}"] = f"=INDEX(Grants!$D${FIRST}:$D${lay.grant_last_row},$E{r})"
        ws[f"H{r}"] = f"=INDEX(Positions!$B${FIRST}:$B${lay.pos_last_row},$D{r})"
        ws[f"F{r}"].number_format = PCT
        ws[f"G{r}"].number_format = "#,##0"
        for m in range(1, MONTHS + 1):
            ws[f"{lay.chg_month(m)}{r}"] = direct_charge_formula(lay, r, m, first, last)
    _money(
        ws,
        range(FIRST, lay.chg_last_row + 1),
        range(lay.chg_first_month, lay.chg_first_month + MONTHS),
    )
    _widths(ws, {"A": 10, "B": 8, "C": 11, "D": 9, "E": 9, "F": 11, "G": 11, "H": 24})
    ws.freeze_panes = ws.cell(row=FIRST, column=3)


# ---- Indirect -----------------------------------------------------------------------------
def _indirect(ws: Worksheet, lay: Layout, labels: list[str]) -> None:
    _title(
        ws,
        "Indirect",
        "Recovered = effective rate x direct; under-recovery = (negotiated - effective) x direct.",
    )
    titles = ["Direct charges by grant", "Indirect recovered", "Indirect under-recovery"]
    chg_ids = f"Charges!$B${FIRST}:$B${lay.chg_last_row}"
    for block, title in enumerate(titles):
        header = lay.indirect_header(block)
        ws.cell(row=header - 1, column=1, value=title).font = BOLD
        _head(ws, header, {1: "Grant", 2: "Effective rate"})
        _month_headers(ws, lay.m0, labels, row=header)
        for gi, g in enumerate(lay.grants):
            r = lay.indirect_row(block, gi)
            ws.cell(row=r, column=1, value=g.id)
            ws[f"B{r}"] = f"=Grants!$H{lay.grant_row(gi)}"
            ws[f"B{r}"].number_format = PCT
            direct_row = lay.indirect_row(0, gi)
            for m in range(1, MONTHS + 1):
                mc = lay.mc(m)
                if block == 0:
                    cc = lay.chg_month(m)
                    col_range = f"Charges!{cc}${FIRST}:{cc}${lay.chg_last_row}"
                    f = f"=SUMPRODUCT(({chg_ids}=$A{r})*{col_range})"
                elif block == 1:
                    f = f"=$B{r}*{mc}{direct_row}"
                else:
                    f = f"=({L.NEGOTIATED}-$B{r})*{mc}{direct_row}"
                ws[f"{mc}{r}"] = f
        t = lay.indirect_total_row(block)
        ws.cell(row=t, column=1, value="Total").font = BOLD
        for m in range(1, MONTHS + 1):
            mc = lay.mc(m)
            ws[f"{mc}{t}"] = (
                f"=SUM({mc}{lay.indirect_row(block, 0)}:{mc}{lay.indirect_row(block, lay.n_g - 1)})"
            )
            ws[f"{mc}{t}"].font = BOLD
        _money(ws, range(header + 1, t + 1), range(lay.m0, lay.m0 + MONTHS))
    _widths(ws, {"A": 24, "B": 13})


# ---- Unrestricted -------------------------------------------------------------------------
def _unrestricted(ws: Worksheet, lay: Layout, labels: list[str]) -> None:
    _title(ws, "Unrestricted", "Cost not carried by any grant, per position-month and by program.")
    _head(ws, HEADER, {1: "Position", 2: "Program"})
    _month_headers(ws, lay.m0, labels)
    chg_pos = f"Charges!$A${FIRST}:$A${lay.chg_last_row}"
    for i, p in enumerate(lay.positions):
        r = lay.pos_row(i)
        ws.cell(row=r, column=1, value=p.id)
        ws.cell(row=r, column=2, value=p.program)
        for m in range(1, MONTHS + 1):
            mc, cc = lay.mc(m), lay.chg_month(m)
            ws[f"{mc}{r}"] = (
                f"=Positions!{lay.pos_month(m)}{r}"
                f"-SUMPRODUCT(({chg_pos}=$A{r})*Charges!{cc}${FIRST}:{cc}${lay.chg_last_row})"
            )
    _money(ws, range(FIRST, lay.unr_last_row + 1), range(lay.m0, lay.m0 + MONTHS))
    chg_prog = f"Charges!$H${FIRST}:$H${lay.chg_last_row}"
    titles = ["Direct shortfall by program", "Indirect under-recovery by program"]
    for block, title in enumerate(titles):
        header = lay.unr_prog_header(block)
        ws.cell(row=header - 1, column=1, value=title).font = BOLD
        _head(ws, header, {1: "Program"})
        _month_headers(ws, lay.m0, labels, row=header)
        for pi, prog in enumerate(lay.programs):
            r = lay.unr_prog_row(block, pi)
            ws.cell(row=r, column=1, value=prog)
            for m in range(1, MONTHS + 1):
                mc, cc = lay.mc(m), lay.chg_month(m)
                if block == 0:
                    programs = f"$B${FIRST}:$B${lay.unr_last_row}"
                    f = f"=SUMPRODUCT(({programs}=$A{r})*{mc}${FIRST}:{mc}${lay.unr_last_row})"
                else:
                    rates = f"Charges!$F${FIRST}:$F${lay.chg_last_row}"
                    f = (
                        f"=SUMPRODUCT(({chg_prog}=$A{r})*({L.NEGOTIATED}-{rates})"
                        f"*Charges!{cc}${FIRST}:{cc}${lay.chg_last_row})"
                    )
                ws[f"{mc}{r}"] = f
        t = lay.unr_prog_total_row(block)
        ws.cell(row=t, column=1, value="Total").font = BOLD
        for m in range(1, MONTHS + 1):
            mc = lay.mc(m)
            ws[f"{mc}{t}"] = (
                f"=SUM({mc}{lay.unr_prog_row(block, 0)}:{mc}{lay.unr_prog_row(block, lay.n_r - 1)})"
            )
            ws[f"{mc}{t}"].font = BOLD
        _money(ws, range(header + 1, t + 1), range(lay.m0, lay.m0 + MONTHS))
    _widths(ws, {"A": 26, "B": 24})
    ws.freeze_panes = ws.cell(row=FIRST, column=3)


# ---- Summary ------------------------------------------------------------------------------
def _summary(ws: Worksheet, lay: Layout, labels: list[str]) -> None:
    _title(ws, "Summary", "Unrestricted gap = direct shortfall + indirect under-recovery.")
    total_col = lay.sum_total_col
    _head(ws, HEADER, {1: "Program", lay.m0 + MONTHS: "Fiscal year"})
    _month_headers(ws, lay.m0, labels)
    for pi, prog in enumerate(lay.programs):
        r = lay.sum_gap_row(pi)
        ws.cell(row=r, column=1, value=prog)
        for m in range(1, MONTHS + 1):
            mc = lay.mc(m)
            direct, under = lay.unr_prog_row(0, pi), lay.unr_prog_row(1, pi)
            ws[f"{mc}{r}"] = f"=Unrestricted!{mc}{direct}+Unrestricted!{mc}{under}"
        ws[f"{total_col}{r}"] = f"=SUM({lay.mc(1)}{r}:{lay.mc(MONTHS)}{r})"
    t = lay.sum_gap_total_row
    ws.cell(row=t, column=1, value="Total unrestricted gap").font = BOLD
    ws.cell(row=lay.sum_direct_row, column=1, value="  of which direct shortfall")
    ws.cell(row=lay.sum_under_row, column=1, value="  of which indirect under-recovery")
    for m in range(1, MONTHS + 1):
        mc = lay.mc(m)
        ws[f"{mc}{t}"] = f"=SUM({mc}{lay.sum_gap_row(0)}:{mc}{lay.sum_gap_row(lay.n_r - 1)})"
        ws[f"{mc}{lay.sum_direct_row}"] = f"=Unrestricted!{mc}{lay.unr_prog_total_row(0)}"
        ws[f"{mc}{lay.sum_under_row}"] = f"=Unrestricted!{mc}{lay.unr_prog_total_row(1)}"
    for r in (t, lay.sum_direct_row, lay.sum_under_row):
        ws[f"{total_col}{r}"] = f"=SUM({lay.mc(1)}{r}:{lay.mc(MONTHS)}{r})"
    for c in range(1, lay.m0 + MONTHS + 1):
        ws.cell(row=t, column=c).font = BOLD
        ws.cell(row=t, column=c).fill = TOTAL_FILL
    _money(ws, range(FIRST, lay.sum_under_row + 1), range(lay.m0, lay.m0 + MONTHS + 1))

    h = lay.burn_header
    ws.cell(
        row=h - 1, column=1, value="Grant burn-down: cumulative charges (direct + indirect)"
    ).font = BOLD
    _head(
        ws,
        h,
        {
            1: "Grant",
            2: "Award",
            lay.m0 + MONTHS: "Charged",
            lay.m0 + MONTHS + 1: "Exhaustion month",
            lay.m0 + MONTHS + 2: "Unspent",
        },
    )
    _month_headers(ws, lay.m0, labels, row=h)
    for gi, g in enumerate(lay.grants):
        r = lay.burn_row(gi)
        ws.cell(row=r, column=1, value=g.id)
        ws[f"B{r}"] = f"=Grants!$D{lay.grant_row(gi)}"
        d, rec = lay.indirect_row(0, gi), lay.indirect_row(1, gi)
        first, last = lay.mc(1), lay.mc(MONTHS)
        for m in range(1, MONTHS + 1):
            mc = lay.mc(m)
            ws[f"{mc}{r}"] = (
                f"=SUM(Indirect!${first}{d}:{mc}{d})+SUM(Indirect!${first}{rec}:{mc}{rec})"
            )
        ws[f"{total_col}{r}"] = f"={last}{r}"
        n_open = f"SUMPRODUCT(({first}{r}:{last}{r}<$B{r}-0.005)*1)"
        ex_col = col(lay.m0 + MONTHS + 1)
        ws[f"{ex_col}{r}"] = f"=IF({n_open}={MONTHS},0,{n_open}+1)"
        un_col = col(lay.m0 + MONTHS + 2)
        ws[f"{un_col}{r}"] = f"=$B{r}-{total_col}{r}"
    _money(
        ws,
        range(h + 1, lay.burn_row(lay.n_g - 1) + 1),
        [2, *range(lay.m0, lay.m0 + MONTHS + 1), lay.m0 + MONTHS + 2],
    )
    _widths(
        ws,
        {
            "A": 34,
            "B": 13,
            total_col: 14,
            col(lay.m0 + MONTHS + 1): 12,
            col(lay.m0 + MONTHS + 2): 13,
        },
    )
    ws.freeze_panes = ws.cell(row=FIRST, column=3)


# ---- Checks -------------------------------------------------------------------------------
def _checks(ws: Worksheet, lay: Layout) -> None:
    _title(ws, "Checks", "Each check shows its value and 1 when it holds. Everything must be 1.")
    _head(ws, HEADER, {1: "Check", 2: "Value", 3: "Holds"})
    r = FIRST
    first_check = r
    for m in range(1, MONTHS + 1):
        pc, cc, uc = lay.pos_month(m), lay.chg_month(m), lay.mc(m)
        ws.cell(row=r, column=1, value=f"Month {m}: cost = grant charges + unrestricted")
        ws[f"B{r}"] = (
            f"=ROUND(Positions!{pc}{lay.pos_total_row}-SUM(Charges!{cc}{FIRST}:{cc}{lay.chg_last_row})"
            f"-SUM(Unrestricted!{uc}{FIRST}:{uc}{lay.unr_last_row}),2)"
        )
        ws[f"C{r}"] = f"=IF(B{r}=0,1,0)"
        r += 1
    for gi, g in enumerate(lay.grants):
        burn = lay.burn_row(gi)
        ws.cell(row=r, column=1, value=f"{g.id}: charged does not exceed award")
        ws[f"B{r}"] = f"=ROUND(Summary!$B{burn}-Summary!${lay.sum_total_col}{burn},2)"
        ws[f"C{r}"] = f"=IF(B{r}>=0,1,0)"
        r += 1
    for gi, g in enumerate(lay.grants):
        d = lay.indirect_row(0, gi)
        gr = lay.grant_row(gi)
        ws.cell(row=r, column=1, value=f"{g.id}: no charges outside the period")
        ws[f"B{r}"] = (
            f"=ROUND(SUMPRODUCT((1-Grants!{lay.grant_month(1)}{gr}:{lay.grant_month(MONTHS)}{gr})"
            f"*Indirect!{lay.mc(1)}{d}:{lay.mc(MONTHS)}{d}),2)"
        )
        ws[f"C{r}"] = f"=IF(B{r}=0,1,0)"
        r += 1
    ws.cell(row=r, column=1, value="No position-month has negative unrestricted cost")
    ws[f"B{r}"] = (
        f"=ROUND(MIN(Unrestricted!{lay.mc(1)}{FIRST}:{lay.mc(MONTHS)}{lay.unr_last_row}),2)"
    )
    ws[f"C{r}"] = f"=IF(B{r}>=0,1,0)"
    r += 1
    ws.cell(row=r, column=1, value="Under-recovery by grant = under-recovery by program")
    ws[f"B{r}"] = (
        f"=ROUND(SUM(Indirect!{lay.mc(1)}{lay.indirect_total_row(2)}:{lay.mc(MONTHS)}{lay.indirect_total_row(2)})"
        f"-SUM(Unrestricted!{lay.mc(1)}{lay.unr_prog_total_row(1)}:{lay.mc(MONTHS)}{lay.unr_prog_total_row(1)}),2)"
    )
    ws[f"C{r}"] = f"=IF(B{r}=0,1,0)"
    last_check = r
    r += 2
    ws.cell(row=r, column=1, value="All checks").font = BOLD
    ws[f"C{r}"] = f'=IF(MIN(C{first_check}:C{last_check})=1,"PASS","FAIL")'
    ws[f"C{r}"].font = BOLD
    _widths(ws, {"A": 56, "B": 14, "C": 10})
