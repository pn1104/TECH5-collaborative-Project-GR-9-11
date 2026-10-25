"""Web routes and controller logic for Component A (Visualization).

This module provides interactive CRUD interfaces, scenario seeders, optimization
triggering, multi-solution visual comparisons, and recommendations.
"""

import collections
import csv
import io
import re
import sqlite3
import flask 
from typing import Any


from app.contract import contract
from app.contract import mocks
from app.domain import models
from app.engine import recommendations
from app.engine import solvers
from app.persistence import repositories
from app.samples import demo_data
from app.visualization import auth

web_bp = flask.Blueprint("visualization_web", __name__)


@web_bp.app_context_processor
def inject_template_globals() -> dict[str, Any]:
    """Injects authorization helpers and active role into templates."""
    return {
        "current_role": auth.get_current_role(),
        "all_roles": auth.UserRole.ALL_ROLES,
        "can_edit": auth.can_edit_cohort_data(),
        "can_optimize": auth.can_trigger_optimization(),
    }


@web_bp.post("/set-role")
def set_role() -> flask.Response:
    """Updates the active user role prototype."""
    role = flask.request.form.get("role", auth.UserRole.ADMIN)
    auth.set_current_role(role)
    role_name = auth.UserRole.ALL_ROLES.get(role, role)
    flask.flash(f"Switched role to {role_name}.", "info")
    target = flask.request.referrer or flask.url_for(
        "visualization_web.dashboard"
    )
    return flask.redirect(target)


@web_bp.get("/")
def dashboard() -> str:
    """Renders main dashboard overview with cohort metrics and runs."""
    stud_repo = repositories.StudentRepository()
    proj_repo = repositories.ProjectRepository()
    fixed_repo = repositories.FixedAssignmentRepository()
    run_repo = repositories.RunRepository()

    students = stud_repo.list_all()
    projects = proj_repo.list_all()
    fixed_assignments = fixed_repo.list_all()
    runs = run_repo.list_runs(limit=10)

    total_capacity = sum(p.max_capacity for p in projects)
    latest_run = runs[0] if runs else None

    return flask.render_template(
        "dashboard.html",
        student_count=len(students),
        project_count=len(projects),
        total_capacity=total_capacity,
        fixed_count=len(fixed_assignments),
        recent_runs=runs,
        latest_run=latest_run,
    )


# -----------------------------------------------------------------------------
# Students CRUD
# -----------------------------------------------------------------------------


@web_bp.get("/students")
def list_students() -> str:
    """Lists all students with their proficiencies and ranked preferences."""
    students = repositories.StudentRepository().list_all()
    projects = repositories.ProjectRepository().list_all()
    skills = repositories.SkillRepository().list_all()
    return flask.render_template(
        "students.html",
        students=students,
        projects=projects,
        skills=skills,
    )


@web_bp.get("/students/new")
def new_student_form() -> str:
    """Displays form to create a new student."""
    projects = repositories.ProjectRepository().list_all()
    skills = repositories.SkillRepository().list_all()
    return flask.render_template(
        "student_form.html",
        student=None,
        projects=projects,
        skills=skills,
    )


def _check_valid_student_data(
    student_id: str,
    student_name: str,
    available_students: dict[str, str],
) -> bool:
    """Checks if the student data is valid
    Args:
        student_id: Target student identifier.
        student_name: Target student name.
        available_students: Map of existing students id and name.
    Returns:
        A list of invalid students.
    """
    

    valid = 1

    if student_id in available_students:
        valid = 0
    elif student_name in available_students.values():
        valid = 0


    return valid


def _parse_and_validate_preferences(
    student_id: str,
    pref_raw: str,
    available_projects: dict[str, models.Project],
) -> tuple[list[models.Preference], list[str]]:
    """Parses and validates comma-separated project preferences.

    Args:
        student_id: Target student identifier.
        pref_raw: Comma-separated project IDs string from user input.
        available_projects: Map of valid project ID to Project model.

    Returns:
        A tuple of (valid_preferences_list, invalid_project_ids_list).
    """
    raw_tokens = [p.strip() for p in pref_raw.split(",") if p.strip()]
    case_map = {p_id.upper(): p_id for p_id in available_projects}

    valid_prefs: list[models.Preference] = []
    invalid_ids: list[str] = []
    seen: set[str] = set()

    for token in raw_tokens:
        resolved_id = None
        if token in available_projects:
            resolved_id = token
        elif token.upper() in case_map:
            resolved_id = case_map[token.upper()]
        else:
            invalid_ids.append(token)
            continue

        if resolved_id not in seen:
            seen.add(resolved_id)
            valid_prefs.append(
                models.Preference(
                    student_id=student_id,
                    project_id=resolved_id,
                    rank=len(valid_prefs) + 1,
                )
            )

    return valid_prefs, invalid_ids


