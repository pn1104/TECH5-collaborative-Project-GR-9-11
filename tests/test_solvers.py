"""Unit tests for optimization solvers and distinct alternative generation."""

import pytest

from app.contract import contract
from app.domain import models
from app.engine import solvers
from app.samples import demo_data


def test_assignment_strategy_abc() -> None:
    """Verifies that AssignmentStrategy cannot be instantiated directly."""
    with pytest.raises(TypeError):
        solvers.AssignmentStrategy()  # type: ignore[abstract]


def test_assignment_engine_initialization() -> None:
    """Verifies that AssignmentEngine registers the three strategies."""
    engine = solvers.AssignmentEngine()
    assert isinstance(engine, contract.AssignmentEngineContract)
    assert set(engine.strategies) == {"PREFERENCE", "SKILL_FIT", "BALANCED"}


@pytest.mark.parametrize(
    "strategy_key", ["PREFERENCE", "SKILL_FIT", "BALANCED"]
)
def test_each_strategy_produces_valid_allocation(strategy_key: str) -> None:
    """Verifies every strategy returns a complete, capacity-feasible run."""
    engine = solvers.AssignmentEngine()
    benchmark = demo_data.get_standard_scenario()
    run = engine.run_assignment(
        students=benchmark["students"],
        projects=benchmark["projects"],
        skills=benchmark["skills"],
        strategy_name=strategy_key,
        max_alternatives=1,
    )
    assert run.status == "COMPLETED"
    allocation = run.solutions[0].assignments
    assert len(allocation) == len(benchmark["students"])
    for project in benchmark["projects"]:
        count = sum(1 for a in allocation if a.project_id == project.id)
        assert project.min_capacity <= count <= project.max_capacity


def test_fixed_assignment_is_preserved() -> None:
    """Verifies a locked student stays on the locked project."""
    engine = solvers.AssignmentEngine()
    scenario = demo_data.get_fixed_assignment_scenario()
    run = engine.run_assignment(
        students=scenario["students"],
        projects=scenario["projects"],
        skills=scenario["skills"],
        fixed_assignments=scenario["fixed_assignments"],
        max_alternatives=2,
    )
    assert run.status == "COMPLETED"
    for solution in run.solutions:
        s02 = solution.get_assignment_for_student("S02")
        assert s02 is not None
        assert s02.project_id == "P2"
        assert s02.is_fixed is True


def test_distinct_alternatives_generation() -> None:
    """Verifies AssignmentEngine produces distinct alternatives."""
    benchmark = demo_data.get_standard_scenario()
    engine = solvers.AssignmentEngine()

    run = engine.run_assignment(
        students=benchmark["students"],
        projects=benchmark["projects"],
        skills=benchmark["skills"],
        max_alternatives=3,
    )

    assert run.status == "COMPLETED"
    assert len(run.solutions) >= 2

    # Check distinctness: verify that each pair of solutions differs
    for i in range(len(run.solutions)):
        for j in range(i + 1, len(run.solutions)):
            pairs_i = {
                (a.student_id, a.project_id)
                for a in run.solutions[i].assignments
            }
            pairs_j = {
                (a.student_id, a.project_id)
                for a in run.solutions[j].assignments
            }
            assert (
                pairs_i != pairs_j
            ), f"Solution {i+1} and {j+1} are duplicate allocations!"
