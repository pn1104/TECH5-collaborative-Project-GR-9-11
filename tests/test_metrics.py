"""Unit tests for analytical indicators, fairness, and comparison."""

import pytest

from app.domain import models
from app.engine import metrics


def test_gini_calculation() -> None:
    """Verifies that Gini coefficient calculation matches expectations."""
    # Complete equality
    assert metrics.calculate_gini([2.0, 2.0, 2.0, 2.0]) == 0.0
    # Inequality
    gini = metrics.calculate_gini([1.0, 1.0, 1.0, 10.0])
    assert 0.0 < gini < 1.0


def test_skill_fit_calculation() -> None:
    """Verifies skill fit score computation for student and project."""
    student = models.Student(
        id="S1", display_name="S1", skills={"py": 3, "sql": 1}
    )
    project = models.Project(
        id="P1",
        title="P1",
        requirements=[
            models.ProjectRequirement(
                project_id="P1", skill_id="py", minimum_level=3
            ),
            models.ProjectRequirement(
                project_id="P1", skill_id="sql", minimum_level=2
            ),
        ],
    )

    fit, unmet = metrics.calculate_assignment_skill_fit(student, project)
    # py is 100% satisfied, sql is 1/2 = 50% satisfied. Average = 75%
    assert fit == 0.75
    assert unmet == ["sql"]


def test_solution_indicators_calculation() -> None:
    """Verifies full indicator computation for a solution."""
    students = [
        models.Student(
            id="S1",
            display_name="S1",
            preferences=[
                models.Preference(student_id="S1", project_id="P1", rank=1)
            ],
        ),
        models.Student(
            id="S2",
            display_name="S2",
            preferences=[
                models.Preference(student_id="S2", project_id="P1", rank=2)
            ],
        ),
    ]
    projects = [models.Project(id="P1", title="P1", max_capacity=2)]
    assignments = [
        models.Assignment(
            student_id="S1",
            project_id="P1",
            preference_rank=1,
            skill_fit_score=1.0,
        ),
        models.Assignment(
            student_id="S2",
            project_id="P1",
            preference_rank=2,
            skill_fit_score=0.8,
        ),
    ]

    indicators = metrics.compute_solution_indicators(
        students=students, projects=projects, assignments=assignments
    )

    assert indicators["feasibility"]["is_feasible"] is True
    assert indicators["efficiency"]["mean_skill_fit"] == 0.9
    assert indicators["fairness"]["mean_rank"] == 1.5
    assert indicators["fairness"]["worst_rank"] == 2
    assert indicators["fairness"]["unranked_count"] == 0
    assert indicators["capacity"]["overall_utilization_pct"] == 100.0


def test_solution_comparison() -> None:
    """Verifies comparative trade-off calculation between two solutions."""
    sol_a = models.Solution(
        id="sol-a",
        run_id="run-1",
        alternative_number=1,
        strategy_name="PREFERENCE",
        assignments=[
            models.Assignment(
                student_id="S1",
                project_id="P1",
                preference_rank=1,
                skill_fit_score=0.5,
            ),
            models.Assignment(
                student_id="S2",
                project_id="P2",
                preference_rank=1,
                skill_fit_score=0.6,
            ),
        ],
        indicators={
            "efficiency": {"mean_skill_fit": 0.55},
            "fairness": {"mean_rank": 1.0, "unranked_count": 0},
        },
    )

    # In Solution B, S1 and S2 swapped projects
    sol_b = models.Solution(
        id="sol-b",
        run_id="run-1",
        alternative_number=2,
        strategy_name="SKILL_FIT",
        assignments=[
            models.Assignment(
                student_id="S1",
                project_id="P2",
                preference_rank=3,
                skill_fit_score=1.0,
            ),
            models.Assignment(
                student_id="S2",
                project_id="P1",
                preference_rank=2,
                skill_fit_score=0.9,
            ),
        ],
        indicators={
            "efficiency": {"mean_skill_fit": 0.95},
            "fairness": {"mean_rank": 2.5, "unranked_count": 0},
        },
    )

    comp = metrics.compare_two_solutions(sol_a, sol_b)
    assert comp["is_distinct"] is True
    assert comp["changed_students_count"] == 2
    assert comp["delta_mean_skill_fit"] == 0.4
    assert comp["delta_mean_rank"] == 1.5
    assert comp["rank_worsened_count"] == 2


# ---------------------------------------------------------------------------
# Additional Team B tests: edge cases from the analytical note (Sections 3-4)
# ---------------------------------------------------------------------------


