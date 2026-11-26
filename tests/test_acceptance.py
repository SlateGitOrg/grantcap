"""Acceptance checks on the seeded data, against the reference and truth.json."""

from __future__ import annotations

import random
from dataclasses import replace

import pytest

from grantcap.models import MONTHS, apply_renewal, permute_within_grants
from grantcap.reference import run

CENT = 0.01


def test_position_months_are_funded_to_the_cent(res):
    for pid, cost in res.cost.items():
        for m in range(MONTHS):
            charged = sum(r.direct[m] for r in res.rows if r.position_id == pid)
            assert charged + res.shortfall[pid][m] == pytest.approx(cost[m], abs=CENT)
            assert res.shortfall[pid][m] >= -CENT


def test_reference_gap_matches_truth_month_by_month(res, truth):
    gap = res.gap_by_month()
    for expected, actual in zip(truth["gap_by_month"], gap, strict=True):
        assert actual.direct_shortfall == pytest.approx(expected["direct_shortfall"], abs=CENT)
        assert actual.under_recovery == pytest.approx(expected["indirect_under_recovery"], abs=CENT)
        assert actual.total == pytest.approx(expected["total"], abs=CENT)


def test_g03_is_exhausted_in_month_nine_and_stops(res, truth):
    g03 = res.grants["G03"]
    assert truth["g03"]["exhaustion_month"] == 9
    assert g03.exhaustion_month == 9
    assert g03.cumulative[8] == pytest.approx(g03.grant.award, abs=CENT)
    assert g03.cumulative[7] < g03.grant.award - 1000  # month 9 is a partial month
    assert g03.direct[9:] == (0.0, 0.0, 0.0)
    asked = truth["g03"]["requested_including_indirect"]
    assert asked > g03.grant.award  # over-allocated


def test_g05_stops_at_period_end_and_the_cost_falls_to_unrestricted(ds, res, truth):
    g05 = res.grants["G05"]
    assert g05.direct[9:] == (0.0, 0.0, 0.0)
    assert all(d > 0 for d in g05.direct[:9])
    # What if the period ran to June and the award were not the limit?
    last_day = ds.org.month_bounds()[-1][1]
    extended = replace(
        ds,
        grants=tuple(
            replace(g, end=last_day, award=1e9) if g.id == "G05" else g for g in ds.grants
        ),
    )
    counterfactual = run(extended)
    base, other = res.gap_by_month(), counterfactual.gap_by_month()
    increase = sum(base[m].direct_shortfall - other[m].direct_shortfall for m in range(9, 12))
    assert increase == pytest.approx(truth["g05"]["unfunded_direct_apr_jun"], abs=CENT)
    assert other[8].direct_shortfall == pytest.approx(base[8].direct_shortfall)


def test_no_grant_is_charged_outside_its_period_or_beyond_its_award(res):
    for g in res.grants.values():
        for m in range(MONTHS):
            if g.in_period[m] == 0:
                assert g.direct[m] == 0.0, (g.grant.id, m + 1)
        assert g.charged <= g.grant.award + CENT


def test_the_federal_award_year_starts_in_october(res):
    g02, g01 = res.grants["G02"], res.grants["G01"]
    assert g02.in_period == (0, 0, 0, *([1] * 9))
    assert g01.in_period == (1, 1, 1, *([0] * 9))
    assert g01.direct[3:] == (0.0,) * 9


def test_indirect_recovery_follows_the_lower_of_negotiated_and_cap(ds, res, truth):
    for gid, g in res.grants.items():
        rate = min(0.18, ds.grant(gid).indirect_cap)
        assert g.effective_rate == pytest.approx(rate)
        for m in range(MONTHS):
            assert g.recovered[m] == pytest.approx(rate * g.direct[m])
            assert g.under_recovery[m] == pytest.approx((0.18 - rate) * g.direct[m])
    county = [g for g in res.grants.values() if g.grant.funder_type == "county"]
    assert len(county) == 1
    assert sum(county[0].recovered) == 0.0
    assert sum(county[0].under_recovery) == pytest.approx(0.18 * sum(county[0].direct))
    total_under = sum(sum(g.under_recovery) for g in res.grants.values())
    assert total_under == pytest.approx(truth["total_indirect_under_recovery"], abs=CENT)