@web_bp.post("/students/new")
def create_student() -> flask.Response:
    """Processes creation of a new student."""
    if not auth.can_edit_cohort_data():
        flask.flash("Permission denied for current role.", "danger")
        return flask.redirect(flask.url_for("visualization_web.list_students"))

    s_id = flask.request.form.get("id", "").strip()
    name = flask.request.form.get("display_name", "").strip() or s_id

    available_students = {
        s.id: s.display_name for s in repositories.StudentRepository().list_all()
    }

    if not _check_valid_student_data(s_id,name, available_students):
        flask.flash(f"Student ID: {s_id}, or Name: {name} already exists.", "danger")
        return flask.redirect(
            flask.url_for("visualization_web.new_student_form")
        )

    if not s_id:
        flask.flash("Student ID cannot be empty.", "warning")
        return flask.redirect(
            flask.url_for("visualization_web.new_student_form")
        )

    # Parse skills
    skills_dict: dict[str, int] = {}
    valid_skills = {s.id for s in repositories.SkillRepository().list_all()}
    for key, val in flask.request.form.items():
        if key.startswith("skill_") and val:
            skill_id = key.replace("skill_", "")
            if skill_id in valid_skills:
                try:
                    lvl = int(val)
                    if lvl > 0:
                        skills_dict[skill_id] = lvl
                except ValueError:
                    pass

    # Parse and validate preferences against catalog
    available_projects = {
        p.id: p for p in repositories.ProjectRepository().list_all()
    }
    pref_raw = flask.request.form.get("preferences_text", "")
    preferences, invalid_proj_ids = _parse_and_validate_preferences(
        s_id, pref_raw, available_projects
    )

    if invalid_proj_ids:
        valid_list = (
            ", ".join(sorted(available_projects.keys())) or "None available"
        )
        flask.flash(
            f"Invalid project ID(s) in preferences: "
            f"{', '.join(invalid_proj_ids)}. "
            f"Available projects: {valid_list}.",
            "danger",
        )
        return flask.redirect(
            flask.url_for("visualization_web.new_student_form")
        )

    student = models.Student(
        id=s_id,
        display_name=name,
        skills=skills_dict,
        preferences=preferences,
    )
    try:
        repositories.StudentRepository().save(student)
    except sqlite3.IntegrityError as exc:
        flask.flash(
            f"Database constraint error while saving student: {exc}",
            "danger",
        )
        return flask.redirect(
            flask.url_for("visualization_web.new_student_form")
        )

    flask.flash(f"Student '{name}' ({s_id}) created successfully.", "success")
    return flask.redirect(flask.url_for("visualization_web.list_students"))


@web_bp.get("/students/<student_id>/edit")
def edit_student_form(student_id: str) -> Any:
    """Displays form to edit an existing student."""
    student = repositories.StudentRepository().get_by_id(student_id)
    if not student:
        flask.flash(f"Student '{student_id}' not found.", "danger")
        return flask.redirect(flask.url_for("visualization_web.list_students"))

    projects = repositories.ProjectRepository().list_all()
    skills = repositories.SkillRepository().list_all()
    return flask.render_template(
        "student_form.html",
        student=student,
        projects=projects,
        skills=skills,
    )


@web_bp.post("/students/<student_id>/edit")
def update_student(student_id: str) -> flask.Response:
    """Updates an existing student entity."""
    if not auth.can_edit_cohort_data():
        flask.flash("Permission denied for current role.", "danger")
        return flask.redirect(flask.url_for("visualization_web.list_students"))

    name = (
        flask.request.form.get("display_name", "").strip() or student_id
    )

    valid_skills = {s.id for s in repositories.SkillRepository().list_all()}
    skills_dict: dict[str, int] = {}
    for key, val in flask.request.form.items():
        if key.startswith("skill_") and val:
            skill_id = key.replace("skill_", "")
            if skill_id in valid_skills:
                try:
                    lvl = int(val)
                    if lvl > 0:
                        skills_dict[skill_id] = lvl
                except ValueError:
                    pass

    # Parse and validate preferences against catalog
    available_projects = {
        p.id: p for p in repositories.ProjectRepository().list_all()
    }
    pref_raw = flask.request.form.get("preferences_text", "")
    preferences, invalid_proj_ids = _parse_and_validate_preferences(
        student_id, pref_raw, available_projects
    )

    if invalid_proj_ids:
        valid_list = (
            ", ".join(sorted(available_projects.keys())) or "None available"
        )
        flask.flash(
            f"Invalid project ID(s) in preferences: "
            f"{', '.join(invalid_proj_ids)}. "
            f"Available projects: {valid_list}.",
            "danger",
        )
        return flask.redirect(
            flask.url_for(
                "visualization_web.edit_student_form", student_id=student_id
            )
        )

    student = models.Student(
        id=student_id,
        display_name=name,
        skills=skills_dict,
        preferences=preferences,
    )
    try:
        repositories.StudentRepository().save(student)
    except sqlite3.IntegrityError as exc:
        flask.flash(
            f"Database constraint error while updating student: {exc}",
            "danger",
        )
        return flask.redirect(
            flask.url_for(
                "visualization_web.edit_student_form", student_id=student_id
            )
        )

    flask.flash(f"Student '{student_id}' updated.", "success")
    return flask.redirect(flask.url_for("visualization_web.list_students"))


