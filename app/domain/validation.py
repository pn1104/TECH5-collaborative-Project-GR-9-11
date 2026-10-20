"""Validation logic for students, projects, preferences, and constraints.

This module enforces domain integrity rules and detects edge cases described
in Section 13 of the TECH5 specification, including contradictory constraints,
capacity deficits, unknown identifiers, and skill incompatibilities.

Every problem is classified as one of:

* error: the input is rejected and the solver must not run.
* error + infeasibility reason: the input is well-formed, but the hard
  constraints provably admit no assignment.
* warning: the run may proceed, but the user should know about it.

The validator never raises on malformed input; it reports it instead.
"""

import dataclasses
from typing import Any

from app.domain import models

MIN_SKILL_LEVEL = 1
MAX_SKILL_LEVEL = 5
MIN_RECOMMENDED_PREFERENCES = 3


@dataclasses.dataclass
class ValidationResult:
    """Represents the outcome of cohort data and constraint validation.

    Attributes:
        is_valid: True if input data has no structural or relational errors.
        errors: List of fatal error messages that prevent optimization.
        warnings: List of non-fatal informational notices or edge-case flags.
        is_feasible: False if hard mathematical constraints guarantee no
            feasible assignment exists.
        infeasibility_reasons: Detailed explanations if proven infeasible.
    """

    is_valid: bool = True
    errors: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)
    is_feasible: bool = True
    infeasibility_reasons: list[str] = dataclasses.field(default_factory=list)

    def add_infeasibility(self, message: str) -> None:
        """Records a proven infeasibility (also counted as a fatal error).

        Args:
            message: Explanation of why no feasible assignment exists.
        """
        self.is_feasible = False
        self.errors.append(message)
        self.infeasibility_reasons.append(message)

    def to_dict(self) -> dict[str, Any]:
        """Serializes validation results to a dictionary.

        Returns:
            Dictionary containing validity flags and messages.
        """
        return {
            "is_valid": self.is_valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "is_feasible": self.is_feasible,
            "infeasibility_reasons": list(self.infeasibility_reasons),
        }


def _is_int(value: Any) -> bool:
    """Returns True for real integers (bool is excluded on purpose)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_valid_level(value: Any) -> bool:
    """Returns True if value is an integer proficiency level from 1 to 5."""
    return _is_int(value) and MIN_SKILL_LEVEL <= value <= MAX_SKILL_LEVEL


def _is_blank(identifier: Any) -> bool:
    """Returns True if an identifier is missing or only whitespace."""
    return identifier is None or not str(identifier).strip()


def _student_level(student: models.Student, skill_id: str) -> int:
    """Returns a student's level for a skill, treating bad values as 0."""
    level = student.skills.get(skill_id, 0)
    return level if _is_int(level) else 0


def _meets(student: models.Student, req: models.ProjectRequirement) -> bool:
    """Returns True if the student meets the requirement's minimum level."""
    return _student_level(student, req.skill_id) >= req.minimum_level


def _check_students(
    students: list[models.Student], result: ValidationResult
) -> set[str]:
    """Checks student identifiers and skill levels.

    Returns:
        The set of unique, non-blank student identifiers.
    """
    student_ids: set[str] = set()
    for student in students:
        if _is_blank(student.id):
            result.errors.append("Student found with empty identifier.")
        elif student.id in student_ids:
            result.errors.append(
                f"Duplicate student identifier detected: '{student.id}'."
            )
        else:
            student_ids.add(student.id)

        for skill_id, level in student.skills.items():
            if not _is_valid_level(level):
                result.errors.append(
                    f"Student '{student.id}' has invalid level {level!r} for "
                    f"skill '{skill_id}' (must be an integer from "
                    f"{MIN_SKILL_LEVEL} to {MAX_SKILL_LEVEL})."
                )
    return student_ids


