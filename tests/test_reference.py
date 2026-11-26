"""The waterfall against a two-position fixture worked out by hand."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import date

import pytest

from grantcap.models import Allocation, permute_within_grants
from grantcap.reference import in_period_flags, monthly_cost, run

CENT = 0.005


def test_monthly_cost_hire_and_merit(tiny):
    alice, bob = tiny.positions
    cost_a = monthly_cost(alice, tiny.org.fringe_rate)
    cost_b = monthly_cost(bob, tiny.org.fringe_rate)
    assert cost_a[:3] == [pytest.approx(12500)] * 3
    assert cost_a[3:] == [pytest.approx(13125)] * 9  # 5% merit from month 4
    assert cost_b[:2] == [0.0, 0.0]  # not yet hired
    assert cost_b[2:] == [pytest.approx(3125)] * 10


def test_effective_rate_is_min_of_negotiated_and_cap(tiny):
    rates = {g.id: tiny.effective_rate(g) for g in tiny.grants}
    assert rates == {"T1": pytest.approx(0.10), "T2": pytest.approx(0.20)}


def test_in_period_flags_need_the_whole_month(tiny):
    t2 = tiny.grant("T2")
    assert in_period_flags(tiny, t2) == (0, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0)
    mid_month = replace(t2, start=date(2025, 9, 15))
    assert in_period_flags(tiny, mid_month)[2] == 0  # September only partly covered


def test_grant_that_runs_out_mid_month_charges_rows_in_order(tiny):
    r = run(tiny)
    by_key = {(row.position_id, row.grant_id): row.direct for row in r.rows}
    # T1 month 4: 7,656.25 left; Alice takes 6,562.5 direct; Bob gets the rest / 1.1.
    assert by_key[("A", "T1")][3] == pytest.approx(6562.5)
    assert by_key[("B", "T1")][3] == pytest.approx(437.5 / 1.1)
    assert by_key[("B", "T1")][4:] == (0.0,) * 8
    t1 = r.grants["T1"]
    assert t1.cumulative[3] == pytest.approx(30000)
    assert t1.exhaustion_month == 4
    assert t1.unspent == pytest.approx(0, abs=CENT)


def test_second_grant_uses_its_own_rate_and_period(tiny):
    t2 = run(tiny).grants["T2"]
    assert t2.in_period == (0, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0)
    expected = [0, 0, 3125, 3281.25, 3281.25, 3281.25, 3281.25, 500 / 1.2, 0, 0, 0, 0]
    assert t2.direct == pytest.approx(tuple(expected))
    assert t2.exhaustion_month == 8
    assert t2.recovered[2] == pytest.approx(625)  # 20% of 3,125
    assert t2.under_recovery == (0.0,) * 12  # cap above the negotiated rate


def test_gap_by_month_matches_hand_calculation(tiny):
    gap = run(tiny).gap_by_month()
    assert gap[0].direct_shortfall == pytest.approx(6250)  # 12,500 less 6,250 from T1
    assert gap[0].under_recovery == pytest.approx(625)  # (20% - 10%) x 6,250
    assert gap[2].direct_shortfall == pytest.approx(4687.5)
    assert gap[2].under_recovery == pytest.approx(781.25)
    assert gap[3].direct_shortfall == pytest.approx(16250 - 6562.5 - 437.5 / 1.1 - 3281.25)
    assert gap[4].total == pytest.approx(16250 - 3281.25)  # only T2 charges
    assert gap[7].direct_shortfall == pytest.approx(16250 - 500 / 1.2)
    assert gap[8].direct_shortfall == pytest.approx(16250)  # no grant is in period


def test_position_gap_adds_the_under_recovery_a_position_leaves(tiny):
    gaps = run(tiny).position_gap()
    r = run(tiny)
    assert sum(gaps.values()) == pytest.approx(sum(g.total for g in r.gap_by_month()))
    # Bob: all of month 5-12 plus the T1 shortfall in month 4 and under-recovery on T1.
    assert gaps["B"] > 0


def test_reordering_rows_changes_who_is_charged_not_the_total(tiny):
    swapped = replace(
        tiny, allocations=(tiny.allocations[1], tiny.allocations[0], tiny.allocations[2])
    )
    a, b = run(tiny), run(swapped)
    direct_a = {(x.position_id, x.grant_id): x.direct for x in a.rows}
    direct_b = {(x.position_id, x.grant_id): x.direct for x in b.rows}
    assert direct_b[("B", "T1")][3] == pytest.approx(1562.5)  # Bob first now gets all he asked
    assert direct_a[("B", "T1")][3] != pytest.approx(direct_b[("B", "T1")][3])
    for ga, gb in zip(a.gap_by_month(), b.gap_by_month(), strict=True):
        assert ga.total == pytest.approx(gb.total)
        assert ga.direct_shortfall == pytest.approx(gb.direct_shortfall)


def test_funding_identity_holds_for_every_position_month(tiny):
    r = run(tiny)
    for pid, cost in r.cost.items():
        for m in range(12):
            charged = sum(row.direct[m] for row in r.rows if row.position_id == pid)
            assert charged + r.shortfall[pid][m] == pytest.approx(cost[m], abs=CENT)
            assert r.shortfall[pid][m] >= -CENT


def test_permutation_helper_keeps_rows_and_blocks(tiny):
    shuffled = permute_within_grants(tiny, random.Random(1))
    assert sorted(shuffled.allocations, key=lambda a: (a.grant_id, a.position_id)) == sorted(
        tiny.allocations, key=lambda a: (a.grant_id, a.position_id)
    )
    assert [a.grant_id for a in shuffled.ordered_allocations()] == ["T1", "T1", "T2"]


def test_charges_are_grouped_by_grant_priority(tiny):
    reordered = replace(
        tiny,
        grants=(replace(tiny.grants[0], priority=2), replace(tiny.grants[1], priority=1)),
        allocations=tuple(Allocation(a.position_id, a.grant_id, a.pct) for a in tiny.allocations),
    )
    assert [a.grant_id for a in reordered.ordered_allocations()] == ["T2", "T1", "T1"]