@web_bp.post("/students/<student_id>/delete")
def delete_student(student_id: str) -> flask.Response:
    """Deletes a student."""
    if not auth.can_edit_cohort_data():
        flask.flash("Permission denied.", "danger")
        return flask.redirect(flask.url_for("visualization_web.list_students"))

    repositories.StudentRepository().delete(student_id)
    flask.flash(f"Student '{student_id}' removed.", "info")
    return flask.redirect(flask.url_for("visualization_web.list_students"))


# -----------------------------------------------------------------------------
# Projects CRUD
# -----------------------------------------------------------------------------


@web_bp.get("/projects")
def list_projects() -> str:
    """Displays project catalog and capacity definitions."""
    projects = repositories.ProjectRepository().list_all()
    skills = repositories.SkillRepository().list_all()
    return flask.render_template(
        "projects.html", projects=projects, skills=skills
    )


@web_bp.get("/projects/new")
def new_project_form() -> str:
    """Displays form to create a semester project."""
    skills = repositories.SkillRepository().list_all()
    return flask.render_template(
        "project_form.html", project=None, skills=skills
    )


def _parse_project_requirements( project_id: str,) -> list[models.ProjectRequirement]:
    """Reads the skill requirements matrix from the submitted form.

    Args:
        project_id: Identifier of the project the requirements belong to.

    Returns:
        A list of ProjectRequirement objects (only skills with level 1-5).
    """
    requirements: list[models.ProjectRequirement] = []
    for skill in repositories.SkillRepository().list_all():
        level_raw = flask.request.form.get(f"req_level_{skill.id}", "0")
        try:
            level = int(level_raw)
        except ValueError:
            level = 0

        if 1 <= level <= 5:
            is_mandatory = flask.request.form.get(f"req_mand_{skill.id}") == "1"
            requirements.append(
                models.ProjectRequirement(
                    project_id=project_id,
                    skill_id=skill.id,
                    minimum_level=level,
                    is_mandatory=is_mandatory,
                )
            )
    return requirements


def _parse_capacities() -> tuple[int, int] | None:
    """Reads and checks min/max capacity from the submitted form.

    Returns:
        A tuple (min_capacity, max_capacity), or None if the input is invalid.
    """
    try:
        min_cap = int(flask.request.form.get("min_capacity", 0))
        max_cap = int(flask.request.form.get("max_capacity", 1))
    except ValueError:
        return None

    if min_cap < 0 or max_cap < 1 or min_cap > max_cap:
        return None
    return min_cap, max_cap


@web_bp.post("/projects/new")
def create_project() -> flask.Response:
    """Processes creation of a project."""
    if not auth.can_edit_cohort_data():
        flask.flash("Permission denied for current role.", "danger")
        return flask.redirect(flask.url_for("visualization_web.list_projects"))

    # 1. Read the basic fields from the form
    p_id = flask.request.form.get("id", "").strip()
    title = flask.request.form.get("title", "").strip()
    description = flask.request.form.get("description", "").strip()

    if not p_id or not title:
        flask.flash("Project ID and title cannot be empty.", "warning")
        return flask.redirect(flask.url_for("visualization_web.new_project_form"))

    # 2. The ID must be new (save() would otherwise overwrite a project)
    if repositories.ProjectRepository().get_by_id(p_id):
        flask.flash(f"Project ID '{p_id}' already exists.", "danger")
        return flask.redirect(flask.url_for("visualization_web.new_project_form"))

    # 3. Read and check the capacities
    capacities = _parse_capacities()
    if capacities is None:
        flask.flash(
            "Invalid capacity: need whole numbers with "
            "0 <= minimum <= maximum and maximum >= 1.",
            "danger",
        )
        return flask.redirect(flask.url_for("visualization_web.new_project_form"))
    min_cap, max_cap = capacities

    # 4. Build the Project object and save it to the database
    project = models.Project(
        id=p_id,
        title=title,
        description=description,
        min_capacity=min_cap,
        max_capacity=max_cap,
        requirements=_parse_project_requirements(p_id),
    )
    try:
        repositories.ProjectRepository().save(project)
    except sqlite3.IntegrityError as exc:
        flask.flash(f"Database error while saving project: {exc}", "danger")
        return flask.redirect(flask.url_for("visualization_web.new_project_form"))

    flask.flash(f"Project '{title}' ({p_id}) created successfully.", "success")
    return flask.redirect(flask.url_for("visualization_web.list_projects"))