def _req(
    project_id: str, skill_id: str, level: int, mandatory: bool = False
) -> models.ProjectRequirement:
    return models.ProjectRequirement(
        project_id=project_id,
        skill_id=skill_id,
        minimum_level=level,
        is_mandatory=mandatory,
    )


def _stud(
    sid: str, ranking: list[str] | None = None, skills: dict | None = None
) -> models.Student:
    return models.Student(
        id=sid,
        display_name=sid,
        skills=skills or {},
        preferences=[
            models.Preference(student_id=sid, project_id=pid, rank=i)
            for i, pid in enumerate(ranking or [], start=1)
        ],
    )


def _asg(
    sid: str,
    pid: str,
    rank: int | None = None,
    fit: float = 1.0,
    unmet: list[str] | None = None,
) -> models.Assignment:
    return models.Assignment(
        student_id=sid,
        project_id=pid,
        preference_rank=rank,
        skill_fit_score=fit,
        unmet_requirements=unmet or [],
    )


# --- Skill fit -------------------------------------------------------------


def test_skill_fit_no_requirements_is_one() -> None:
    project = models.Project(id="P1", title="P1")
    assert metrics.calculate_assignment_skill_fit(_stud("S1"), project) == (
        1.0,
        [],
    )


def test_skill_fit_caps_at_one_and_counts_missing_skill_as_zero() -> None:
    project = models.Project(
        id="P1",
        title="P1",
        requirements=[_req("P1", "py", 2), _req("P1", "rust", 4, True)],
    )
    student = _stud("S1", skills={"py": 5})  # exceeds py, lacks rust
    fit, unmet = metrics.calculate_assignment_skill_fit(student, project)
    assert fit == 0.5  # (min(1, 5/2) + 0/4) / 2
    assert unmet == ["rust"]


def test_skill_fit_includes_mandatory_requirements() -> None:
    project = models.Project(
        id="P1",
        title="P1",
        requirements=[_req("P1", "py", 4, True), _req("P1", "sql", 2)],
    )
    fit, unmet = metrics.calculate_assignment_skill_fit(
        _stud("S1", skills={"py": 2, "sql": 2}), project
    )
    assert fit == 0.75
    assert unmet == ["py"]


# --- Gini ------------------------------------------------------------------


def test_gini_examples_from_note() -> None:
    assert metrics.calculate_gini([2.0, 2.0]) == 0.0
    assert metrics.calculate_gini([1.0, 3.0]) == pytest.approx(0.25)
    assert metrics.calculate_gini([3.0, 5.0]) == pytest.approx(0.125)


def test_gini_matches_pairwise_formula() -> None:
    values = [1.0, 1.0, 2.0, 4.0, 4.0, 7.0]
    n = len(values)
    pairwise = sum(abs(a - b) for a in values for b in values) / (
        2 * n * sum(values)
    )
    assert metrics.calculate_gini(values) == pytest.approx(pairwise)


def test_gini_degenerate_inputs() -> None:
    assert metrics.calculate_gini([]) == 0.0
    assert metrics.calculate_gini([0.0, 0.0]) == 0.0
    with pytest.raises(ValueError):
        metrics.calculate_gini([1.0, -1.0])


# --- Solution indicators ---------------------------------------------------


def test_indicators_count_unranked_as_m_plus_one() -> None:
    projects = [
        models.Project(id="P1", title="P1", max_capacity=2),
        models.Project(id="P2", title="P2", max_capacity=2),
    ]
    students = [_stud("S1", ["P1"]), _stud("S2", ["P1"])]
    ind = metrics.compute_solution_indicators(
        students, projects, [_asg("S1", "P1", 1), _asg("S2", "P2")]
    )
    fair = ind["fairness"]
    assert fair["unranked_rank"] == 3
    assert fair["unranked_count"] == 1
    assert fair["unranked_students"] == ["S2"]
    assert fair["mean_rank"] == 2.0  # (1 + 3) / 2
    assert fair["worst_rank"] == 3
    assert fair["rank_gini"] == 0.25
    assert fair["rank_distribution"] == {"rank_1": 1, "unranked": 1}
    assert fair["unranked_pct"] == 50.0


def test_indicators_recompute_rank_from_preferences() -> None:
    """A wrong stored preference_rank must not change the fairness numbers."""
    projects = [models.Project(id="P1", title="P1", max_capacity=1)]
    ind = metrics.compute_solution_indicators(
        [_stud("S1", ["P1"])], projects, [_asg("S1", "P1", rank=5)]
    )
    assert ind["fairness"]["mean_rank"] == 1.0


