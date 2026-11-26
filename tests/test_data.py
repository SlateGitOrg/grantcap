"""The synthetic generator, the input loaders and their validation."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from grantcap.io import load_dataset, write_dataset
from grantcap.models import Allocation, DataError, Org, apply_renewal, validate
from grantcap.synth import build_truth, generate, write_synthetic

DATA = Path(__file__).resolve().parent.parent / "data"


def test_generator_is_deterministic_and_seed_sensitive():
    assert generate(7) == generate(7)
    assert generate(8).positions != generate(7).positions


def test_dataset_has_the_documented_shape(ds):
    assert len(ds.positions) == 48
    assert len(ds.programs()) == 5
    assert len(ds.grants) == 7
    assert 78 <= len(ds.allocations) <= 85
    assert min(p.salary for p in ds.positions) == 38000
    assert max(p.salary for p in ds.positions) == 110000
    assert min(p.fte for p in ds.positions) == 0.5
    assert max(p.fte for p in ds.positions) == 1.0
    assert ds.org.fringe_rate == 0.27 and ds.org.negotiated_indirect_rate == 0.18
    assert ds.org.fiscal_year_start == date(2025, 7, 1)


def test_awards_span_the_documented_range(ds):
    awards = [g.award for g in ds.grants]
    assert min(awards) == 60000 and max(awards) == 900000


def test_no_position_is_requested_above_its_full_cost(ds):
    totals: dict[str, float] = {}
    for a in ds.allocations:
        totals[a.position_id] = totals.get(a.position_id, 0) + a.pct
    assert max(totals.values()) <= 1.0 + 1e-9
    assert any(t < 1.0 for t in totals.values())  # some planned unrestricted share


def test_committed_sample_data_matches_the_generator(ds):
    assert load_dataset(DATA) == ds
    stored = json.loads((DATA / "truth.json").read_text())
    assert stored == build_truth(ds)


def test_truth_records_the_injected_patterns(truth):
    assert truth["g03"]["exhaustion_month"] == 9
    assert truth["g05"]["period_end"] == "2026-03-31"
    assert truth["g05"]["unfunded_direct_apr_jun"] > 0
    assert truth["g06"]["unspent_balance"] > 0
    assert len(truth["gap_by_month"]) == 12


def test_write_and_load_round_trip(ds, tmp_path):
    write_synthetic(tmp_path)
    assert load_dataset(tmp_path) == ds
    write_dataset(ds, tmp_path / "again")
    assert load_dataset(tmp_path / "again") == ds


def test_missing_file_is_a_data_error(tmp_path):
    with pytest.raises(DataError, match="org.yaml"):
        load_dataset(tmp_path)


def test_missing_column_is_reported(ds, tmp_path):
    write_dataset(ds, tmp_path)
    (tmp_path / "grants.csv").write_text("id,name\nG1,x\n")
    with pytest.raises(DataError, match="missing columns"):
        load_dataset(tmp_path)


def test_over_requested_position_is_rejected(ds):
    extra = Allocation("P001", "G03", 0.5)
    with pytest.raises(DataError, match="P001"):
        validate(replace(ds, allocations=(*ds.allocations, extra)))


def test_unknown_references_and_duplicates_are_rejected(ds):
    with pytest.raises(DataError, match="unknown grant"):
        validate(replace(ds, allocations=(Allocation("P001", "G99", 0.1),)))
    with pytest.raises(DataError, match="unknown position"):
        validate(replace(ds, allocations=(Allocation("P999", "G01", 0.1),)))
    first = ds.allocations[0]
    with pytest.raises(DataError, match="duplicate allocation"):
        validate(replace(ds, allocations=(first, first)))


def test_bad_values_are_rejected(ds):
    with pytest.raises(DataError, match="first day"):
        validate(replace(ds, org=Org(date(2025, 7, 15), 0.27, 0.18)))
    bad_grant = replace(ds.grants[0], end=date(2020, 1, 1))
    with pytest.raises(DataError, match="end on or after"):
        validate(replace(ds, grants=(bad_grant, *ds.grants[1:])))
    bad_pos = replace(ds.positions[0], fte=1.5)
    with pytest.raises(DataError, match="FTE"):
        validate(replace(ds, positions=(bad_pos, *ds.positions[1:])))


def test_renewal_rejects_non_positive_amounts(ds):
    with pytest.raises(DataError):
        apply_renewal(ds, "G05", 0)
