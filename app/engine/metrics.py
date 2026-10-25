"""Calculators for feasibility, efficiency, fairness, and trade-offs.

This module provides analytical functions to evaluate solutions according to
the requirements in Section 7 of the TECH5 specification.

Definitions follow Sections 3 and 4 of the Team B analytical note:

- Effective rank: a student's stated rank for the assigned project, or
  m + 1 (m = number of projects) when the project is not on their list.
- Skill fit: average over all project requirements of
  min(1, student level / required level). Projects without requirements
  score 1. A missing skill counts as level 0.
- Mandatory requirements are team-level: a non-empty project needs at
  least one member who meets each mandatory requirement.
- Mean skill fit is the average of the ``skill_fit_score`` stored on each
  assignment (the solver fills it with ``calculate_assignment_skill_fit``).
  Ranks and all feasibility checks are recomputed from the input data.
"""

from typing import Any

from app.domain import models

# Indicators are rounded so floating-point noise is never shown as a
# difference between two solutions.
_DECIMALS = 4


def _round(value: float) -> float:
    """Rounds a metric to the shared number of decimals."""
    return round(float(value), _DECIMALS)


def _pct(part: float, whole: float) -> float:
    """Returns part/whole as a percentage with one decimal (0 if whole is 0)."""
    if whole <= 0:
        return 0.0
    return round(part / float(whole) * 100.0, 1)


def _mean(values: list[float]) -> float:
    """Returns the arithmetic mean, or 0.0 for an empty list."""
    return sum(values) / len(values) if values else 0.0


def calculate_assignment_skill_fit(
    student: models.Student,
    project: models.Project,
) -> tuple[float, list[str]]:
    """Calculates skill fit score and unmet requirements for a student-project pair.

    In compliance with Section 7.2 of the TECH5 specification, skill fit
    evaluates how well the candidate student satisfies the required technical
    skills of the target project.

    Each requirement contributes min(1, level / required level), so a partial
    skill earns partial credit and exceeding a level earns no extra credit.
    The score is the average over all requirements (mandatory included).

    Args:
        student: The student under evaluation.
        project: The project under evaluation.

    Returns:
        A tuple of (skill_fit_score [0.0, 1.0], list_of_unmet_skill_ids).
        Unmet skills are listed once each, in requirement order.
    """
    if not project.requirements:
        return 1.0, []

    credits: list[float] = []
    unmet: list[str] = []
    for req in project.requirements:
        level = student.get_skill_level(req.skill_id)
        required = req.minimum_level
        if required <= 0:
            credits.append(1.0)
            continue
        credits.append(min(1.0, level / float(required)))
        if level < required and req.skill_id not in unmet:
            unmet.append(req.skill_id)

    return _mean(credits), unmet


def calculate_gini(values: list[float]) -> float:
    """Calculates the Gini coefficient of inequality for non-negative values.

    In compliance with Section 7.3 of the TECH5 specification, the Gini
    coefficient measures the inequality/fairness in student preference rank
    distribution (0.0 represents perfect equality, 1.0 represents extreme inequality).

    Uses the sorted form G = 2 * sum(i * x_(i)) / (n * sum(x)) - (n + 1) / n,
    which equals the mean absolute difference formula but runs in
    O(n log n).

    Args:
        values: Non-negative numerical series (e.g. assigned preference ranks).

    Returns:
        The Gini coefficient in [0.0, 1.0]. Returns 0.0 for an empty list or
        when all values are zero.

    Raises:
        ValueError: If any value is negative.
    """
    if any(v < 0 for v in values):
        raise ValueError("Gini coefficient requires non-negative values.")
    n = len(values)
    total = float(sum(values))
    if n == 0 or total == 0.0:
        return 0.0

    ordered = sorted(values)
    weighted = sum(i * v for i, v in enumerate(ordered, start=1))
    gini = 2.0 * weighted / (n * total) - (n + 1.0) / n
    return min(1.0, max(0.0, gini))


def _assignments_by_student(
    assignments: list[models.Assignment],
) -> dict[str, models.Assignment]:
    """Maps each student to their first assignment, keeping input order."""
    result: dict[str, models.Assignment] = {}
    for asg in assignments:
        result.setdefault(asg.student_id, asg)
    return result