def _check_projects(
    projects: list[models.Project], result: ValidationResult
) -> tuple[set[str], bool]:
    """Checks project identifiers, capacities, and requirement levels.

    Returns:
        The set of unique project identifiers, and whether all capacities
        and required levels are usable numbers (needed before any
        feasibility arithmetic).
    """
    project_ids: set[str] = set()
    numbers_ok = True
    for project in projects:
        if _is_blank(project.id):
            result.errors.append("Project found with empty identifier.")
        elif project.id in project_ids:
            result.errors.append(
                f"Duplicate project identifier detected: '{project.id}'."
            )
        else:
            project_ids.add(project.id)

        min_cap, max_cap = project.min_capacity, project.max_capacity
        if not _is_int(max_cap):
            numbers_ok = False
            result.errors.append(
                f"Project '{project.id}' has missing or non-integer max "
                f"capacity: {max_cap!r}."
            )
        elif max_cap <= 0:
            result.errors.append(
                f"Project '{project.id}' has non-positive max capacity: "
                f"{max_cap}."
            )
        if not _is_int(min_cap):
            numbers_ok = False
            result.errors.append(
                f"Project '{project.id}' has missing or non-integer min "
                f"capacity: {min_cap!r}."
            )
        elif min_cap < 0:
            result.errors.append(
                f"Project '{project.id}' has negative min capacity: "
                f"{min_cap}."
            )
        if _is_int(min_cap) and _is_int(max_cap) and min_cap > max_cap:
            result.errors.append(
                f"Project '{project.id}' has min capacity "
                f"({min_cap}) exceeding max capacity ({max_cap})."
            )

        for req in project.requirements:
            if not _is_valid_level(req.minimum_level):
                numbers_ok = False
                result.errors.append(
                    f"Project '{project.id}' requires invalid level "
                    f"{req.minimum_level!r} for skill '{req.skill_id}' (must "
                    f"be an integer from {MIN_SKILL_LEVEL} to "
                    f"{MAX_SKILL_LEVEL})."
                )
    return project_ids, numbers_ok


def _check_skill_catalog(
    students: list[models.Student],
    projects: list[models.Project],
    skills: list[models.Skill] | None,
    result: ValidationResult,
) -> None:
    """Rejects skills that are not in the catalog (if a catalog is given)."""
    if not skills:
        return
    catalog = {s.id for s in skills}
    for student in students:
        for skill_id in student.skills:
            if skill_id not in catalog:
                result.errors.append(
                    f"Student '{student.id}' lists uncatalogued skill "
                    f"'{skill_id}'."
                )
    for project in projects:
        for req in project.requirements:
            if req.skill_id not in catalog:
                result.errors.append(
                    f"Project '{project.id}' demands uncatalogued skill "
                    f"'{req.skill_id}'."
                )


def _check_preferences(
    students: list[models.Student],
    project_ids: set[str],
    result: ValidationResult,
) -> None:
    """Checks each student's ranked preferences.

    Errors: unknown project, project ranked twice, rank below 1 or not an
    integer, preference owned by another student. Warnings: no or fewer
    than three preferences, tied ranks, gaps in the ranking.
    """
    for student in students:
        if not student.preferences:
            result.warnings.append(
                f"Student '{student.display_name}' ({student.id}) has "
                "submitted no ranked preferences."
            )
            continue

        seen_projects: set[str] = set()
        seen_ranks: set[int] = set()
        for pref in student.preferences:
            if pref.student_id != student.id:
                result.errors.append(
                    f"Preference for project '{pref.project_id}' belongs to "
                    f"student '{pref.student_id}' but is listed under "
                    f"student '{student.id}'."
                )
            if pref.project_id not in project_ids:
                result.errors.append(
                    f"Student '{student.id}' ranked unknown project "
                    f"'{pref.project_id}'."
                )
            if pref.project_id in seen_projects:
                result.errors.append(
                    f"Student '{student.id}' ranked project "
                    f"'{pref.project_id}' more than once."
                )
            seen_projects.add(pref.project_id)

            if not _is_int(pref.rank) or pref.rank < 1:
                result.errors.append(
                    f"Student '{student.id}' has invalid rank {pref.rank!r} "
                    f"for project '{pref.project_id}' (must be 1 or higher)."
                )
                continue
            if pref.rank in seen_ranks:
                result.warnings.append(
                    f"Student '{student.id}' has duplicate rank {pref.rank} "
                    "(tied preferences)."
                )
            seen_ranks.add(pref.rank)

        if len(seen_projects) < MIN_RECOMMENDED_PREFERENCES:
            result.warnings.append(
                f"Student '{student.id}' ranked only {len(seen_projects)} "
                f"project(s); at least {MIN_RECOMMENDED_PREFERENCES} are "
                "expected."
            )
        if seen_ranks and sorted(seen_ranks) != list(
            range(1, len(seen_ranks) + 1)
        ):
            result.warnings.append(
                f"Student '{student.id}' has gaps in their ranking "
                f"{sorted(seen_ranks)}; ranks are used as given."
            )


