"""Reading and writing the four input files (positions, grants, allocations, org)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from grantcap.models import (
    NEVER,
    Allocation,
    DataError,
    Dataset,
    Grant,
    Org,
    Position,
    validate,
)

POSITION_COLUMNS = [
    "id",
    "program",
    "title",
    "annual_salary",
    "fte",
    "hire_month",
    "merit_pct",
    "merit_month",
]
GRANT_COLUMNS = [
    "id",
    "name",
    "funder_type",
    "award",
    "period_start",
    "period_end",
    "indirect_rate_cap",
    "priority",
]
ALLOCATION_COLUMNS = ["position_id", "grant_id", "requested_pct"]


def _read(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        raise DataError(f"missing input file: {path.name}")
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise DataError(f"{path.name} is missing columns: {', '.join(missing)}")
    return frame


def _int_or(value: str, default: int) -> int:
    return int(value) if value.strip() else default


def _number(value: str, label: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise DataError(f"{label}: {value!r} is not a number") from exc


def _date(value: str, label: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise DataError(f"{label}: {value!r} is not an ISO date") from exc


def load_org(path: Path) -> Org:
    if not path.exists():
        raise DataError("missing input file: org.yaml")
    raw = yaml.safe_load(path.read_text()) or {}
    try:
        start = raw["fiscal_year_start"]
        if isinstance(start, str):
            start = date.fromisoformat(start)
        return Org(
            fiscal_year_start=start,
            fringe_rate=float(raw["fringe_rate"]),
            negotiated_indirect_rate=float(raw["negotiated_indirect_rate"]),
            name=str(raw.get("name", "Organisation")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DataError(f"org.yaml is incomplete or malformed: {exc}") from exc


def load_dataset(directory: Path | str) -> Dataset:
    directory = Path(directory)
    org = load_org(directory / "org.yaml")
    positions = tuple(
        Position(
            id=r["id"],
            program=r["program"],
            title=r["title"],
            salary=_number(r["annual_salary"], f"position {r['id']} salary"),
            fte=_number(r["fte"], f"position {r['id']} fte"),
            hire_month=_int_or(r["hire_month"], 1),
            merit_pct=_number(r["merit_pct"] or "0", f"position {r['id']} merit"),
            merit_month=_int_or(r["merit_month"], NEVER),
        )
        for r in _read(directory / "positions.csv", POSITION_COLUMNS).to_dict("records")
    )
    grants = tuple(
        Grant(
            id=r["id"],
            name=r["name"],
            funder_type=r["funder_type"],
            award=_number(r["award"], f"grant {r['id']} award"),
            start=_date(r["period_start"], f"grant {r['id']} start"),
            end=_date(r["period_end"], f"grant {r['id']} end"),
            indirect_cap=_number(r["indirect_rate_cap"], f"grant {r['id']} cap"),
            priority=int(r["priority"]),
        )
        for r in _read(directory / "grants.csv", GRANT_COLUMNS).to_dict("records")
    )
    allocations = tuple(
        Allocation(
            r["position_id"],
            r["grant_id"],
            _number(r["requested_pct"], f"allocation {r['position_id']}/{r['grant_id']}"),
        )
        for r in _read(directory / "allocations.csv", ALLOCATION_COLUMNS).to_dict("records")
    )
    ds = Dataset(org, positions, grants, allocations)
    validate(ds)
    return ds


def write_dataset(ds: Dataset, directory: Path | str) -> None:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "id": p.id,
                "program": p.program,
                "title": p.title,
                "annual_salary": f"{p.salary:.0f}",
                "fte": f"{p.fte:g}",
                "hire_month": "" if p.hire_month == 1 else p.hire_month,
                "merit_pct": f"{p.merit_pct:g}",
                "merit_month": "" if p.merit_month == NEVER else p.merit_month,
            }
            for p in ds.positions
        ],
        columns=POSITION_COLUMNS,
    ).to_csv(directory / "positions.csv", index=False)
    pd.DataFrame(
        [
            {
                "id": g.id,
                "name": g.name,
                "funder_type": g.funder_type,
                "award": f"{g.award:.0f}",
                "period_start": g.start.isoformat(),
                "period_end": g.end.isoformat(),
                "indirect_rate_cap": f"{g.indirect_cap:g}",
                "priority": g.priority,
            }
            for g in ds.grants
        ],
        columns=GRANT_COLUMNS,
    ).to_csv(directory / "grants.csv", index=False)
    pd.DataFrame(
        [
            {"position_id": a.position_id, "grant_id": a.grant_id, "requested_pct": f"{a.pct:g}"}
            for a in ds.allocations
        ],
        columns=ALLOCATION_COLUMNS,
    ).to_csv(directory / "allocations.csv", index=False)
    org = {
        "name": ds.org.name,
        "fiscal_year_start": ds.org.fiscal_year_start.isoformat(),
        "fringe_rate": ds.org.fringe_rate,
        "negotiated_indirect_rate": ds.org.negotiated_indirect_rate,
    }
    (directory / "org.yaml").write_text(yaml.safe_dump(org, sort_keys=False))