@web_bp.get("/projects/<project_id>/edit")
def edit_project_form(project_id: str) -> Any:
    """Displays form to edit a project."""
    project = repositories.ProjectRepository().get_by_id(project_id)
    if not project:
        flask.flash(f"Project '{project_id}' not found.", "danger")
        return flask.redirect(flask.url_for("visualization_web.list_projects"))

    skills = repositories.SkillRepository().list_all()
    return flask.render_template(
        "project_form.html", project=project, skills=skills
    )


@web_bp.post("/projects/<project_id>/edit")
def update_project(project_id: str) -> flask.Response:
    """Updates an existing project entity."""
    if not auth.can_edit_cohort_data():
        flask.flash("Permission denied for current role.", "danger")
        return flask.redirect(flask.url_for("visualization_web.list_projects"))

    # 1. The project must already exist
    if not repositories.ProjectRepository().get_by_id(project_id):
        flask.flash(f"Project '{project_id}' not found.", "danger")
        return flask.redirect(flask.url_for("visualization_web.list_projects"))

    title = flask.request.form.get("title", "").strip()
    description = flask.request.form.get("description", "").strip()
    if not title:
        flask.flash("Project title cannot be empty.", "warning")
        return flask.redirect(
            flask.url_for(
                "visualization_web.edit_project_form", project_id=project_id
            )
        )

    # 2. Read and check the capacities
    capacities = _parse_capacities()
    if capacities is None:
        flask.flash(
            "Invalid capacity: need whole numbers with "
            "0 <= minimum <= maximum and maximum >= 1.",
            "danger",
        )
        return flask.redirect(
            flask.url_for(
                "visualization_web.edit_project_form", project_id=project_id
            )
        )
    min_cap, max_cap = capacities

    # 3. Build the updated Project and save it (save() overwrites)
    project = models.Project(
        id=project_id,
        title=title,
        description=description,
        min_capacity=min_cap,
        max_capacity=max_cap,
        requirements=_parse_project_requirements(project_id),
    )
    try:
        repositories.ProjectRepository().save(project)
    except sqlite3.IntegrityError as exc:
        flask.flash(f"Database error while updating project: {exc}", "danger")
        return flask.redirect(
            flask.url_for(
                "visualization_web.edit_project_form", project_id=project_id
            )
        )

    flask.flash(f"Project '{project_id}' updated.", "success")
    return flask.redirect(flask.url_for("visualization_web.list_projects"))


@web_bp.post("/projects/<project_id>/delete")
def delete_project(project_id: str) -> flask.Response:
    """Deletes a project."""
    if not auth.can_edit_cohort_data():
        flask.flash("Permission denied.", "danger")
        return flask.redirect(flask.url_for("visualization_web.list_projects"))

    try:
        deleted = repositories.ProjectRepository().delete(project_id)
    except sqlite3.IntegrityError as exc:
        flask.flash(
            f"Cannot delete project '{project_id}': it is still used "
            f"elsewhere ({exc}).",
            "danger",
        )
        return flask.redirect(flask.url_for("visualization_web.list_projects"))

    if deleted:
        flask.flash(
            f"Project '{project_id}' removed, together with its skill "
            f"requirements, student preferences and fixed assignments for it.",
            "info",
        )
    else:
        flask.flash(f"Project '{project_id}' not found.", "warning")
    return flask.redirect(flask.url_for("visualization_web.list_projects"))

# -----------------------------------------------------------------------------
# Skills CRUD & Preferences Editor
# -----------------------------------------------------------------------------


@web_bp.get("/skills")
def list_skills() -> str:
    """Lists skill catalog records."""
    skills = repositories.SkillRepository().list_all()
    return flask.render_template("skills.html", skills=skills)


