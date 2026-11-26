"""Plain-text and CSV reports built from the reference result."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from grantcap.models import MONTHS
from grantcap.reference import Result

TOP_POSITIONS = 10


def _money(value: float) -> str:
    return f"{value:,.0f}" if abs(value) >= 0.5 else "-"


def table(headers: list[str], rows: list[list[str]], left: int = 1) -> str:
    """Fixed-width table; the first `left` columns are left-aligned, the rest right-aligned."""
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]

    def line(cells: list[str]) -> str:
        parts = [
            c.ljust(widths[i]) if i < left else c.rjust(widths[i]) for i, c in enumerate(cells)
        ]
        return "  ".join(parts).rstrip()

    rule = "  ".join("-" * w for w in widths)
    return "\n".join([line(headers), rule, *(line(r) for r in rows)])


def short_names(programs: list[str]) -> list[str]:
    """First word of each program name, or the full name where first words collide."""
    firsts = [p.split()[0] for p in programs]
    return [f if firsts.count(f) == 1 else p for f, p in zip(firsts, programs, strict=True)]


def gap_frames(res: Result) -> dict[str, pd.DataFrame]:
    months = res.gap_by_month()
    by_month = pd.DataFrame(
        {
            "month": [g.label for g in months],
            "direct_shortfall": [round(g.direct_shortfall, 2) for g in months],
            "indirect_under_recovery": [round(g.under_recovery, 2) for g in months],
            "total": [round(g.total, 2) for g in months],
        }
    )
    program_gap = res.program_gap()
    by_program = pd.DataFrame(
        {"month": [g.label for g in months]}
        | {prog: [round(v, 2) for v in values] for prog, values in program_gap.items()}
    )
    gaps = res.position_gap()
    ds = res.dataset
    ranked = sorted(ds.positions, key=lambda p: (-gaps[p.id], p.id))[:TOP_POSITIONS]
    total = sum(gaps.values())
    top = pd.DataFrame(
        {
            "position": [p.id for p in ranked],
            "program": [p.program for p in ranked],
            "title": [p.title for p in ranked],
            "annual_cost": [round(sum(res.cost[p.id]), 2) for p in ranked],
            "annual_gap": [round(gaps[p.id], 2) for p in ranked],
            "share_of_gap": [round(gaps[p.id] / total, 4) if total else 0.0 for p in ranked],
        }
    )
    return {"gap_by_month": by_month, "gap_by_program": by_program, "gap_top_positions": top}


def gap_report(res: Result) -> str:
    months = res.gap_by_month()
    year = res.dataset.org.fiscal_year_start.year
    out = [f"Unrestricted gap by month, fiscal year starting {year} (US dollars)", ""]
    rows = [
        [g.label, _money(g.direct_shortfall), _money(g.under_recovery), _money(g.total)]
        for g in months
    ]
    rows.append(
        [
            "Year",
            _money(sum(g.direct_shortfall for g in months)),
            _money(sum(g.under_recovery for g in months)),
            _money(sum(g.total for g in months)),
        ]
    )
    out.append(table(["Month", "Direct shortfall", "Indirect under-recovery", "Total"], rows))

    programs = res.dataset.programs()
    program_gap = res.program_gap()
    rows = [
        [g.label, *(_money(program_gap[p][i]) for p in programs), _money(g.total)]
        for i, g in enumerate(months)
    ]
    rows.append(
        [
            "Year",
            *(_money(sum(program_gap[p])) for p in programs),
            _money(sum(g.total for g in months)),
        ]
    )
    out += ["", "Total gap by program", ""]
    out.append(table(["Month", *short_names(programs), "Total"], rows))

    top = gap_frames(res)["gap_top_positions"]
    rows = [
        [
            str(r.position),
            r.program,
            r.title,
            _money(r.annual_cost),
            _money(r.annual_gap),
            f"{r.share_of_gap:.1%}",
        ]
        for r in top.itertuples()
    ]
    out += ["", f"The {TOP_POSITIONS} positions carrying most of the gap", ""]
    out.append(
        table(["Position", "Program", "Title", "Annual cost", "Annual gap", "Share"], rows, left=3)
    )
    return "\n".join(out)


def burndown_frames(res: Result) -> dict[str, pd.DataFrame]:
    ds = res.dataset
    labels = ds.org.month_labels()
    last_month = ds.org.month_bounds()[-1][1]
    grants = [res.grants[g.id] for g in ds.ordered_grants()]
    summary = pd.DataFrame(
        {
            "grant": [g.grant.id for g in grants],
            "funder": [g.grant.funder_type for g in grants],
            "award": [g.grant.award for g in grants],
            "charged": [round(g.charged, 2) for g in grants],
            "exhaustion_month": [
                labels[g.exhaustion_month - 1] if g.exhaustion_month else "" for g in grants
            ],
            "balance_as_of": [min(g.grant.end, last_month).strftime("%b-%y") for g in grants],
            "unspent": [round(g.unspent, 2) for g in grants],
        }
    )
    monthly = pd.DataFrame(
        [
            {
                "grant": g.grant.id,
                "month": labels[m],
                "cumulative_charged": round(g.cumulative[m], 2),
                "award": g.grant.award,
            }
            for g in grants
            for m in range(MONTHS)
        ]
    )  # fmt: skip
    return {"burndown_summary": summary, "burndown_by_month": monthly}


def burndown_report(res: Result) -> str:
    ds = res.dataset
    labels = ds.org.month_labels()
    grants = [res.grants[g.id] for g in ds.ordered_grants()]
    out = ["Grant burn-down (cumulative direct + indirect charges, US dollars)", ""]
    rows = []
    for g in grants:
        exhausted = (
            f"{g.exhaustion_month} ({labels[g.exhaustion_month - 1]})"
            if g.exhaustion_month
            else "-"
        )
        rows.append(
            [
                g.grant.id,
                g.grant.funder_type,
                _money(g.grant.award),
                _money(g.charged),
                exhausted,
                _money(g.unspent),
            ]
        )
    out.append(
        table(["Grant", "Funder", "Award", "Charged", "Exhaustion month", "Unspent"], rows, left=2)
    )
    out += ["", "Cumulative charges by month (an asterisk marks the month the award runs out)", ""]
    headers = ["Month", *(g.grant.id for g in grants)]
    rows = []
    for m in range(MONTHS):
        cells = [labels[m]]
        for g in grants:
            mark = "*" if g.exhaustion_month == m + 1 else ""
            cells.append(_money(g.cumulative[m]) + mark)
        rows.append(cells)
    rows.insert(0, ["Award", *(_money(g.grant.award) for g in grants)])
    out.append(table(headers, rows))
    out += [
        "",
        "Unspent is the award less charges to date at the end of the grant period, or at the "
        "fiscal year end for periods that run past it.",
    ]
    return "\n".join(out)


def write_csvs(frames: dict[str, pd.DataFrame], directory: Path | str) -> list[Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, frame in frames.items():
        path = directory / f"{name}.csv"
        frame.to_csv(path, index=False)
        paths.append(path)
    return paths