def _check_fixed_assignments(
    students: list[models.Student],
    projects: list[models.Project],
    fixed_assignments: list[models.FixedAssignment],
    student_ids: set[str],
    project_ids: set[str],
    result: ValidationResult,
) -> dict[str, str]:
    """Checks fixed locks for unknown IDs, conflicts, and repeats.

    Returns:
        Mapping of student ID to locked project ID, for locks that are
        unambiguous and reference known entities.
    """
    projects_by_student: dict[str, list[str]] = {}
    for fixed in fixed_assignments:
        if fixed.student_id not in student_ids:
            result.errors.append(
                f"Fixed assignment references unknown student "
                f"'{fixed.student_id}'."
            )
        if fixed.project_id not in project_ids:
            result.errors.append(
                f"Fixed assignment references unknown project "
                f"'{fixed.project_id}'."
            )
        locked = projects_by_student.setdefault(fixed.student_id, [])
        if fixed.project_id in locked:
            result.warnings.append(
                f"Fixed assignment of student '{fixed.student_id}' to "
                f"project '{fixed.project_id}' is listed more than once; "
                "it is counted once."
            )
        else:
            locked.append(fixed.project_id)

    locks: dict[str, str] = {}
    for s_id, locked in projects_by_student.items():
        if len(locked) > 1:
            result.errors.append(
                f"Contradictory fixed assignment: student '{s_id}' is "
                f"fixed to {len(locked)} different projects "
                f"({', '.join(locked)})."
            )
        elif s_id in student_ids and locked[0] in project_ids:
            locks[s_id] = locked[0]

    students_by_id = {s.id: s for s in students}
    for s_id, p_id in locks.items():
        student = students_by_id[s_id]
        if student.preferences and student.get_preference_rank(p_id) is None:
            result.warnings.append(
                f"Student '{s_id}' is fixed to project '{p_id}', which they "
                "did not rank."
            )
    return locks


