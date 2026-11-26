"""Typed inputs for the position budget and the validation that guards them."""

from __future__ import annotations

import calendar
import random
from dataclasses import dataclass, replace
from datetime import date

MONTHS = 12
NEVER = 13  # merit effective month meaning "no merit increase this fiscal year"


class DataError(ValueError):
    """Raised when an input file breaks a rule the budget depends on."""


@dataclass(frozen=True)
class Org:
    fiscal_year_start: date
    fringe_rate: float
    negotiated_indirect_rate: float
    name: str = "Organisation"

    def month_bounds(self) -> list[tuple[date, date]]:
        """First and last day of each of the 12 fiscal months."""
        bounds = []
        year, month = self.fiscal_year_start.year, self.fiscal_year_start.month
        for _ in range(MONTHS):
            last = calendar.monthrange(year, month)[1]
            bounds.append((date(year, month, 1), date(year, month, last)))
            month += 1
            if month > 12:
                month, year = 1, year + 1
        return bounds

    def month_labels(self) -> list[str]:
        return [start.strftime("%b-%y") for start, _ in self.month_bounds()]


@dataclass(frozen=True)
class Position:
    id: str
    program: str
    title: str
    salary: float
    fte: float
    hire_month: int = 1
    merit_pct: float = 0.0
    merit_month: int = NEVER


@dataclass(frozen=True)
class Grant:
    id: str
    name: str
    funder_type: str
    award: float
    start: date
    end: date
    indirect_cap: float
    priority: int


@dataclass(frozen=True)
class Allocation:
    position_id: str
    grant_id: str
    pct: float


@dataclass(frozen=True)
class Dataset:
    org: Org
    positions: tuple[Position, ...]
    grants: tuple[Grant, ...]
    allocations: tuple[Allocation, ...]

    def position(self, position_id: str) -> Position:
        return next(p for p in self.positions if p.id == position_id)

    def grant(self, grant_id: str) -> Grant:
        return next(g for g in self.grants if g.id == grant_id)

    def programs(self) -> list[str]:
        seen: dict[str, None] = {}
        for p in self.positions:
            seen.setdefault(p.program)
        return list(seen)

    def ordered_grants(self) -> list[Grant]:
        """Grants in charge-priority order (lower number first, id breaks ties)."""
        return sorted(self.grants, key=lambda g: (g.priority, g.id))

    def ordered_allocations(self) -> list[Allocation]:
        """Allocations grouped by grant in priority order.

        Inside a grant block the order of the allocations file is kept: earlier rows are
        charged first when the award runs short.
        """
        rank = {g.id: i for i, g in enumerate(self.ordered_grants())}
        return sorted(self.allocations, key=lambda a: rank[a.grant_id])  # stable

    def effective_rate(self, grant: Grant) -> float:
        return min(self.org.negotiated_indirect_rate, grant.indirect_cap)


def validate(ds: Dataset) -> None:
    """Reject inputs that would make the waterfall meaningless."""
    org = ds.org
    if org.fiscal_year_start.day != 1:
        raise DataError("fiscal_year_start must be the first day of a month")
    if not 0 <= org.fringe_rate < 1 or not 0 <= org.negotiated_indirect_rate < 1:
        raise DataError("fringe and negotiated indirect rates must be between 0 and 1")
    pos_ids = [p.id for p in ds.positions]
    grant_ids = [g.id for g in ds.grants]
    if len(set(pos_ids)) != len(pos_ids):
        raise DataError("duplicate position id")
    if len(set(grant_ids)) != len(grant_ids):
        raise DataError("duplicate grant id")
    for p in ds.positions:
        if p.salary <= 0 or not 0 < p.fte <= 1:
            raise DataError(f"position {p.id}: salary must be positive and FTE in (0, 1]")
        if not 1 <= p.hire_month <= MONTHS:
            raise DataError(f"position {p.id}: hire month must be 1-{MONTHS}")
        if not 1 <= p.merit_month <= NEVER:
            raise DataError(f"position {p.id}: merit month must be 1-{NEVER}")
    for g in ds.grants:
        if g.award <= 0 or g.end < g.start:
            raise DataError(f"grant {g.id}: award must be positive and end on or after start")
        if not 0 <= g.indirect_cap <= 1:
            raise DataError(f"grant {g.id}: indirect cap must be between 0 and 1")
    seen: set[tuple[str, str]] = set()
    totals: dict[str, float] = {}
    for a in ds.allocations:
        if a.position_id not in pos_ids:
            raise DataError(f"allocation references unknown position {a.position_id}")
        if a.grant_id not in grant_ids:
            raise DataError(f"allocation references unknown grant {a.grant_id}")
        if not 0 < a.pct <= 1:
            raise DataError(f"allocation {a.position_id}/{a.grant_id}: pct must be in (0, 1]")
        key = (a.position_id, a.grant_id)
        if key in seen:
            raise DataError(f"duplicate allocation {a.position_id}/{a.grant_id}")
        seen.add(key)
        totals[a.position_id] = totals.get(a.position_id, 0.0) + a.pct
    for pid, total in totals.items():
        if total > 1 + 1e-9:
            raise DataError(f"position {pid} is requested at {total:.0%} of its cost across grants")


def apply_renewal(
    ds: Dataset, grant_id: str, amount: float, through: date | None = None
) -> Dataset:
    """Extend one grant with a renewal award: more money and a later end date.

    The period is extended to `through`, by default the last day of the fiscal year.
    """
    if amount <= 0:
        raise DataError("renewal amount must be positive")
    grant = ds.grant(grant_id)
    target = through or ds.org.month_bounds()[-1][1]
    renewed = replace(grant, award=grant.award + amount, end=max(grant.end, target))
    grants = tuple(renewed if g.id == grant_id else g for g in ds.grants)
    return replace(ds, grants=grants)


def permute_within_grants(ds: Dataset, rng: random.Random) -> Dataset:
    """Shuffle the order of allocations inside each grant (the charge order only)."""
    by_grant: dict[str, list[Allocation]] = {}
    for a in ds.allocations:
        by_grant.setdefault(a.grant_id, []).append(a)
    shuffled: list[Allocation] = []
    for rows in by_grant.values():
        rows = list(rows)
        rng.shuffle(rows)
        shuffled.extend(rows)
    return replace(ds, allocations=tuple(shuffled))