def test_indicators_feasible_solution_has_all_checks_passing() -> None:
    projects = [
        models.Project(
            id="P1",
            title="P1",
            min_capacity=1,
            max_capacity=2,
            requirements=[_req("P1", "py", 3, mandatory=True)],
        ),
        models.Project(id="P2", title="P2", min_capacity=0, max_capacity=2),
    ]
    students = [
        _stud("S1", ["P1"], {"py": 3}),
        _stud("S2", ["P1"]),  # no py, but S1 covers the team
    ]
    fixed = [models.FixedAssignment(student_id="S1", project_id="P1")]
    ind = metrics.compute_solution_indicators(
        students,
        projects,
        [_asg("S1", "P1", 1), _asg("S2", "P1", 1, 0.0, ["py"])],
        fixed,
    )
    feas = ind["feasibility"]
    assert feas["is_feasible"] is True
    assert feas["violations"] == []
    assert all(feas["checks"].values())
    assert feas["mandatory_requirements_applicable"] == 1
    assert feas["mandatory_requirements_fulfilled"] == 1
    assert feas["fixed_assignments_respected"] == 1
    # Empty project with min 0 is allowed and flagged as empty.
    assert ind["capacity"]["empty_projects"] == ["P2"]
    assert ind["capacity"]["projects"]["P1"]["is_full"] is True
    # The individual gap is counted, but not as a soft requirement.
    assert ind["efficiency"]["unmet_requirements_count"] == 1
    assert ind["efficiency"]["unmet_soft_requirements_count"] == 0
    assert ind["efficiency"]["unmet_mandatory_individual_count"] == 1


def test_indicators_report_every_violation() -> None:
    projects = [
        models.Project(
            id="P1",
            title="P1",
            max_capacity=1,
            requirements=[_req("P1", "rust", 2, mandatory=True)],
        ),
        models.Project(id="P2", title="P2", min_capacity=1, max_capacity=2),
    ]
    students = [_stud("S1"), _stud("S2"), _stud("S3"), _stud("S4")]
    fixed = [models.FixedAssignment(student_id="S1", project_id="P2")]
    assignments = [
        _asg("S1", "P1"),
        _asg("S2", "P1"),  # P1 over capacity, P2 empty but min 1
        _asg("S3", "P1"),
        _asg("S3", "P2"),  # S3 twice; S4 missing
        _asg("S9", "P1"),  # unknown student
        _asg("S4", "PX"),  # unknown project
    ]
    ind = metrics.compute_solution_indicators(
        students, projects, assignments, fixed
    )
    feas = ind["feasibility"]
    text = " ".join(feas["violations"])
    assert feas["is_feasible"] is False
    assert not any(feas["checks"].values())
    assert "S9" in text and "PX" in text
    assert "Student 'S4' has no project" in text
    assert "'S3' is assigned to 2 projects" in text
    assert "above its maximum" in text
    assert "rust" in text
    assert "Fixed assignment broken" in text


def test_indicators_below_minimum_is_violation() -> None:
    projects = [
        models.Project(id="P1", title="P1", min_capacity=2, max_capacity=3)
    ]
    ind = metrics.compute_solution_indicators(
        [_stud("S1", ["P1"])], projects, [_asg("S1", "P1", 1)]
    )
    assert ind["feasibility"]["checks"]["capacity_respected"] is False
    assert "below its minimum" in ind["feasibility"]["violations"][0]


def test_indicators_capacity_figures() -> None:
    projects = [
        models.Project(id="P1", title="P1", min_capacity=1, max_capacity=4),
        models.Project(id="P2", title="P2", min_capacity=1, max_capacity=4),
    ]
    students = [_stud(f"S{i}", ["P1", "P2"]) for i in range(3)]
    ind = metrics.compute_solution_indicators(
        students,
        projects,
        [_asg("S0", "P1", 1), _asg("S1", "P1", 1), _asg("S2", "P2", 2)],
    )
    cap = ind["capacity"]
    assert cap["total_capacity"] == 8
    assert cap["free_places"] == 5
    assert cap["overall_utilization_pct"] == 37.5
    assert cap["projects"]["P1"]["utilization_pct"] == 50.0
    assert cap["projects"]["P2"]["is_at_minimum"] is True
    assert cap["projects"]["P2"]["margin_above_min"] == 0