def _feasibility(
    students: list[models.Student],
    projects: list[models.Project],
    assignments: list[models.Assignment],
    fixed_assignments: list[models.FixedAssignment],
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Re-checks every hard constraint independently of the solver.

    Returns:
        The feasibility indicator group and the members of each project
        (only students and projects that exist in the input).
    """
    violations: list[str] = []
    student_ids = {s.id for s in students}
    project_by_id = {p.id: p for p in projects}
    student_by_id = {s.id: s for s in students}

    # 1. Allocation completeness: every student has exactly one project.
    projects_of: dict[str, list[str]] = {s.id: [] for s in students}
    members: dict[str, list[str]] = {p.id: [] for p in projects}
    complete = True
    for asg in assignments:
        if asg.student_id not in student_ids:
            complete = False
            violations.append(
                f"Assignment for unknown student '{asg.student_id}'."
            )
            continue
        if asg.project_id not in project_by_id:
            violations.append(
                f"Student '{asg.student_id}' is assigned to unknown project "
                f"'{asg.project_id}'."
            )
            continue
        projects_of[asg.student_id].append(asg.project_id)
        members[asg.project_id].append(asg.student_id)

    for s in students:
        count = len(projects_of[s.id])
        if count == 0:
            complete = False
            violations.append(f"Student '{s.id}' has no project.")
        elif count > 1:
            complete = False
            violations.append(
                f"Student '{s.id}' is assigned to {count} projects: "
                f"{', '.join(projects_of[s.id])}."
            )
    # 2. Capacity compliance: l_p <= n_p <= u_p for every project.
    capacity_ok = True
    for p in projects:
        n_p = len(members[p.id])
        if n_p > p.max_capacity:
            capacity_ok = False
            violations.append(
                f"Project '{p.id}' has {n_p} students, above its maximum of "
                f"{p.max_capacity}."
            )
        if n_p < p.min_capacity:
            capacity_ok = False
            violations.append(
                f"Project '{p.id}' has {n_p} students, below its minimum of "
                f"{p.min_capacity}."
            )

    # 3. Fixed assignment adherence (identical duplicate locks count once).
    unique_locks = list(
        dict.fromkeys((fa.student_id, fa.project_id) for fa in fixed_assignments)
    )
    fixed_respected = 0
    for student_id, project_id in unique_locks:
        if project_id in projects_of.get(student_id, []):
            fixed_respected += 1
        else:
            violations.append(
                f"Fixed assignment broken: student '{student_id}' must be in "
                f"project '{project_id}'."
            )
    fixed_ok = fixed_respected == len(unique_locks)

    # 4. Mandatory requirements, team level: each non-empty project needs at
    #    least one member meeting each mandatory requirement.
    mandatory_applicable = 0
    mandatory_fulfilled = 0
    for p in projects:
        team = [student_by_id[sid] for sid in members[p.id]]
        if not team:
            continue
        for req in p.requirements:
            if not req.is_mandatory:
                continue
            mandatory_applicable += 1
            if any(
                st.get_skill_level(req.skill_id) >= req.minimum_level
                for st in team
            ):
                mandatory_fulfilled += 1
            else:
                violations.append(
                    f"Project '{p.id}' has no member with skill "
                    f"'{req.skill_id}' at level {req.minimum_level} or higher "
                    "(mandatory)."
                )
    mandatory_ok = mandatory_fulfilled == mandatory_applicable

    feasibility = {
        "is_feasible": not violations,
        "violations": violations,
        "checks": {
            "allocation_complete": complete,
            "capacity_respected": capacity_ok,
            "fixed_assignments_respected": fixed_ok,
            "mandatory_requirements_met": mandatory_ok,
        },
        "assigned_count": sum(1 for s in students if projects_of[s.id]),
        "total_students": len(students),
        "fixed_assignments_total": len(unique_locks),
        "fixed_assignments_respected": fixed_respected,
        "mandatory_requirements_applicable": mandatory_applicable,
        "mandatory_requirements_fulfilled": mandatory_fulfilled,
    }
    return feasibility, members


def compute_solution_indicators(
    students: list[models.Student],
    projects: list[models.Project],
    assignments: list[models.Assignment],
    fixed_assignments: list[models.FixedAssignment] | None = None,
) -> dict[str, Any]:
    """Computes comprehensive feasibility, efficiency, and fairness indicators.

    Evaluates a solution across the four dimensions defined in the specification:
    1. Feasibility: Exact student count, capacity bounds, fixed assignments.
    2. Efficiency: Mean skill-fit score, unmet soft requirements count.
    3. Fairness: Rank distribution, mean rank, worst rank, unranked count, Gini.
    4. Capacity: Total assigned, total capacity, overall utilization, per-project.

    Efficiency and fairness are measured over the students that have a valid
    assignment (their first one if a student appears more than once); any
    such problem is reported under feasibility.

    Args:
        students: Complete cohort of students.
        projects: Catalog of semester projects.
        assignments: List of student-to-project allocations.
        fixed_assignments: Optional list of locked pre-allocations.

    Returns:
        Dictionary containing structured indicators and diagnostic metrics:
        {
            "feasibility": {"is_feasible": bool, "violations": list[str], ...},
            "efficiency": {"mean_skill_fit": float, ...},
            "fairness": {"mean_rank": float, "worst_rank": int, "rank_gini": float, ...},
            "capacity": {"overall_utilization_pct": float, "projects": dict, ...}
        }
    """
    fixed_assignments = fixed_assignments or []
    feasibility, members = _feasibility(
        students, projects, assignments, fixed_assignments
    )

    project_by_id = {p.id: p for p in projects}
    student_by_id = {s.id: s for s in students}
    unranked_rank = len(projects) + 1

    # Valid assignments only: known student and known project.
    evaluated = [
        asg
        for asg in _assignments_by_student(assignments).values()
        if asg.student_id in student_by_id and asg.project_id in project_by_id
    ]

    # --- Efficiency -------------------------------------------------------
    fits = [asg.skill_fit_score for asg in evaluated]
    unmet_total = 0
    unmet_soft = 0
    unmet_mandatory = 0
    unmet_by_project: dict[str, int] = {p.id: 0 for p in projects}
    for asg in evaluated:
        mandatory_skills = {
            r.skill_id
            for r in project_by_id[asg.project_id].requirements
            if r.is_mandatory
        }
        for skill_id in asg.unmet_requirements:
            unmet_total += 1
            unmet_by_project[asg.project_id] += 1
            if skill_id in mandatory_skills:
                unmet_mandatory += 1
            else:
                unmet_soft += 1

    efficiency = {
        "mean_skill_fit": _round(_mean(fits)),
        "min_skill_fit": _round(min(fits)) if fits else 0.0,
        "total_skill_fit_sum": _round(sum(fits)),
        "unmet_requirements_count": unmet_total,
        "unmet_soft_requirements_count": unmet_soft,
        "unmet_mandatory_individual_count": unmet_mandatory,
        "unmet_requirements_by_project": {
            pid: count for pid, count in unmet_by_project.items() if count
        },
    }

    # --- Fairness (effective ranks, unranked = m + 1) ---------------------
    ranks: list[int] = []
    unranked_students: list[str] = []
    for asg in evaluated:
        stated = student_by_id[asg.student_id].get_preference_rank(
            asg.project_id
        )
        if stated is None:
            ranks.append(unranked_rank)
            unranked_students.append(asg.student_id)
        else:
            ranks.append(stated)

    ranked_only = [r for r in ranks if r != unranked_rank]
    highest_stated = max(ranked_only) if ranked_only else 0
    distribution = {
        f"rank_{k}": ranked_only.count(k) for k in range(1, highest_stated + 1)
    }
    distribution["unranked"] = len(unranked_students)

    mean_rank = _mean([float(r) for r in ranks])
    variance = _mean([(r - mean_rank) ** 2 for r in ranks])
    fairness = {
        "mean_rank": _round(mean_rank),
        "worst_rank": max(ranks) if ranks else 0,
        "rank_variance": _round(variance),
        "rank_gini": _round(calculate_gini([float(r) for r in ranks])),
        "rank_distribution": distribution,
        "unranked_count": len(unranked_students),
        "unranked_pct": _pct(len(unranked_students), len(ranks)),
        "unranked_students": unranked_students,
        "unranked_rank": unranked_rank,
    }

    # --- Capacity ---------------------------------------------------------
    total_assigned = sum(len(m) for m in members.values())
    total_capacity = sum(p.max_capacity for p in projects)
    per_project: dict[str, dict[str, Any]] = {}
    for p in projects:
        n_p = len(members[p.id])
        per_project[p.id] = {
            "assigned_count": n_p,
            "min_capacity": p.min_capacity,
            "max_capacity": p.max_capacity,
            "utilization_pct": _pct(n_p, p.max_capacity),
            "free_places": p.max_capacity - n_p,
            "margin_above_min": n_p - p.min_capacity,
            "is_full": n_p >= p.max_capacity,
            "is_at_minimum": n_p == p.min_capacity and n_p > 0,
            "is_empty": n_p == 0,
        }
    capacity = {
        "total_assigned": total_assigned,
        "total_capacity": total_capacity,
        "total_min_capacity": sum(p.min_capacity for p in projects),
        "free_places": total_capacity - total_assigned,
        "overall_utilization_pct": _pct(total_assigned, total_capacity),
        "full_projects": [pid for pid, d in per_project.items() if d["is_full"]],
        "empty_projects": [
            pid for pid, d in per_project.items() if d["is_empty"]
        ],
        "projects": per_project,
    }

    return {
        "feasibility": feasibility,
        "efficiency": efficiency,
        "fairness": fairness,
        "capacity": capacity,
    }


# --- Comparison ------------------------------------------------------------

# For each compared indicator: (group, key, True if higher is better).
_COMPARED_METRICS: list[tuple[str, str, bool]] = [
    ("efficiency", "mean_skill_fit", True),
    ("efficiency", "unmet_requirements_count", False),
    ("fairness", "mean_rank", False),
    ("fairness", "worst_rank", False),
    ("fairness", "unranked_count", False),
    ("fairness", "rank_gini", False),
]


def _unranked_rank_for(sol_a: models.Solution, sol_b: models.Solution) -> int:
    """Effective rank used for unranked assignments when comparing.

    Uses m + 1 stored by compute_solution_indicators. Older solutions without
    it fall back to one more than the highest stated rank seen.
    """
    for sol in (sol_a, sol_b):
        value = sol.indicators.get("fairness", {}).get("unranked_rank")
        if isinstance(value, int) and value > 0:
            return value
    stated = [
        a.preference_rank
        for sol in (sol_a, sol_b)
        for a in sol.assignments
        if a.preference_rank is not None
    ]
    return (max(stated) if stated else 0) + 1


def _metric_value(
    sol: models.Solution,
    group: str,
    key: str,
    unranked_rank: int,
) -> float | None:
    """Reads a stored indicator, deriving it from assignments if missing."""
    value = sol.indicators.get(group, {}).get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if not sol.assignments:
        return None
    ranks = [
        a.preference_rank if a.preference_rank is not None else unranked_rank
        for a in sol.assignments
    ]
    derived: dict[str, float] = {
        "mean_skill_fit": _round(
            _mean([a.skill_fit_score for a in sol.assignments])
        ),
        "unmet_requirements_count": sum(
            len(a.unmet_requirements) for a in sol.assignments
        ),
        "mean_rank": _round(_mean([float(r) for r in ranks])),
        "worst_rank": max(ranks),
        "unranked_count": sum(
            1 for a in sol.assignments if a.preference_rank is None
        ),
        "rank_gini": _round(calculate_gini([float(r) for r in ranks])),
    }
    return derived.get(key)


def _direction(delta: float, higher_is_better: bool) -> str:
    """Labels a B - A delta as better, worse, or tie for solution B."""
    if delta == 0:
        return "tie"
    improved = delta > 0 if higher_is_better else delta < 0
    return "better" if improved else "worse"


def _fmt(value: float) -> str:
    """Formats a number for summary sentences without trailing zeros."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _trade_off_summary(
    changed_count: int,
    total: int,
    improved: int,
    worsened: int,
    delta_metrics: dict[str, dict[str, Any]],
) -> list[str]:
    """Builds short plain-language statements from the computed deltas."""
    if changed_count == 0:
        return ["Both solutions assign every student to the same project."]

    lines = [f"B moves {changed_count} of {total} students to another project."]

    fit = delta_metrics.get("mean_skill_fit")
    rank = delta_metrics.get("mean_rank")
    if fit and fit["delta"] is not None:
        if fit["direction"] == "tie":
            lines.append(f"Mean skill fit is unchanged ({_fmt(fit['a'])}).")
        else:
            verb = "raises" if fit["delta"] > 0 else "lowers"
            lines.append(
                f"B {verb} mean skill fit by {_fmt(abs(fit['delta']))} "
                f"({_fmt(fit['a'])} to {_fmt(fit['b'])})."
            )
    if rank and rank["delta"] is not None:
        if rank["direction"] == "tie":
            lines.append(f"Mean preference rank is unchanged ({_fmt(rank['a'])}).")
        else:
            verb = "improves" if rank["delta"] < 0 else "worsens"
            lines.append(
                f"B {verb} mean preference rank by {_fmt(abs(rank['delta']))} "
                f"({_fmt(rank['a'])} to {_fmt(rank['b'])})."
            )

    lines.append(
        f"{worsened} student(s) get a worse rank in B and "
        f"{improved} get a better rank."
    )

    unranked = delta_metrics.get("unranked_count")
    if unranked and unranked["delta"]:
        more_or_fewer = "more" if unranked["delta"] > 0 else "fewer"
        lines.append(
            f"B places {_fmt(abs(unranked['delta']))} {more_or_fewer} "
            "student(s) outside their preference list."
        )
    worst = delta_metrics.get("worst_rank")
    if worst and worst["delta"]:
        lines.append(
            f"The worst assigned rank goes from {_fmt(worst['a'])} to "
            f"{_fmt(worst['b'])}."
        )
    gini = delta_metrics.get("rank_gini")
    if gini and gini["delta"]:
        trend = "more" if gini["delta"] > 0 else "less"
        lines.append(
            f"Ranks are {trend} unevenly spread in B (Gini {_fmt(gini['a'])} "
            f"to {_fmt(gini['b'])})."
        )

    if fit and rank and fit["delta"] is not None and rank["delta"] is not None:
        f_dir, r_dir = fit["direction"], rank["direction"]
        if f_dir == "better" and r_dir == "worse":
            lines.append(
                "Trade-off: B gains skill fit at the cost of student preferences."
            )
        elif f_dir == "worse" and r_dir == "better":
            lines.append(
                "Trade-off: B gains student preferences at the cost of skill fit."
            )
        elif "worse" not in (f_dir, r_dir) and "better" in (f_dir, r_dir):
            lines.append("B is at least as good as A on skill fit and mean rank.")
        elif "better" not in (f_dir, r_dir) and "worse" in (f_dir, r_dir):
            lines.append("A is at least as good as B on skill fit and mean rank.")
    return lines


