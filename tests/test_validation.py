"""Unit tests for domain validation and feasibility checking."""

from app.domain import models
from app.domain import validation


def test_empty_cohort_validation() -> None:
    """Verifies that empty cohort data is flagged as invalid."""
    res = validation.validate_cohort(students=[], projects=[])
    assert res.is_valid is False
    assert any("Student cohort cannot be empty" in err for err in res.errors)
    assert any("Project catalog cannot be empty" in err for err in res.errors)


def test_duplicate_identifiers() -> None:
    """Verifies detection of duplicate student and project IDs."""
    students = [
        models.Student(id="S01", display_name="Student 1"),
        models.Student(id="S01", display_name="Student 1 Duplicate"),
    ]
    projects = [
        models.Project(id="P1", title="Project 1"),
        models.Project(id="P1", title="Project 1 Duplicate"),
    ]
    res = validation.validate_cohort(students=students, projects=projects)
    assert res.is_valid is False
    assert any("Duplicate student identifier" in err for err in res.errors)
    assert any("Duplicate project identifier" in err for err in res.errors)


def test_capacity_errors() -> None:
    """Verifies detection of negative, zero, or inverted capacities."""
    students = [models.Student(id="S01", display_name="Student 1")]
    projects = [
        models.Project(
            id="P1", title="Invalid Project", min_capacity=5, max_capacity=2
        )
    ]
    res = validation.validate_cohort(students=students, projects=projects)
    assert res.is_valid is False
    assert any("exceeding max capacity" in err for err in res.errors)


def test_contradictory_fixed_assignments() -> None:
    """Verifies detection of contradictory fixed assignments."""
    students = [
        models.Student(id="S01", display_name="S1"),
        models.Student(id="S02", display_name="S2"),
    ]
    projects = [
        models.Project(id="P1", title="P1", max_capacity=1),
        models.Project(id="P2", title="P2", max_capacity=2),
    ]
    # S01 fixed to both P1 and P2
    fixed = [
        models.FixedAssignment(student_id="S01", project_id="P1"),
        models.FixedAssignment(student_id="S01", project_id="P2"),
    ]
    res = validation.validate_cohort(
        students=students, projects=projects, fixed_assignments=fixed
    )
    assert res.is_valid is False
    assert any("Contradictory fixed assignment" in err for err in res.errors)


def test_fixed_exceeding_capacity() -> None:
    """Verifies that fixed assignments exceeding capacity cause error."""
    students = [
        models.Student(id="S01", display_name="S1"),
        models.Student(id="S02", display_name="S2"),
    ]
    projects = [
        models.Project(id="P1", title="P1", max_capacity=1),
    ]
    # 2 fixed assignments to P1 which has max_capacity 1
    fixed = [
        models.FixedAssignment(student_id="S01", project_id="P1"),
        models.FixedAssignment(student_id="S02", project_id="P1"),
    ]
    res = validation.validate_cohort(
        students=students, projects=projects, fixed_assignments=fixed
    )
    assert res.is_feasible is False
    assert any("exceed its maximum capacity" in err for err in res.errors)


def test_aggregate_capacity_deficit() -> None:
    """Verifies detection of aggregate capacity deficit."""
    students = [
        models.Student(id="S01", display_name="S1"),
        models.Student(id="S02", display_name="S2"),
        models.Student(id="S03", display_name="S3"),
    ]
    projects = [
        models.Project(id="P1", title="P1", max_capacity=2),
    ]
    # 3 students, but total capacity is only 2
    res = validation.validate_cohort(students=students, projects=projects)
    assert res.is_feasible is False
    assert any("Insufficient overall capacity" in err for err in res.errors)


# --- Helpers for the tests below -------------------------------------------


def _student(
    s_id: str,
    prefs: list[str] | None = None,
    skills: dict[str, int] | None = None,
) -> models.Student:
    """Builds a student whose preferences are ranked 1, 2, 3, ... in order."""
    return models.Student(
        id=s_id,
        display_name=s_id,
        skills=skills or {},
        preferences=[
            models.Preference(s_id, p_id, rank)
            for rank, p_id in enumerate(prefs or [], start=1)
        ],
    )


def _projects(*ids: str, min_cap: int = 0, max_cap: int = 3) -> list:
    """Builds simple projects without requirements."""
    return [
        models.Project(id=p, title=p, min_capacity=min_cap, max_capacity=max_cap)
        for p in ids
    ]


def _rust_project(p_id: str, min_cap: int, max_cap: int = 3) -> models.Project:
    """Builds a project with a mandatory Rust (level 4) requirement."""
    return models.Project(
        id=p_id,
        title=p_id,
        min_capacity=min_cap,
        max_capacity=max_cap,
        requirements=[
            models.ProjectRequirement(p_id, "rust", 4, is_mandatory=True)
        ],
    )


