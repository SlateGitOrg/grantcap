"""The charge waterfall in plain Python: the tested reference for the workbook.

For each grant, month by month, rows are charged in block order. A row's direct charge is
the in-period flag times the smaller of its requested dollars and what is left of the award
(after every earlier charge to the grant, indirect included) divided by 1 + the effective
indirect rate. Grants do not draw on each other: whatever a grant cannot carry falls to
unrestricted funds.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from grantcap.models import MONTHS, Dataset, Grant, Position

EXHAUSTION_TOLERANCE = 0.005


@dataclass(frozen=True)
class ChargeRow:
    position_id: str
    grant_id: str
    pct: float
    program: str
    direct: tuple[float, ...]


@dataclass(frozen=True)
class GrantResult:
    grant: Grant
    effective_rate: float
    in_period: tuple[int, ...]
    direct: tuple[float, ...]
    recovered: tuple[float, ...]
    under_recovery: tuple[float, ...]
    cumulative: tuple[float, ...]  # direct plus indirect, running total by month
    exhaustion_month: int  # 0 when the award is never used up
    unspent: float

    @property
    def charged(self) -> float:
        return self.cumulative[-1]


@dataclass(frozen=True)
class GapMonth:
    month: int
    label: str
    direct_shortfall: float
    under_recovery: float

    @property
    def total(self) -> float:
        return self.direct_shortfall + self.under_recovery


@dataclass
class Result:
    dataset: Dataset
    cost: dict[str, list[float]]
    rows: list[ChargeRow]
    grants: dict[str, GrantResult]
    shortfall: dict[str, list[float]]  # position -> cost minus grant direct charges
    program_shortfall: dict[str, list[float]]
    program_under: dict[str, list[float]]
    row_under: list[list[float]] = field(default_factory=list)

    def gap_by_month(self) -> list[GapMonth]:
        labels = self.dataset.org.month_labels()
        out = []
        for m in range(MONTHS):
            direct = sum(v[m] for v in self.program_shortfall.values())
            under = sum(v[m] for v in self.program_under.values())
            out.append(GapMonth(m + 1, labels[m], direct, under))
        return out

    def program_gap(self) -> dict[str, list[float]]:
        return {
            prog: [
                self.program_shortfall[prog][m] + self.program_under[prog][m] for m in range(MONTHS)
            ]
            for prog in self.program_shortfall
        }

    def position_gap(self) -> dict[str, float]:
        """Annual direct shortfall plus the under-recovery the position's charges leave."""
        gap = {pid: sum(v) for pid, v in self.shortfall.items()}
        for row, under in zip(self.rows, self.row_under, strict=True):
            gap[row.position_id] += sum(under)
        return gap


def monthly_cost(position: Position, fringe_rate: float) -> list[float]:
    """Loaded cost per fiscal month: zero before hire, merit factor from its month on."""
    out = []
    for m in range(1, MONTHS + 1):
        if m < position.hire_month:
            out.append(0.0)
            continue
        merit = 1 + position.merit_pct if m >= position.merit_month else 1.0
        out.append(position.salary / 12 * position.fte * merit * (1 + fringe_rate))
    return out


def in_period_flags(ds: Dataset, grant: Grant) -> tuple[int, ...]:
    """1 for each fiscal month that lies wholly inside the grant period."""
    return tuple(
        1 if grant.start <= first and grant.end >= last else 0
        for first, last in ds.org.month_bounds()
    )


def run(ds: Dataset) -> Result:
    cost = {p.id: monthly_cost(p, ds.org.fringe_rate) for p in ds.positions}
    program_of = {p.id: p.program for p in ds.positions}
    allocations = ds.ordered_allocations()

    rows: list[ChargeRow] = []
    row_under: list[list[float]] = []
    grants: dict[str, GrantResult] = {}
    negotiated = ds.org.negotiated_indirect_rate

    for grant in ds.ordered_grants():
        block = [a for a in allocations if a.grant_id == grant.id]
        rate = ds.effective_rate(grant)
        flags = in_period_flags(ds, grant)
        direct_by_row = [[0.0] * MONTHS for _ in block]
        for m in range(MONTHS):
            charged_before = sum(sum(r[:m]) for r in direct_by_row) * (1 + rate)
            charged_above = 0.0
            for i, alloc in enumerate(block):
                remaining = max(0.0, grant.award - charged_before - charged_above)
                requested = alloc.pct * cost[alloc.position_id][m]
                d = flags[m] * min(requested, remaining / (1 + rate))
                direct_by_row[i][m] = d
                charged_above += d * (1 + rate)
        for alloc, direct in zip(block, direct_by_row, strict=True):
            rows.append(
                ChargeRow(
                    alloc.position_id,
                    grant.id,
                    alloc.pct,
                    program_of[alloc.position_id],
                    tuple(direct),
                )
            )
            row_under.append([(negotiated - rate) * d for d in direct])

        direct_total = [sum(r[m] for r in direct_by_row) for m in range(MONTHS)]
        recovered = [rate * d for d in direct_total]
        under = [(negotiated - rate) * d for d in direct_total]
        cumulative, running = [], 0.0
        for m in range(MONTHS):
            running += direct_total[m] + recovered[m]
            cumulative.append(running)
        exhausted = [
            m + 1 for m, c in enumerate(cumulative) if c >= grant.award - EXHAUSTION_TOLERANCE
        ]
        grants[grant.id] = GrantResult(
            grant=grant,
            effective_rate=rate,
            in_period=flags,
            direct=tuple(direct_total),
            recovered=tuple(recovered),
            under_recovery=tuple(under),
            cumulative=tuple(cumulative),
            exhaustion_month=exhausted[0] if exhausted else 0,
            unspent=grant.award - cumulative[-1],
        )

    shortfall = {pid: list(c) for pid, c in cost.items()}
    for row in rows:
        for m in range(MONTHS):
            shortfall[row.position_id][m] -= row.direct[m]

    programs = ds.programs()
    program_shortfall = {prog: [0.0] * MONTHS for prog in programs}
    program_under = {prog: [0.0] * MONTHS for prog in programs}
    for pid, values in shortfall.items():
        for m in range(MONTHS):
            program_shortfall[program_of[pid]][m] += values[m]
    for row, under in zip(rows, row_under, strict=True):
        for m in range(MONTHS):
            program_under[row.program][m] += under[m]

    return Result(ds, cost, rows, grants, shortfall, program_shortfall, program_under, row_under)