def _check_feasibility(
    students: list[models.Student],
    projects: list[models.Project],
    locks: dict[str, str],
    enforce_exact_allocation: bool,
    result: ValidationResult,
) -> None:
    """Proves infeasibility from capacities, locks, and mandatory skills.

    These are necessary conditions only: passing them does not guarantee
    that the solver finds a solution, but failing them guarantees it won't.
    """
    cohort_size = len(students)

    # Locks per project.
    locked_count: dict[str, int] = {}
    for p_id in locks.values():
        locked_count[p_id] = locked_count.get(p_id, 0) + 1
    for p in projects:
        if locked_count.get(p.id, 0) > p.max_capacity:
            result.add_infeasibility(
                f"Fixed assignments ({locked_count[p.id]}) for project "
                f"'{p.id}' exceed its maximum capacity ({p.max_capacity})."
            )

    # Aggregate capacity.
    total_max = sum(p.max_capacity for p in projects)
    total_min = sum(p.min_capacity for p in projects)
    if enforce_exact_allocation and cohort_size > total_max:
        result.add_infeasibility(
            f"Insufficient overall capacity: total cohort size "
            f"({cohort_size}) exceeds aggregate maximum project capacity "
            f"({total_max})."
        )
    if cohort_size < total_min:
        result.add_infeasibility(
            f"Cohort size ({cohort_size}) is below aggregate minimum "
            f"project capacity ({total_min})."
        )
    else:
        # Locks can push a project above its minimum, using up students.
        needed = sum(
            max(p.min_capacity, locked_count.get(p.id, 0)) for p in projects
        )
        if needed > cohort_size:
            result.add_infeasibility(
                f"Fixed assignments and minimum capacities together need "
                f"{needed} students, but the cohort has only {cohort_size}."
            )

    # Mandatory skills are team-level: a project with members needs at
    # least one member meeting each mandatory requirement. Members who
    # lack the skill are allowed.
    students_by_id = {s.id: s for s in students}
    unusable: list[models.Project] = []
    for project in projects:
        mandatory = [r for r in project.requirements if r.is_mandatory]
        locked_here = [
            students_by_id[s_id] for s_id, p_id in locks.items()
            if p_id == project.id
        ]
        must_have_members = project.min_capacity > 0 or bool(locked_here)
        for req in mandatory:
            # Who could cover this requirement: anyone not fixed elsewhere.
            candidates = [
                s for s in students
                if _meets(s, req) and locks.get(s.id, project.id) == project.id
            ]
            if not candidates:
                if not must_have_members:
                    unusable.append(project)
                    result.warnings.append(
                        f"Project '{project.id}' will stay empty: no "
                        f"available student meets its mandatory skill "
                        f"'{req.skill_id}' (level {req.minimum_level})."
                    )
                elif not any(_meets(s, req) for s in students):
                    result.add_infeasibility(
                        f"Mandatory requirement impossible: No student in "
                        f"cohort meets mandatory skill '{req.skill_id}' "
                        f"(level {req.minimum_level}) for project "
                        f"'{project.id}'."
                    )
                else:
                    result.add_infeasibility(
                        f"Mandatory requirement impossible for project "
                        f"'{project.id}': every student with skill "
                        f"'{req.skill_id}' (level {req.minimum_level}) is "
                        "fixed to another project."
                    )
                break
            if len(locked_here) >= project.max_capacity and not any(
                _meets(s, req) for s in locked_here
            ):
                result.add_infeasibility(
                    f"Project '{project.id}' is filled by fixed assignments, "
                    f"but none of them meets mandatory skill "
                    f"'{req.skill_id}' (level {req.minimum_level})."
                )

    # Projects that must stay empty take no students.
    if enforce_exact_allocation and unusable and cohort_size <= total_max:
        usable = total_max - sum(p.max_capacity for p in unusable)
        if cohort_size > usable:
            result.add_infeasibility(
                f"Only {usable} places are usable because project(s) "
                f"{', '.join(p.id for p in unusable)} must stay "
                f"empty, but the cohort has {cohort_size} students."
            )


def validate_cohort(
    students: list[models.Student],
    projects: list[models.Project],
    skills: list[models.Skill] | None = None,
    fixed_assignments: list[models.FixedAssignment] | None = None,
    enforce_exact_allocation: bool = True,
) -> ValidationResult:
    """Validates complete cohort inputs and checks for structural infeasibility.

    Args:
        students: List of students in the cohort.
        projects: List of available semester projects.
        skills: Optional list of defined skills in the catalog. When given,
            skills outside the catalog are rejected.
        fixed_assignments: Optional list of locked pre-allocations.
        enforce_exact_allocation: Whether every student must receive a project.

    Returns:
        A ValidationResult detailing validity, warnings, and feasibility.
    """
    result = ValidationResult()

    if not students:
        result.errors.append("Student cohort cannot be empty.")
    if not projects:
        result.errors.append("Project catalog cannot be empty.")

    student_ids = _check_students(students, result)
    project_ids, numbers_ok = _check_projects(projects, result)
    _check_skill_catalog(students, projects, skills, result)
    _check_preferences(students, project_ids, result)
    locks = _check_fixed_assignments(
        students,
        projects,
        fixed_assignments or [],
        student_ids,
        project_ids,
        result,
    )

    # Feasibility arithmetic is only meaningful once the numbers are valid.
    if numbers_ok and students and projects:
        _check_feasibility(
            students, projects, locks, enforce_exact_allocation, result
        )

    result.is_valid = not result.errors
    return result