def test_indicators_empty_cohort() -> None:
    ind = metrics.compute_solution_indicators([], [], [])
    assert ind["feasibility"]["is_feasible"] is True
    assert ind["efficiency"]["mean_skill_fit"] == 0.0
    assert ind["fairness"]["mean_rank"] == 0.0
    assert ind["capacity"]["overall_utilization_pct"] == 0.0


# --- Comparison ------------------------------------------------------------


def _sol(sol_id: str, alt: int, assignments, indicators=None):
    return models.Solution(
        id=sol_id,
        run_id="run-1",
        alternative_number=alt,
        strategy_name="TEST",
        assignments=assignments,
        indicators=indicators or {},
    )


def test_compare_identical_solutions() -> None:
    asgs = [_asg("S1", "P1", 1, 0.5)]
    comp = metrics.compare_two_solutions(_sol("a", 1, asgs), _sol("b", 2, asgs))
    assert comp["is_distinct"] is False
    assert comp["changed_students_count"] == 0
    assert comp["delta_metrics"]["mean_skill_fit"]["direction"] == "tie"
    assert comp["trade_off_summary"] == [
        "Both solutions assign every student to the same project."
    ]


def test_compare_lists_worst_first_and_handles_unranked() -> None:
    sol_a = _sol(
        "a",
        1,
        [_asg("S1", "P1", 1), _asg("S2", "P2", 2), _asg("S3", "P3", 1)],
        {"fairness": {"unranked_rank": 4}},
    )
    sol_b = _sol(
        "b",
        2,
        [_asg("S1", "P2", 2), _asg("S2", "P1", 1), _asg("S3", "P1", None)],
        {"fairness": {"unranked_rank": 4}},
    )
    comp = metrics.compare_two_solutions(sol_a, sol_b)
    order = [c["student_id"] for c in comp["changed_assignments"]]
    assert order == ["S3", "S1", "S2"]  # rank deltas +3, +1, -1
    s3 = comp["changed_assignments"][0]
    assert s3["rank_b"] == 4 and s3["unranked_b"] is True
    assert comp["rank_worsened_count"] == 2
    assert comp["rank_improved_count"] == 1


def test_compare_equal_rank_move() -> None:
    sol_a = _sol("a", 1, [_asg("S1", "P1", 1, 0.4)])
    sol_b = _sol("b", 2, [_asg("S1", "P2", 1, 0.9)])
    comp = metrics.compare_two_solutions(sol_a, sol_b)
    change = comp["changed_assignments"][0]
    assert change["status"] == "equal_rank"
    assert change["skill_fit_delta"] == 0.5
    assert comp["equal_rank_moved_count"] == 1


def test_compare_derives_metrics_when_indicators_missing() -> None:
    sol_a = _sol("a", 1, [_asg("S1", "P1", 1, 0.5), _asg("S2", "P2", 1, 0.5)])
    sol_b = _sol("b", 2, [_asg("S1", "P2", 2, 1.0), _asg("S2", "P1", 1, 1.0)])
    comp = metrics.compare_two_solutions(sol_a, sol_b)
    assert comp["delta_mean_skill_fit"] == 0.5
    assert comp["delta_mean_rank"] == 0.5
    fit = comp["delta_metrics"]["mean_skill_fit"]
    rank = comp["delta_metrics"]["mean_rank"]
    assert fit["direction"] == "better"
    assert rank["direction"] == "worse"
    assert (
        "Trade-off: B gains skill fit at the cost of student preferences."
        in comp["trade_off_summary"]
    )


def test_compare_output_fits_run_comparison_model() -> None:
    projects = [
        models.Project(id="P1", title="P1", max_capacity=1),
        models.Project(id="P2", title="P2", max_capacity=1),
    ]
    students = [_stud("S1", ["P1", "P2"]), _stud("S2", ["P1", "P2"])]
    asg_a = [_asg("S1", "P1", 1), _asg("S2", "P2", 2)]
    asg_b = [_asg("S1", "P2", 2), _asg("S2", "P1", 1)]
    sol_a = _sol(
        "a", 1, asg_a, metrics.compute_solution_indicators(students, projects, asg_a)
    )
    sol_b = _sol(
        "b", 2, asg_b, metrics.compute_solution_indicators(students, projects, asg_b)
    )
    comparison = models.RunComparison.from_dict(
        metrics.compare_two_solutions(sol_a, sol_b)
    )
    assert comparison.changed_students_count == 2
    assert comparison.delta_mean_rank == 0.0
    assert comparison.rank_improved_count == 1
    assert comparison.rank_worsened_count == 1
    assert comparison.solution_b_alt == 2