@web_bp.post("/skills/new")
def create_skill() -> flask.Response:
    """Creates a new skill record."""
    if not auth.can_edit_cohort_data():
        flask.flash("Permission denied for current role.", "danger")
        return flask.redirect(flask.url_for("visualization_web.list_skills"))
    
    raw_skill_id = flask.request.form.get("id", "").strip()
    skill_id = raw_skill_id.lower()
    # Validate allowed characters for skill identifiers
    if not re.match(r"^[a-z0-9_]+$", skill_id):
        flask.flash(
            "Skill ID may only contain lowercase letters, digits, and underscores.",
            "warning",
        )
        return flask.redirect(flask.url_for("visualization_web.list_skills"))
    skill_name = flask.request.form.get("name", "").strip() or skill_id
    description = flask.request.form.get("description", "").strip()
    
    if not skill_id:
        flask.flash("Skill ID is required.", "warning")
        return flask.redirect(flask.url_for("visualization_web.list_skills"))
    
    repo = repositories.SkillRepository()
    existing = repo.get_by_id(skill_id)
    skill = models.Skill(id=skill_id, name=skill_name, description=description)
    try:
        repo.save(skill)
        if existing:
            flask.flash(f"Skill '{skill_name}' ({skill_id}) updated.", "success")
        else:
            flask.flash(f"Skill '{skill_name}' ({skill_id}) created successfully.", "success")
    except sqlite3.IntegrityError as exc:
        flask.flash(f"Database constraint error while saving skill: {exc}", "danger")
    
    return flask.redirect(flask.url_for("visualization_web.list_skills"))

@web_bp.post("/skills/<skill_id>/delete")
def delete_skill(skill_id: str) -> flask.Response:
    """Deletes a skill record."""
    if not auth.can_edit_cohort_data():
        flask.flash("Permission denied for current role.", "danger")
        return flask.redirect(flask.url_for("visualization_web.list_skills"))

    try:
        repositories.SkillRepository().delete(skill_id)
        flask.flash(f"Skill '{skill_id}' removed.", "info")
    except Exception as exc:
        flask.flash(f"Error deleting skill '{skill_id}': {exc}", "danger")

    return flask.redirect(flask.url_for("visualization_web.list_skills"))

@web_bp.get("/preferences")
def preferences_overview() -> str:
    """Displays cross-table preference matrix."""
    students = repositories.StudentRepository().list_all()
    projects = repositories.ProjectRepository().list_all()
    return flask.render_template(
        "preferences.html", students=students, projects=projects
    )


# -----------------------------------------------------------------------------
# Fixed Assignments & Reruns
# -----------------------------------------------------------------------------


@web_bp.get("/fixed-assignments")
def list_fixed_assignments() -> str:
    """Lists administrative pre-allocated constraints."""
    fixed = repositories.FixedAssignmentRepository().list_all()
    students = repositories.StudentRepository().list_all()
    projects = repositories.ProjectRepository().list_all()
    return flask.render_template(
        "fixed_assignments.html",
        fixed_assignments=fixed,
        students=students,
        projects=projects,
    )


@web_bp.post("/fixed-assignments/new")
def create_fixed_assignment() -> flask.Response:
    """Locks a student to a designated project."""
    target = flask.url_for("visualization_web.list_fixed_assignments")
    if not auth.can_edit_cohort_data():
        flask.flash("Permission denied.", "danger")
        return flask.redirect(target)

    s_id = flask.request.form.get("student_id", "").strip()
    p_id = flask.request.form.get("project_id", "").strip()
    reason = flask.request.form.get("reason", "").strip()
    status = flask.request.form.get("status", "APPROVED").strip()

    if not s_id or not p_id:
        flask.flash("Student and Project must be selected.", "warning")
        return flask.redirect(target)

    repositories.FixedAssignmentRepository().save(
        models.FixedAssignment(
            student_id=s_id, project_id=p_id, status=status, reason=reason
        )
    )
    flask.flash(
        f"Fixed assignment created: Student {s_id} locked to Project {p_id}. "
        "A new run is required to recalculate allocations.",
        "success",
    )
    return flask.redirect(target)


@web_bp.post("/fixed-assignments/<student_id>/delete")
def delete_fixed_assignment(student_id: str) -> flask.Response:
    """Removes a locked allocation."""
    target = flask.url_for("visualization_web.list_fixed_assignments")
    if not auth.can_edit_cohort_data():
        flask.flash("Permission denied.", "danger")
        return flask.redirect(target)

    repositories.FixedAssignmentRepository().delete(student_id)
    flask.flash(f"Fixed assignment for student '{student_id}' removed.", "info")
    return flask.redirect(target)


# -----------------------------------------------------------------------------
# Scenarios & Data Seeding
# -----------------------------------------------------------------------------


@web_bp.get("/scenarios")
def scenarios_page() -> str:
    """Displays benchmark scenarios loader."""
    return flask.render_template("scenarios.html")