# --- Malformed numbers -------------------------------------------------------


def test_missing_capacity_is_reported_not_crashing() -> None:
    """A None or non-integer capacity is an error, never an exception."""
    projects = [
        models.Project(id="P1", title="P1", max_capacity=None),  # type: ignore
        models.Project(id="P2", title="P2", min_capacity="2"),  # type: ignore
    ]
    res = validation.validate_cohort([_student("S1", ["P1"])], projects)
    assert res.is_valid is False
    assert any("non-integer max capacity" in e for e in res.errors)
    assert any("non-integer min capacity" in e for e in res.errors)


def test_skill_levels_must_be_between_1_and_5() -> None:
    """Student and requirement levels outside 1-5 are rejected."""
    project = models.Project(
        id="P1",
        title="P1",
        requirements=[models.ProjectRequirement("P1", "py", 0)],
    )
    students = [_student("S1", ["P1"], skills={"py": 9})]
    res = validation.validate_cohort(students, [project])
    assert res.is_valid is False
    assert any("'S1' has invalid level 9" in e for e in res.errors)
    assert any("requires invalid level 0" in e for e in res.errors)


def test_invalid_requirement_level_does_not_crash() -> None:
    """A None requirement level on a mandatory skill is reported cleanly."""
    project = models.Project(
        id="P1",
        title="P1",
        min_capacity=1,
        requirements=[
            models.ProjectRequirement("P1", "py", None, True)  # type: ignore
        ],
    )
    res = validation.validate_cohort([_student("S1", ["P1"])], [project])
    assert res.is_valid is False
    assert any("requires invalid level None" in e for e in res.errors)


# --- Preferences ---------------------------------------------------------------


def test_fewer_than_three_preferences_warns() -> None:
    """Ranking fewer than three projects is allowed but flagged."""
    res = validation.validate_cohort(
        [_student("S1", ["P1", "P2"])], _projects("P1", "P2", "P3")
    )
    assert res.is_valid is True
    assert any("ranked only 2 project(s)" in w for w in res.warnings)


def test_three_preferences_gives_no_preference_warnings() -> None:
    """A clean 1-2-3 ranking produces no warnings at all."""
    res = validation.validate_cohort(
        [_student("S1", ["P1", "P2", "P3"])], _projects("P1", "P2", "P3")
    )
    assert res.is_valid is True
    assert res.warnings == []


def test_rank_below_one_is_rejected() -> None:
    """Ranks must be 1 or higher."""
    student = models.Student(
        id="S1",
        display_name="S1",
        preferences=[models.Preference("S1", "P1", 0)],
    )
    res = validation.validate_cohort([student], _projects("P1"))
    assert res.is_valid is False
    assert any("invalid rank 0" in e for e in res.errors)


def test_same_project_ranked_twice_is_rejected() -> None:
    """Ranking one project twice is an error."""
    student = models.Student(
        id="S1",
        display_name="S1",
        preferences=[
            models.Preference("S1", "P1", 1),
            models.Preference("S1", "P1", 2),
        ],
    )
    res = validation.validate_cohort([student], _projects("P1"))
    assert res.is_valid is False
    assert any("more than once" in e for e in res.errors)


def test_tied_ranks_and_gaps_only_warn() -> None:
    """Tied ranks and gaps (1, 3, 4) are allowed but flagged."""
    tied = models.Student(
        id="S1",
        display_name="S1",
        preferences=[
            models.Preference("S1", "P1", 1),
            models.Preference("S1", "P2", 1),
            models.Preference("S1", "P3", 2),
        ],
    )
    gaps = models.Student(
        id="S2",
        display_name="S2",
        preferences=[
            models.Preference("S2", "P1", 1),
            models.Preference("S2", "P2", 3),
            models.Preference("S2", "P3", 4),
        ],
    )
    res = validation.validate_cohort([tied, gaps], _projects("P1", "P2", "P3"))
    assert res.is_valid is True
    assert any("'S1' has duplicate rank 1" in w for w in res.warnings)
    assert any("'S2' has gaps" in w for w in res.warnings)


def test_preference_listed_under_wrong_student_is_rejected() -> None:
    """A preference whose student_id differs from its owner is an error."""
    student = models.Student(
        id="S1",
        display_name="S1",
        preferences=[models.Preference("S2", "P1", 1)],
    )
    res = validation.validate_cohort([student], _projects("P1"))
    assert res.is_valid is False
    assert any("belongs to student 'S2'" in e for e in res.errors)


# --- Mandatory skills ------------------------------------------------------------


def test_unfillable_optional_project_is_only_a_warning() -> None:
    """A project nobody qualifies for is fine if it may stay empty."""
    projects = [_rust_project("P1", min_cap=0)] + _projects("P2")
    res = validation.validate_cohort([_student("S1", ["P2"])], projects)
    assert res.is_feasible is True
    assert res.is_valid is True
    assert any("'P1' will stay empty" in w for w in res.warnings)