def compare_two_solutions(
    solution_a: models.Solution,
    solution_b: models.Solution,
) -> dict[str, Any]:
    """Performs detailed trade-off comparison between two alternative solutions.

    In compliance with Section 7.4 of the specification, identifies:
    - Changed student allocations between solutions A and B.
    - Improved and worsened student preference ranks.
    - Deltas in mean skill-fit, mean rank, and Gini coefficient.
    - Human-readable trade-off summary statements.

    All deltas are B minus A, rounded to four decimals. Solution-level values
    come from the stored indicators (derived from the assignments if absent).
    Per-student ranks use the stored preference_rank, with unranked counted
    as m + 1.

    Args:
        solution_a: Baseline solution.
        solution_b: Alternative solution to compare against A.

    Returns:
        Dictionary documenting differences, changed assignments, and trade-offs:
        {
            "solution_a_id": str,
            "solution_b_id": str,
            "is_distinct": bool,
            "changed_students_count": int,
            "changed_assignments": list[dict[str, Any]],
            "delta_metrics": dict[str, Any],
            "trade_off_summary": list[str]
        }
    """
    unranked_rank = _unranked_rank_for(solution_a, solution_b)
    by_a = _assignments_by_student(solution_a.assignments)
    by_b = _assignments_by_student(solution_b.assignments)
    student_ids = list(dict.fromkeys([*by_a, *by_b]))

    def effective(asg: models.Assignment | None) -> int | None:
        if asg is None:
            return None
        if asg.preference_rank is None:
            return unranked_rank
        return asg.preference_rank

    changed: list[dict[str, Any]] = []
    improved = worsened = equal_rank = 0
    for sid in student_ids:
        a, b = by_a.get(sid), by_b.get(sid)
        p_a = a.project_id if a else None
        p_b = b.project_id if b else None
        if p_a == p_b:
            continue
        rank_a, rank_b = effective(a), effective(b)
        if rank_a is not None and rank_b is not None:
            rank_delta = rank_b - rank_a
        else:
            rank_delta = 0  # student missing from one solution
        if a is None or b is None:
            status = "only_in_a" if b is None else "only_in_b"
        elif rank_delta > 0:
            status = "worsened"
            worsened += 1
        elif rank_delta < 0:
            status = "improved"
            improved += 1
        else:
            status = "equal_rank"
            equal_rank += 1
        fit_a = a.skill_fit_score if a else None
        fit_b = b.skill_fit_score if b else None
        changed.append({
            "student_id": sid,
            "project_a_id": p_a,
            "project_b_id": p_b,
            "rank_a": rank_a,
            "rank_b": rank_b,
            "unranked_a": bool(a) and a.preference_rank is None,
            "unranked_b": bool(b) and b.preference_rank is None,
            "rank_delta": rank_delta,
            "skill_fit_a": _round(fit_a) if fit_a is not None else None,
            "skill_fit_b": _round(fit_b) if fit_b is not None else None,
            "skill_fit_delta": (
                _round(fit_b - fit_a)
                if fit_a is not None and fit_b is not None
                else None
            ),
            "status": status,
        })

    # Largest worsening first, so the students who pay are seen at once.
    changed.sort(key=lambda c: (-c["rank_delta"], c["student_id"]))

    delta_metrics: dict[str, dict[str, Any]] = {}
    for group, key, higher_is_better in _COMPARED_METRICS:
        val_a = _metric_value(solution_a, group, key, unranked_rank)
        val_b = _metric_value(solution_b, group, key, unranked_rank)
        delta = (
            _round(val_b - val_a)
            if val_a is not None and val_b is not None
            else None
        )
        delta_metrics[key] = {
            "a": val_a,
            "b": val_b,
            "delta": delta,
            "direction": (
                _direction(delta, higher_is_better)
                if delta is not None
                else "unknown"
            ),
            "higher_is_better": higher_is_better,
        }
    delta_metrics["rank_distribution"] = {
        "a": solution_a.indicators.get("fairness", {}).get(
            "rank_distribution", {}
        ),
        "b": solution_b.indicators.get("fairness", {}).get(
            "rank_distribution", {}
        ),
    }

    def top_level(key: str) -> float:
        delta = delta_metrics[key]["delta"]
        return delta if delta is not None else 0.0

    return {
        "solution_a_id": solution_a.id,
        "solution_a_alt": solution_a.alternative_number,
        "solution_b_id": solution_b.id,
        "solution_b_alt": solution_b.alternative_number,
        "is_distinct": bool(changed),
        "changed_students_count": len(changed),
        "total_students": len(student_ids),
        "changed_assignments": changed,
        "rank_improved_count": improved,
        "rank_worsened_count": worsened,
        "equal_rank_moved_count": equal_rank,
        "delta_mean_skill_fit": top_level("mean_skill_fit"),
        "delta_mean_rank": top_level("mean_rank"),
        "delta_unranked_count": int(top_level("unranked_count")),
        "delta_metrics": delta_metrics,
        "trade_off_summary": _trade_off_summary(
            len(changed), len(student_ids), improved, worsened, delta_metrics
        ),
    }