@web_bp.post("/load-scenario/<scenario_name>")
def load_scenario(scenario_name: str) -> flask.Response:
    """Populates database with a designated reproducible benchmark cohort."""
    repo_run = repositories.RunRepository()
    repo_run.clear_all_cohort_data()

    if scenario_name == "standard":
        data = demo_data.get_standard_scenario()
    elif scenario_name == "fixed":
        data = demo_data.get_fixed_assignment_scenario()
    elif scenario_name == "infeasible":
        data = demo_data.get_infeasible_scenario()
    elif scenario_name == "conflicting":
        data = demo_data.get_conflicting_fixed_scenario()
    else:
        flask.flash(f"Unknown scenario: '{scenario_name}'.", "warning")
        return flask.redirect(flask.url_for("visualization_web.scenarios_page"))

    skill_repo = repositories.SkillRepository()
    for s in data["skills"]:
        skill_repo.save(s)

    proj_repo = repositories.ProjectRepository()
    for p in data["projects"]:
        proj_repo.save(p)

    stud_repo = repositories.StudentRepository()
    for st in data["students"]:
        stud_repo.save(st)

    fixed_repo = repositories.FixedAssignmentRepository()
    for fa in data.get("fixed_assignments", []):
        fixed_repo.save(fa)

    flask.flash(
        f"Benchmark '{data['scenario_name']}' loaded successfully! "
        f"{data['description']}",
        "success",
    )
    return flask.redirect(flask.url_for("visualization_web.dashboard"))


@web_bp.post("/clear-data")
def clear_data() -> flask.Response:
    """Clears all cohort and constraint data."""
    repositories.RunRepository().clear_all_cohort_data()
    flask.flash("All cohort data cleared.", "info")
    return flask.redirect(flask.url_for("visualization_web.dashboard"))


# -----------------------------------------------------------------------------
# Runs & Solutions
# -----------------------------------------------------------------------------


@web_bp.post("/runs/trigger")
def trigger_run() -> flask.Response:
    """Submits current cohort data to Service A to generate allocations."""
    if not auth.can_trigger_optimization():
        flask.flash("Permission denied for current role.", "danger")
        return flask.redirect(flask.url_for("visualization_web.dashboard"))

    max_alts = int(flask.request.form.get("max_alternatives", 3))
    strat = flask.request.form.get("primary_strategy", "PREFERENCE")

    students = repositories.StudentRepository().list_all()
    projects = repositories.ProjectRepository().list_all()
    skills = repositories.SkillRepository().list_all()
    fixed = repositories.FixedAssignmentRepository().list_all()

    engine: contract.AssignmentEngineContract = solvers.AssignmentEngine()
    req = contract.RunRequest(
        students=students,
        projects=projects,
        skills=skills,
        fixed_assignments=fixed,
        strategy_key=strat,
        max_alternatives=max_alts,
    )
    val_outcome = engine.validate_inputs(req)
    for warning_msg in val_outcome.warnings:
        flask.flash(f"Warning: {warning_msg}", "warning")
    try:
        run = engine.execute_run(req)
    except NotImplementedError:
        flask.flash(
            "Notice: AssignmentEngine.execute_run() is not yet implemented by "
            "Team B. Running with MockAssignmentEngine for demonstration.",
            "info",
        )
        mock_engine = mocks.MockAssignmentEngine()
        run = mock_engine.execute_run(req)

    if run.status == "COMPLETED":
        flask.flash(
            f"Optimization run completed! Found {len(run.solutions)} "
            "distinct alternative solutions.",
            "success",
        )
    elif run.status == "INFEASIBLE":
        flask.flash(
            "Solver could not find a feasible solution under the specified "
            "hard constraints. Inspect diagnostics below.",
            "warning",
        )
    else:
        flask.flash(f"Run ended with status: {run.status}.", "danger")

    return flask.redirect(
        flask.url_for("visualization_web.view_run", run_id=run.id)
    )


@web_bp.get("/runs/<run_id>")
def view_run(run_id: str) -> Any:
    """Displays results, alternative solutions, and diagnostics of a run."""
    run = repositories.RunRepository().get_run(run_id)
    if not run:
        flask.flash(f"Run '{run_id}' not found.", "danger")
        return flask.redirect(flask.url_for("visualization_web.dashboard"))

    recs = recommendations.generate_recommendations(run.solutions)

    return flask.render_template(
        "run_detail.html",
        run=run,
        recommendations=recs,
    )


@web_bp.get("/solutions/<solution_id>")
def view_solution(solution_id: str) -> Any:
    """Displays complete student assignment details for a solution."""
    repo = repositories.RunRepository()
    solution = repo.get_solution(solution_id)
    if not solution:
        flask.flash(f"Solution '{solution_id}' not found.", "danger")
        return flask.redirect(flask.url_for("visualization_web.dashboard"))

    run = repo.get_run(solution.run_id)
    students = {s.id: s for s in repositories.StudentRepository().list_all()}
    projects = {p.id: p for p in repositories.ProjectRepository().list_all()}

    return flask.render_template(
        "solution_detail.html",
        solution=solution,
        run=run,
        students=students,
        projects=projects,
    )