def test_caps_match_the_funder_types(ds):
    caps = {g.id: g.indirect_cap for g in ds.grants}
    assert caps["G04"] == caps["G05"] == 0.10  # the two foundations
    assert caps["G03"] == caps["G06"] == 0.15  # state
    assert caps["G07"] == 0.0  # county


def test_vacancies_cost_nothing_before_hire_and_merit_adds_three_percent(ds, res):
    vacancies = {p.id: p.hire_month for p in ds.positions if p.hire_month > 1}
    assert sorted(vacancies.values()) == [3, 5, 8, 10]
    for pid, hire in vacancies.items():
        cost = res.cost[pid]
        assert cost[: hire - 1] == [0.0] * (hire - 1)
        assert cost[hire - 1] > 0
    for p in ds.positions:
        cost = res.cost[p.id]
        if p.hire_month <= 6:
            assert cost[6] == pytest.approx(cost[5] * 1.03, rel=1e-12)  # month 7 vs month 6
            assert cost[11] == pytest.approx(cost[6])  # flat after the step


def test_permuting_rows_inside_a_grant_leaves_the_gap_unchanged(ds, res):
    baseline = res.gap_by_month()
    base_alloc = {(r.position_id, r.grant_id): r.direct for r in res.rows}
    changed = 0
    for seed in range(10):
        permuted = run(permute_within_grants(ds, random.Random(seed)))
        for a, b in zip(baseline, permuted.gap_by_month(), strict=True):
            assert b.direct_shortfall == pytest.approx(a.direct_shortfall, abs=1e-6)
            assert b.under_recovery == pytest.approx(a.under_recovery, abs=1e-6)
        alloc = {(r.position_id, r.grant_id): r.direct for r in permuted.rows}
        if any(abs(sum(alloc[k]) - sum(base_alloc[k])) > CENT for k in base_alloc):
            changed += 1
    assert changed >= 1  # who carries the gap does change


def test_burndown_matches_truth(res, truth):
    assert res.grants["G06"].unspent == pytest.approx(truth["g06"]["unspent_balance"], abs=CENT)
    assert res.grants["G06"].unspent > 10000
    assert res.grants["G03"].exhaustion_month == 9
    assert all(g.exhaustion_month == 0 for gid, g in res.grants.items() if gid != "G03")


def test_renewing_g05_closes_the_april_june_gap_by_its_direct_charges(ds, res):
    renewed = run(apply_renewal(ds, "G05", 90000))
    base, after = res.gap_by_month(), renewed.gap_by_month()
    renewal_direct = renewed.grants["G05"].direct
    for m in range(9):  # July-March is untouched
        assert after[m].total == pytest.approx(base[m].total)
    for m in range(9, 12):
        assert renewal_direct[m] > 0
        # The direct shortfall falls by exactly what the renewal now carries.
        assert base[m].direct_shortfall - after[m].direct_shortfall == pytest.approx(
            renewal_direct[m], abs=CENT
        )
        # The foundation cap leaves 8 points of the 18% negotiated rate unrecovered.
        assert after[m].under_recovery - base[m].under_recovery == pytest.approx(
            0.08 * renewal_direct[m], abs=CENT
        )
    assert renewed.grants["G05"].charged <= ds.grant("G05").award + 90000 + CENT


def test_renewal_extends_period_and_award(ds):
    renewed = apply_renewal(ds, "G05", 90000)
    assert renewed.grant("G05").award == ds.grant("G05").award + 90000
    assert renewed.grant("G05").end == ds.org.month_bounds()[-1][1]
    assert renewed.grant("G03") == ds.grant("G03")
