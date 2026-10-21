"""Monotonic first-send budgets do not become fresh TTLs on replay."""
import pytest

from app.scoped.errors import ScopeError
from app.scoped.timing import TimingBudget, current_budget, use_budget


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, milliseconds):
        self.now += milliseconds / 1000


def timing(**changes):
    return dict(capture_age_ms=300, request_age_ms=100,
                max_snapshot_age_ms=2000, max_request_age_ms=3000, **changes)


def changed(**changes):
    value = timing()
    value.update(changes)
    return value


def test_valid_for_is_total_first_send_budget_not_current_remaining():
    clock = Clock()
    budget = TimingBudget(timing(), clock=clock)
    assert budget.valid_for_ms == 1800
    assert budget.remaining_ms == 1700
    clock.advance(250)
    assert budget.valid_for_ms == 1800
    assert budget.remaining_ms == 1450
    budget.check()


def test_snapshot_expiry_includes_reported_age_and_server_processing():
    clock = Clock()
    budget = TimingBudget(timing(), clock=clock)
    clock.advance(1700)
    with pytest.raises(ScopeError) as error:
        budget.check()
    assert error.value.code == "SNAPSHOT_EXPIRED"


def test_request_budget_alone_applies_without_snapshot():
    clock = Clock()
    budget = TimingBudget(changed(max_request_age_ms=600), clock=clock, has_snapshot=False)
    assert budget.valid_for_ms == 600
    clock.advance(500)
    with pytest.raises(ScopeError) as error:
        budget.check()
    assert error.value.code == "REQUEST_EXPIRED"


def test_retry_cannot_extend_deadline_or_original_validity():
    clock = Clock()
    budget = TimingBudget(timing(), clock=clock)
    deadline = budget.deadline
    clock.advance(400)
    budget.retry(changed(capture_age_ms=650, request_age_ms=450))
    assert budget.deadline == deadline
    assert budget.valid_for_ms == 1800
    budget.retry(changed(capture_age_ms=1100, request_age_ms=900))
    assert budget.deadline < deadline
    assert budget.elapsed_ms == 900
    assert budget.valid_for_ms == 1800


def test_retry_reported_age_can_expire_snapshot_immediately():
    budget = TimingBudget(timing(), clock=Clock())
    with pytest.raises(ScopeError) as error:
        budget.retry(changed(capture_age_ms=2000, request_age_ms=1800))
    assert error.value.code == "SNAPSHOT_EXPIRED"


@pytest.mark.parametrize("changes", [
    dict(capture_age_ms=501, request_age_ms=300),
    dict(capture_age_ms=250, request_age_ms=50),
    dict(max_snapshot_age_ms=2001),
    dict(max_request_age_ms=3001),
])
def test_retry_keeps_first_capture_age_and_budgets(changes):
    budget = TimingBudget(timing(), clock=Clock())
    with pytest.raises(ScopeError) as error:
        budget.retry(changed(**changes))
    assert error.value.code == "REQUEST_ID_CONFLICT"


@pytest.mark.parametrize("changes", [
    dict(capture_age_ms=-1), dict(request_age_ms=True), dict(request_age_ms=1.5),
    dict(capture_age_ms=50), dict(max_request_age_ms=-1),
    dict(max_snapshot_age_ms=120001),
])
def test_invalid_or_unbounded_ages_are_rejected(changes):
    with pytest.raises(ScopeError) as error:
        TimingBudget(changed(**changes), clock=Clock())
    assert error.value.code == "INVALID_SCOPE_OR_TIMING"


def test_semantic_action_window_uses_the_same_first_send_origin():
    clock = Clock()
    budget = TimingBudget(timing(), clock=clock)
    clock.advance(250)
    budget.limit_validity(500)
    assert budget.valid_for_ms == 850
    clock.advance(500)
    with pytest.raises(ScopeError) as error:
        budget.check()
    assert error.value.code == "REQUEST_EXPIRED"


def test_context_budget_is_nested_and_restored():
    first = TimingBudget(timing(), clock=Clock())
    second = TimingBudget(timing(), clock=Clock())
    assert current_budget() is None
    with use_budget(first):
        assert current_budget() is first
        with use_budget(second):
            assert current_budget() is second
        assert current_budget() is first
    assert current_budget() is None


@pytest.mark.parametrize("field,expected", [
    ("max_request_age_ms", "REQUEST_EXPIRED"),
    ("max_snapshot_age_ms", "SNAPSHOT_EXPIRED"),
])
def test_zero_budget_is_well_formed_but_immediately_expired(field, expected):
    with pytest.raises(ScopeError) as error:
        TimingBudget(changed(**{field: 0}), clock=Clock())
    assert error.value.status_code == 409
    assert error.value.code == expected


def test_zero_snapshot_budget_does_not_reject_a_request_without_snapshot():
    budget = TimingBudget(changed(max_snapshot_age_ms=0), clock=Clock(), has_snapshot=False)
    assert budget.valid_for_ms == 3000