@web_bp.post("/solutions/<solution_id>/lock-and-rerun")
def lock_and_rerun(solution_id: str) -> flask.Response:
    """Locks a student assignment from a solution and triggers a new run."""
    student_id = flask.request.form.get("student_id")
    project_id = flask.request.form.get("project_id")

    if not student_id or not project_id:
        flask.flash("Student and Project required.", "warning")
        return flask.redirect(
            flask.url_for(
                "visualization_web.view_solution", solution_id=solution_id
            )
        )

    # Persist as fixed assignment
    fixed_repo = repositories.FixedAssignmentRepository()
    fixed_repo.save(
        models.FixedAssignment(
            student_id=student_id,
            project_id=project_id,
            status="APPROVED",
            reason=f"Locked interactively from Solution {solution_id[:8]}.",
        )
    )

    # Immediately trigger rerun via Component B (Assignment Engine)
    students = repositories.StudentRepository().list_all()
    projects = repositories.ProjectRepository().list_all()
    skills = repositories.SkillRepository().list_all()
    fixed = fixed_repo.list_all()

    engine: contract.AssignmentEngineContract = solvers.AssignmentEngine()
    req = contract.RunRequest(
        students=students,
        projects=projects,
        skills=skills,
        fixed_assignments=fixed,
    )
    try:
        new_run = engine.execute_run(req)
    except NotImplementedError:
        new_run = mocks.MockAssignmentEngine().execute_run(req)

    flask.flash(
        f"Student {student_id} locked to Project {project_id}. "
        "New run generated!",
        "success",
    )
    return flask.redirect(
        flask.url_for("visualization_web.view_run", run_id=new_run.id)
    )

@web_bp.post("/clear-solutions")
def clear_solutions() -> flask.Response:
    """Clears all solutions in the current run."""
    repositories.RunRepository().clear_all_current_solutions()
    flask.flash("All solutions cleared.", "info")
    return flask.redirect(flask.url_for("visualization_web.dashboard"))

# -----------------------------------------------------------------------------
# Comparison & Recommendations
# -----------------------------------------------------------------------------
def generate_recommendations(solutions):
    """Evaluates all solutions and generates recommendations separating objective evidence from policy advice.
    
    Rule: Prioritize minimizing total student rank regret (Efficiency first),
    using solution balance and fairness as a tie-breaker.
    
    Args:
        solutions: List of Solution objects to evaluate.
        
    Returns:
        list[dict]: List of recommendations ready for the template.
    """
    if not solutions:
        return []

    sorted_solutions = sorted(
        solutions,
        key=lambda sol: (sol.indicators.get("efficiency", {}).get("mean_rank", 999),
                            sol.indicators.get("fairness", {}).get("rank_gini", 0)))
    
    recommendations = []

    for index, sol in enumerate(sorted_solutions[:3], start=1):
        if index == 1:
            priority = "Primary Recommendation"
        elif index == 2:
            priority = "Strong ALternative (High Balance)"
        else:
            priority = "Conservative Baseline (Low Risk)"
        
        evidence = [
            f"Average Preference Rank: {sol.indicators.get('fairness', {}).get('mean_rank', 'N/A')}",
            f"Worst Preference Rank: {sol.indicators.get('fairness', {}).get('worst_rank', 'N/A')}",
            f"Rank Gini (Inequality): {sol.indicators.get('fairness', {}).get('rank_gini', 'N/A')}"
        ]

        criteria = [
            "Student Preference Maximization (Rank Regret minimization)",
            "Workload & Capacity Equivalence",
            "Fixed Lock Constraint Preservation"
        ]

        if index == 1:
            advice = (
                f"Solution Alternative #{sol.id} represents the mathematically optimal choice. "
                f"It achieves the best balance of satisfying student preference ranks while keeping inequality low."
            )
        else:
            advice = (
                f"Solution Alternative #{sol.id} serves as a viable alternative, offering trade-offs "
                f"in distribution equity if departmental priorities favor broader spread over strict rank minimization."
            )
        recommendations.append({
            "recommended_alternative_number": sol.id,
            "recommended_solution_id": sol.id,
            "priority_focus": priority,
            "evidence": evidence,
            "criteria_used": criteria,
            "advice": advice
        })

    return recommendations


def _add_display_names(comparison: models.RunComparison) -> None:
    """Replaces raw IDs in the comparison with readable names and titles.
 
    Args:
        comparison: The RunComparison whose changed assignments are updated.
    """
    student_names = {
        s.id: s.display_name
        for s in repositories.StudentRepository().list_all()
    }
    project_titles = {
        p.id: p.title for p in repositories.ProjectRepository().list_all()
    }
 
    for change in comparison.changed_assignments:
        s_id = change.get("student_id")
        p_a = change.get("project_a_id")
        p_b = change.get("project_b_id")
        change["student_name"] = student_names.get(s_id, s_id)
        change["project_a_title"] = project_titles.get(p_a, p_a)
        change["project_b_title"] = project_titles.get(p_b, p_b)

