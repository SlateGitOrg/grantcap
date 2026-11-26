"""Seeded synthetic data for a youth and family services nonprofit, with injected patterns.

Injected patterns (each recovered by the analysis and recorded in truth.json):

* G03 is over-allocated: its award runs out in fiscal month 9 (March).
* G05 is a nine-month award: its period ends March 31, so April-June falls to unrestricted.
* G06 is under-allocated: it leaves a known unspent balance.
* G01 is the last quarter of a federal award year; G02 is the next one starting in October.
* Four vacancies are hired in months 3, 5, 8 and 10; everyone gets a 3% merit increase in
  month 7.
* Foundations cap indirect at 10%, the state at 15%, the county at 0%.

`truth.json` is computed here with grant-level arithmetic (one aggregated waterfall per
grant), which is a different route from the row-level reference the budget is tested against.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import replace
from datetime import date
from pathlib import Path

from grantcap.io import write_dataset
from grantcap.models import MONTHS, Allocation, Dataset, Grant, Org, Position
from grantcap.reference import monthly_cost, run

SEED = 7
FISCAL_YEAR_START = date(2025, 7, 1)
HUGE_AWARD = 1e12

# program -> (head count, [(title, salary low, salary high)])
PROGRAMS: list[tuple[str, int, list[tuple[str, int, int]]]] = [
    (
        "Early Learning",
        10,
        [
            ("Program Director", 84000, 96000),
            ("Lead Teacher", 52000, 62000),
            ("Teacher", 44000, 52000),
            ("Teaching Assistant", 38000, 43000),
            ("Family Engagement Specialist", 48000, 58000),
        ],
    ),
    (
        "Youth Mentoring",
        9,
        [
            ("Program Director", 80000, 92000),
            ("Mentor Coordinator", 50000, 60000),
            ("Youth Development Specialist", 44000, 54000),
            ("Outreach Worker", 39000, 46000),
        ],
    ),
    (
        "Family Support",
        11,
        [
            ("Program Director", 88000, 100000),
            ("Case Manager", 50000, 62000),
            ("Family Advocate", 44000, 54000),
            ("Parent Educator", 46000, 56000),
            ("Intake Specialist", 40000, 47000),
        ],
    ),
    (
        "Housing Stability",
        9,
        [
            ("Program Director", 86000, 98000),
            ("Housing Navigator", 52000, 64000),
            ("Case Manager", 50000, 60000),
            ("Landlord Liaison", 46000, 54000),
        ],
    ),
    (
        "Counseling and Wellness",
        9,
        [
            ("Clinical Director", 100000, 110000),
            ("Licensed Therapist", 70000, 88000),
            ("Counselor", 58000, 68000),
            ("Peer Support Specialist", 40000, 48000),
        ],
    ),
]

# Funding mix per (program index, first position index, last position index): [(grant, pct)].
# Percentages per position sum to at most 100%; the rest is planned unrestricted funding.
MIXES: list[tuple[int, int, int, list[tuple[str, float]]]] = [
    (0, 0, 5, [("G02", 0.80), ("G07", 0.20)]),
    (0, 6, 7, [("G02", 0.80), ("G06", 0.20)]),
    (0, 8, 9, [("G06", 1.00)]),
    (1, 0, 1, [("G05", 0.45), ("G04", 0.12)]),
    (1, 2, 4, [("G05", 0.45)]),
    (1, 5, 8, [("G03", 0.70), ("G07", 0.30)]),
    (2, 0, 4, [("G01", 0.50), ("G03", 0.50)]),
    (2, 5, 7, [("G02", 0.40), ("G06", 0.60)]),
    (2, 8, 10, [("G06", 1.00)]),
    (3, 0, 2, [("G01", 0.40), ("G05", 0.50)]),
    (3, 3, 5, [("G07", 1.00)]),
    (3, 6, 8, [("G03", 1.00)]),
    (4, 0, 1, [("G02", 0.60), ("G04", 0.12)]),
    (4, 2, 3, [("G02", 0.80)]),
    (4, 4, 8, [("G02", 0.60), ("G03", 0.40)]),
]

# (program index, position index) -> hire month
VACANCIES = {(2, 2): 3, (1, 6): 5, (3, 4): 8, (0, 9): 10}

MERIT_PCT = 0.03
MERIT_MONTH = 7


def _grant(
    gid: str, name: str, funder: str, start: date, end: date, cap: float, priority: int
) -> Grant:
    return Grant(gid, name, funder, HUGE_AWARD, start, end, cap, priority)


def _grants() -> list[Grant]:
    fy_start, fy_end = date(2025, 7, 1), date(2026, 6, 30)
    return [
        _grant("G01", "Federal family support pass-through (prior award year)", "federal",
               date(2024, 10, 1), date(2025, 9, 30), 0.18, 1),
        _grant("G02", "Federal family support pass-through", "federal",
               date(2025, 10, 1), date(2026, 9, 30), 0.18, 2),
        _grant("G03", "State child welfare services", "state", fy_start, fy_end, 0.15, 3),
        _grant("G04", "Community foundation general support", "foundation",
               fy_start, fy_end, 0.10, 4),
        _grant("G05", "Family foundation youth initiative (nine months)", "foundation",
               fy_start, date(2026, 3, 31), 0.10, 5),
        _grant("G06", "State early childhood and housing services", "state",
               fy_start, fy_end, 0.15, 6),
        _grant("G07", "County human services contract", "county", fy_start, fy_end, 0.0, 7),
    ]  # fmt: skip


def _positions(rng: random.Random) -> list[Position]:
    positions: list[Position] = []
    for prog_idx, (program, count, titles) in enumerate(PROGRAMS):
        for i in range(count):
            title, low, high = titles[0] if i == 0 else titles[1 + (i - 1) % (len(titles) - 1)]
            salary = round(rng.uniform(low, high) / 500) * 500
            fte = 1.0 if rng.random() < 0.7 else rng.choice([0.5, 0.6, 0.75, 0.8, 0.9])
            if i == 0:
                fte = 1.0
            positions.append(
                Position(
                    id=f"P{len(positions) + 1:03d}",
                    program=program,
                    title=title,
                    salary=float(salary),
                    fte=fte,
                    hire_month=VACANCIES.get((prog_idx, i), 1),
                    merit_pct=MERIT_PCT,
                    merit_month=MERIT_MONTH,
                )
            )
    # Pin the ends of the documented ranges.
    pinned = {
        "P004": (38000.0, 0.5),  # a part-time teaching assistant
        "P040": (110000.0, 1.0),  # the clinical director
    }
    return [
        Position(**{**p.__dict__, "salary": pinned[p.id][0], "fte": pinned[p.id][1]})
        if p.id in pinned
        else p
        for p in positions
    ]


def _allocations(positions: list[Position]) -> list[Allocation]:
    by_program: dict[str, list[Position]] = {}
    for p in positions:
        by_program.setdefault(p.program, []).append(p)
    lookup: dict[str, list[tuple[str, float]]] = {}
    for prog_idx, first, last, mix in MIXES:
        members = by_program[PROGRAMS[prog_idx][0]]
        for pos in members[first : last + 1]:
            lookup[pos.id] = mix
    return [Allocation(p.id, g, pct) for p in positions for g, pct in lookup.get(p.id, [])]


def _round_up(value: float, step: float = 500.0) -> float:
    return math.ceil(value / step) * step


def _size_awards(base: Dataset) -> Dataset:
    """Set each award from what the grant would be asked to carry, per its injected pattern.

    `base` holds effectively unlimited awards, so the reference run shows each grant's ask.
    """
    asked = run(base).grants
    g03 = asked["G03"].cumulative
    awards = {
        "G01": _round_up(asked["G01"].charged * 1.04),
        "G02": 900_000.0,
        # Strictly between the cumulative ask through month 8 and through month 9.
        "G03": round((g03[7] + 0.4 * (g03[8] - g03[7])) / 500) * 500.0,
        "G04": 60_000.0,
        "G05": _round_up(asked["G05"].charged * 1.02),
        "G06": _round_up(asked["G06"].charged * 1.12),
        "G07": _round_up(asked["G07"].charged * 1.03),
    }  # fmt: skip
    grants = tuple(replace(g, award=awards[g.id]) for g in base.grants)
    return replace(base, grants=grants)


def generate(seed: int = SEED) -> Dataset:
    rng = random.Random(seed)
    org = Org(FISCAL_YEAR_START, 0.27, 0.18, "Harbor Light Family Services")
    positions = _positions(rng)
    ds = Dataset(org, tuple(positions), tuple(_grants()), tuple(_allocations(positions)))
    return _size_awards(ds)


def build_truth(ds: Dataset, seed: int = SEED) -> dict:
    """Expected answers from one aggregated waterfall per grant (no row-level logic)."""
    cost = {p.id: monthly_cost(p, ds.org.fringe_rate) for p in ds.positions}
    bounds = ds.org.month_bounds()
    negotiated = ds.org.negotiated_indirect_rate
    total_cost = [sum(c[m] for c in cost.values()) for m in range(MONTHS)]
    charged_direct = [0.0] * MONTHS
    under = [0.0] * MONTHS
    info: dict[str, dict] = {}
    for g in ds.grants:
        rate = ds.effective_rate(g)
        asked_unflagged = [
            sum(a.pct * cost[a.position_id][m] for a in ds.allocations if a.grant_id == g.id)
            for m in range(MONTHS)
        ]
        flags = [1 if g.start <= first and g.end >= last else 0 for first, last in bounds]
        remaining = g.award
        exhaustion = 0
        charges = []
        for m in range(MONTHS):
            direct = min(flags[m] * asked_unflagged[m], remaining / (1 + rate))
            remaining -= direct * (1 + rate)
            if exhaustion == 0 and remaining <= 0.005:
                exhaustion = m + 1
            charges.append(direct)
            charged_direct[m] += direct
            under[m] += (negotiated - rate) * direct
        info[g.id] = {
            "asked_unflagged": asked_unflagged,
            "flags": flags,
            "charges": charges,
            "exhaustion": exhaustion,
            "unspent": g.award - sum(charges) * (1 + rate),
            "rate": rate,
        }
    gap = [
        {
            "month": m + 1,
            "direct_shortfall": round(total_cost[m] - charged_direct[m], 2),
            "indirect_under_recovery": round(under[m], 2),
            "total": round(total_cost[m] - charged_direct[m] + under[m], 2),
        }
        for m in range(MONTHS)
    ]
    g03, g05, g06 = info["G03"], info["G05"], info["G06"]
    g03_award = ds.grant("G03").award
    g03_requested = sum(g03["asked_unflagged"]) * (1 + g03["rate"])
    return {
        "seed": seed,
        "gap_by_month": gap,
        "total_indirect_under_recovery": round(sum(under), 2),
        "g03": {
            "award": g03_award,
            "exhaustion_month": g03["exhaustion"],
            "unfunded_direct_after_exhaustion": round(
                sum(g03["asked_unflagged"]) - sum(g03["charges"]), 2
            ),
            "requested_including_indirect": round(g03_requested, 2),
        },
        "g05": {
            "period_end": ds.grant("G05").end.isoformat(),
            "unfunded_direct_apr_jun": round(sum(g05["asked_unflagged"][9:]), 2),
        },
        "g06": {"award": ds.grant("G06").award, "unspent_balance": round(g06["unspent"], 2)},
    }


def write_synthetic(directory: Path | str, seed: int = SEED) -> Dataset:
    directory = Path(directory)
    ds = generate(seed)
    write_dataset(ds, directory)
    (directory / "truth.json").write_text(json.dumps(build_truth(ds, seed), indent=2) + "\n")
    return ds