def test_one_qualified_member_is_enough() -> None:
    """Mandatory skills are team-level: one qualified member suffices."""
    students = [
        _student("S1", ["P1"], skills={"rust": 5}),
        _student("S2", ["P1"]),
    ]
    projects = [_rust_project("P1", min_cap=2)] + _projects("P2")
    res = validation.validate_cohort(students, projects)
    assert res.is_feasible is True
    assert res.is_valid is True


def test_unqualified_student_may_be_fixed_to_project() -> None:
    """Locking an unqualified student is fine if a qualified one can join."""
    students = [
        _student("S1", ["P1"]),
        _student("S2", ["P1"], skills={"rust": 5}),
    ]
    projects = [_rust_project("P1", min_cap=0)] + _projects("P2")
    fixed = [models.FixedAssignment("S1", "P1")]
    res = validation.validate_cohort(students, projects, fixed_assignments=fixed)
    assert res.is_feasible is True


def test_qualified_students_all_fixed_elsewhere() -> None:
    """A needed project fails if every qualified student is locked away."""
    students = [
        _student("S1", ["P2"], skills={"rust": 5}),
        _student("S2", ["P1"]),
    ]
    projects = [_rust_project("P1", min_cap=1)] + _projects("P2")
    fixed = [models.FixedAssignment("S1", "P2")]
    res = validation.validate_cohort(students, projects, fixed_assignments=fixed)
    assert res.is_feasible is False
    assert any(
        "fixed to another project" in r for r in res.infeasibility_reasons
    )


def test_project_filled_by_unqualified_locks() -> None:
    """Locks that fill a project without anyone qualified are infeasible."""
    students = [
        _student("S1", ["P1"]),
        _student("S2", ["P2"], skills={"rust": 5}),
    ]
    projects = [_rust_project("P1", min_cap=0, max_cap=1)] + _projects("P2")
    fixed = [models.FixedAssignment("S1", "P1")]
    res = validation.validate_cohort(students, projects, fixed_assignments=fixed)
    assert res.is_feasible is False
    assert any(
        "filled by fixed assignments" in r for r in res.infeasibility_reasons
    )


def test_empty_projects_reduce_usable_capacity() -> None:
    """Places in projects that must stay empty don't count."""
    students = [_student(s, ["P2"]) for s in ("S1", "S2", "S3")]
    projects = [_rust_project("P1", min_cap=0)] + _projects("P2", max_cap=2)
    res = validation.validate_cohort(students, projects)
    assert res.is_feasible is False
    assert any("Only 2 places are usable" in r for r in res.infeasibility_reasons)


# --- Fixed assignments -------------------------------------------------------------


def test_repeated_identical_lock_is_counted_once() -> None:
    """The same lock entered twice warns, and is not a contradiction."""
    fixed = [models.FixedAssignment("S1", "P1")] * 2
    res = validation.validate_cohort(
        [_student("S1", ["P1"])],
        _projects("P1", max_cap=1),
        fixed_assignments=fixed,
    )
    assert res.is_valid is True
    assert any("listed more than once" in w for w in res.warnings)


def test_fixed_to_unranked_project_warns() -> None:
    """Locking a student into a project they did not rank is flagged."""
    fixed = [models.FixedAssignment("S1", "P2")]
    res = validation.validate_cohort(
        [_student("S1", ["P1"])],
        _projects("P1", "P2"),
        fixed_assignments=fixed,
    )
    assert res.is_valid is True
    assert any("which they did not rank" in w for w in res.warnings)


def test_locks_and_minimums_exceed_cohort() -> None:
    """Locks that overfill one project starve another project's minimum."""
    students = [_student(s, ["P1"]) for s in ("S1", "S2", "S3")]
    projects = [
        models.Project(id="P1", title="P1", min_capacity=1, max_capacity=3),
        models.Project(id="P2", title="P2", min_capacity=2, max_capacity=3),
    ]
    fixed = [models.FixedAssignment(s, "P1") for s in ("S1", "S2")]
    res = validation.validate_cohort(students, projects, fixed_assignments=fixed)
    assert res.is_feasible is False
    assert any("together need 4 students" in r for r in res.infeasibility_reasons)


def test_demo_scenario_is_clean() -> None:
    """The standard demo cohort passes with no errors or warnings."""
    from app.samples import demo_data

    sc = demo_data.get_standard_scenario()
    res = validation.validate_cohort(
        sc["students"], sc["projects"], sc["skills"], sc["fixed_assignments"]
    )
    assert res.is_valid is True
    assert res.is_feasible is True
    assert res.warnings == []