# Metrics shown in the multi-solution overview table.
# Each row: (label, indicator group, indicator key, which direction is better)
OVERVIEW_METRICS = [
    ("Average skill fit", "efficiency", "mean_skill_fit", "high"),
    ("Unmet soft requirements", "efficiency", "unmet_soft_requirements_count", "low"),
    ("Average preference rank", "fairness", "mean_rank", "low"),
    ("Worst preference rank", "fairness", "worst_rank", "low"),
    ("Students outside their preferences", "fairness", "unranked_count", "low"),
    ("Rank Gini (inequality)", "fairness", "rank_gini", "low"),
]


def _build_overview(solutions: list[models.Solution]) -> list[dict[str, Any]]:
    """Builds one table row per metric, with the value of every alternative.

    The best value in each row is stored in "best" so the template can
    highlight it. If all alternatives have the same value, nothing is
    highlighted ("best" stays None).
    """
    rows = []
    for label, group, key, better in OVERVIEW_METRICS:
        values = []
        for s in solutions:
            values.append(s.indicators.get(group, {}).get(key))

        numbers = [v for v in values if v is not None]
        best = None
        if len(set(numbers)) > 1:
            if better == "high":
                best = max(numbers)
            else:
                best = min(numbers)

        rows.append(
            {
                "label": label,
                "key": key,
                "better": better,
                "values": values,
                "best": best,
            }
        )
    return rows

@web_bp.get("/compare")

def compare_solutions() -> Any:
    run_repo = repositories.RunRepository()
    runs = run_repo.list_runs()

    # 1. Collect all solutions from recent runs (for the two dropdowns)
    all_solutions: list[models.Solution] = []
    for run in runs:
        all_solutions.extend(run.solutions)

    # 2. Multisolution overview: all alternatives of one run side by side
    run_id = flask.request.args.get("run", "").strip()
    selected_run = None
    if run_id:
        selected_run = run_repo.get_run(run_id)
        if selected_run is None:
            flask.flash(f"Run '{run_id}' not found.", "warning")
    elif runs:
        selected_run = runs[0]  # newest run by default

    overview = []
    if selected_run is not None and selected_run.solutions:
        overview = _build_overview(selected_run.solutions)

    # 2. Read the chosen solution IDs from the URL (?sol1=...&sol2=...)
    sol1_id = flask.request.args.get("sol1", "").strip()
    sol2_id = flask.request.args.get("sol2", "").strip()

    # Nothing chosen yet: pre-select the first two alternatives
    if not sol1_id and not sol2_id and len(all_solutions) >= 2:
        sol1_id = all_solutions[0].id
        sol2_id = all_solutions[1].id

    sol_a = run_repo.get_solution(sol1_id) if sol1_id else None
    sol_b = run_repo.get_solution(sol2_id) if sol2_id else None

    # 3. Ask the engine for the comparison (mock until Team B is done)
    comparison = None
    if sol1_id and sol2_id:
        if sol_a is None or sol_b is None:
            flask.flash(
                "One or both selected solutions were not found. "
                "Run the optimizer first, then choose two solutions.",
                "warning",
            )
        else:
            engine: contract.AssignmentEngineContract = (
                solvers.AssignmentEngine()
            )
            try:
                comparison = engine.compare_solutions(sol1_id, sol2_id)
            except NotImplementedError:
                flask.flash(
                    "Notice: comparison metrics are not yet implemented by "
                    "Team B. Showing MockAssignmentEngine comparison.",
                    "info",
                )
                comparison = mocks.MockAssignmentEngine().compare_solutions(
                    sol1_id, sol2_id
                )
            except KeyError as exc:
                flask.flash(f"Comparison failed: {exc}", "danger")

            if comparison is not None:
                _add_display_names(comparison)

    # 4. Show the page
    return flask.render_template(
            "compare.html",
            runs=runs,
            selected_run=selected_run,
            overview=overview,
            all_solutions=all_solutions,
            sol_a=sol_a,
            sol_b=sol_b,
            comparison=comparison,
    )


@web_bp.get("/recommendations/<run_id>")
def view_recommendations(run_id: str) -> Any:
    """Displays transparent recommendations with evidence and advice."""
    run = repositories.RunRepository().get_run(run_id)
    if not run:
        flask.flash(f"Run '{run_id}' not found.", "danger")
        return flask.redirect(flask.url_for("visualization_web.dashboard"))

    recs = recommendations.generate_recommendations(run.solutions)

    return flask.render_template(
        "recommendations.html",
        run=run,
        recommendations=recs,
    )
