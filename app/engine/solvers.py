"""Mathematical optimization solvers and Strategy Pattern for TECH5.
Implements the binary Integer Linear Program described in the 
analytical_note_template_md using PuLP and the bundled CBC solver. 
Three strategies share one constraint set and only differs in their objective function.
Distinct alternatives are created with integer no-good cuts.
"""

import abc
import shutil
import time
from typing import Any
import uuid

import pulp
from app import config
from app.contract import contract
from app.domain import models
from app.domain import validation
from app.engine import metrics
from app.persistence import repositories

def _effective_rank(
    student: models.Student, project_id: str, num_projects: int
)  -> int:
    """Returns the stated rank or num_projects + 1 if unranked

    Args:
        student: Student whose preferences are looked up
        project_id: The project to look up.
        num_projects: Number of projects in the catalog.

    Returns:
        The effective rank used by the optimization model
    """
    rank =student.get_preference_rank(project_id)
    return rank if rank is not None else num_projects + 1


def _skill_fit(student: models.Student, project: models.Project
) -> tuple[float,list[str]]:
    """Computes the skill-fit score sigma and the unmet requirements

    Sigma averages min(1, level / required level) over the project
    requirements. Projects without requirements is given a neutral fit of 1.

    Args:
       student: The candidate student.
        project: The target project.

    Returns:
        A tuple of (skill_fit_score in [0, 1], list_of_unmet_skill_ids).
    """
    if not project.requirements:
        return 1.0,[]
    total =0.0
    unmet: list[str] =[]
    for req in project.requirements:
        level = student.get_skill_level(req.skill_id)
        required = max(req.minimum_level, 1)
        total += min(1.0, level / required)
        if level < req.minimum_level:
            unmet.append(req.skill_id)
    return total/len(project.requirements), unmet

class AssignmentStrategy(abc.ABC):
    """Abstract Base Class for student-to-project allocation strategies.
    Subclasses define the per-pair objective coefficient. The shared solve
    method builds the constraints and always maximizes total utility.
    """

    def __init__(self, name: str, description: str) -> None:
        """Initializes the strategy with descriptive metadata.

        Args:
            name: Machine-readable identifier for the strategy.
            description: Human-readable explanation of the objective function.
        """
        self.name = name
        self.description = description
        self._num_students = 0

    @abc.abstractmethod
    def calculate_cost_or_utility(
        self,
        student: models.Student,
        project: models.Project,
        max_preferences: int,
    ) -> float:
        """Computes the objective utility of assigning student to project.

        Args:
            student: The candidate student.
            project: The target semester project.
            max_preferences: Number of projects in the catalog.

        Returns:
            Utility coefficient of x[s, p] in the maximized objective.
        """
        
    def _add_extra_terms(
        self, 
        prob: pulp.LpProblem,
        x: dict[tuple[int,int],pulp.LpVariable],
        students: list[models.Student],
        projects: list[models.Project],
    ) -> pulp.LpAffineExpression | float:
        """Hook for strategy-specific variables, constraints and terms.

        Args:
            prob: The problem under construction.
            x: Assignment variables indexed by (student index, project index).
            students: Students in the cohort
            projects: Projects in the catalog.

        Returns:
            An expression added to the objective (0 by default)
        """
        del prob, x, students, projects  # Unused by default.
        return 0.0

    def solve(
        self,
        students: list[models.Student],
        projects: list[models.Project],
        fixed_assignments: list[models.FixedAssignment] | None = None,
        excluded_solutions: list[list[tuple[str, str]]] | None = None,
    ) -> tuple[str, list[models.Assignment], float | None, dict[str, Any]]:
        """Solves the assignment ILP under this strategy's objective.

        Args:
            students: List of students in the cohort
            projects: List of available semester projects.
            fixed_assignments: Pre-assigned student-project pairs that must hold.
            excluded_solutions: Earlier allocations, each cut off by a no-good
            cut so that the new solution differs for at least one student.

        Returns:
            A tuple of (solver_status, assignments, objective_value, 
            diagnostics). Assignments is empty if no solution was found.
        """
        fixed_assignments =fixed_assignments or []
        excluded_solutions= excluded_solutions or []
        self._num_students = len(students)
        num_projects= len(projects)
        s_index ={s.id: i for i,s in enumerate(students)}
        p_index ={p.id: j for j,p in enumerate(projects)}

        prob = pulp.LpProblem(f"assignment_{self.name}", pulp.LpMaximize)
        x = {
            (i, j): pulp.LpVariable(f"x_{i}_{j}", cat=pulp.LpBinary)
        for i in range(len(students))
        for j in range(num_projects)
        }

        #Objective: per-pair utility including strategy-specific extra terms.
        utility = pulp.lpSum(
            self.calculate_cost_or_utility(s, p, num_projects) * x[i, j]
            for i, s in enumerate(students)
            for j, p in enumerate(projects)
        )
        extra = self._add_extra_terms(prob, x, students, projects)
        prob += utility+ extra

        # (1)Every student is given exactly one project
        for i in range(len(students)):
            prob += (
                pulp.lpSum(x[i,j] for j in range(num_projects))== 1,
                f"one_project_{i}", )

        for j, project in enumerate(projects):
            load= pulp.lpSum(x[i, j] for i in range(len(students)))
            #(2) Headcount bounds
            prob += load >= project.min_capacity, f"min_cap_{j}"
            prob += load <= project.max_capacity, f"max_cap_{j}"
            #(4) A non-empty project has a qualified member per mandatory requirement
            for r, req in enumerate(project.requirements):
                if not req.is_mandatory:
                    continue
                qualified = pulp.lpSum(
                    x[i, j]
                    for i, s in enumerate(students)
                    if s.get_skill_level(req.skill_id) >= req.minimum_level)
                prob += (
                    project.max_capacity * qualified >= load,
                    f"mandatory_{j}_{r}",)

        #(3) Fixed assignments
        for k, fixed in enumerate(fixed_assignments):
            if fixed.student_id in s_index and fixed.project_id in p_index:
                i = s_index[fixed.student_id]
                j = p_index[fixed.project_id]
                prob += x[i, j]==1, f"fixed_{k}"

        #(5) No-good cuts against earlier allocations.
        for c, previous in enumerate(excluded_solutions):
            prob += (
                pulp.lpSum(
                    x[s_index[s_id], p_index[p_id]]
                    for s_id, p_id in previous
                    if s_id in s_index and p_id in p_index)
                <= len(students)-1,
                f"no_good_{c}",)

        start = time.perf_counter()
        cbc_path = shutil.which("cbc")
        if cbc_path:
            solver = pulp.COIN_CMD(
                path=cbc_path,
                msg=False,
                timeLimit=config.Config.PULP_TIME_LIMIT_SECONDS,
            )
        else:
            solver = pulp.PULP_CBC_CMD(
                msg=False,
                timeLimit=config.Config.PULP_TIME_LIMIT_SECONDS,
            )
        prob.solve(solver)
        status = pulp.LpStatus[prob.status]
        diagnostics: dict[str, Any] ={
            "solver_status": status,
            "solve_time_seconds": round(time.perf_counter() - start, 4),
            "variables_count": len(prob.variables()),
            "constraints_count": prob.numConstraints(),}

        found=(pulp.LpSolutionOptimal, pulp.LpSolutionIntegerFeasible)
        if prob.sol_status not in found:
            return status, [], None, diagnostics
        if prob.sol_status == pulp.LpSolutionIntegerFeasible:
            diagnostics["warning"] = (
                "Time limit reached; the solution may not be optimal.")

        fixed_pairs = {(f.student_id, f.project_id) for f in fixed_assignments}
        assignments: list[models.Assignment] = []
        for i, student in enumerate(students):
            for j, project in enumerate(projects):
                value = x[i, j].value()
                if value is None or value < 0.5:
                    continue
                fit,unmet = _skill_fit(student, project)
                assignments.append(
                    models.Assignment(
                        student_id=student.id,
                        project_id=project.id,
                        is_fixed=(student.id, project.id) in fixed_pairs,
                        preference_rank=student.get_preference_rank(
                            project.id
                        ),
                        skill_fit_score=round(fit, 4),
                        unmet_requirements=unmet,
                    ))
        return status, assignments, pulp.value(prob.objective),diagnostics


class PreferenceOrientedSolver(AssignmentStrategy):
    """Minimizes total effective rank. Skill fit only breaks ties."""

    def __init__(self) -> None:
        """Initializes the preference-oriented strategy."""
        super().__init__(
            name="PREFERENCE",
            description=(
                "Minimizes total preference rank. Skill fit is used only to break ties."
            ),)

    def calculate_cost_or_utility(
        self,
        student: models.Student,
        project: models.Project,
        max_preferences: int,
    ) -> float:
        """Returns -rank+epsilon*sigma with epsilon = 1/(n+ 1)

        Args:
            student: The candidate student
            project: The target semester project.
            max_preferences: Number of projects in the catalog (m).

        Returns:
            Utility coefficient of x[s,p].
        """
        rank= _effective_rank(student, project.id, max_preferences)
        fit, _ = _skill_fit(student, project)
        epsilon = 1.0 /(self._num_students+ 1)
        return -rank +epsilon * fit


class SkillFitOrientedSolver(AssignmentStrategy):
    """Maximizes total skill fit; preference rank only breaks ties."""

    def __init__(self) -> None:
        """Initializes the skill-fit-oriented strategy"""
        super().__init__(
            name="SKILL_FIT",
            description=(
                "Maximizes total skill fit; preference rank is used only to "
                "break ties."
            ),)

    def calculate_cost_or_utility(
        self,
        student: models.Student,
        project: models.Project,
        max_preferences: int,
        )-> float:
        """Returns sigma-delta*rank with delta = 1e-3/(n *(m + 1)).

        Args:
            student: The candidate student
            project: The target semester project
            max_preferences: Number of projects in the catalog (m)

        Returns:
            Utility coefficient of x[s,p]
        """
        rank = _effective_rank(student, project.id, max_preferences)
        fit, _ = _skill_fit(student, project)
        delta = 1e-3/(max(self._num_students, 1) * (max_preferences + 1))
        return fit-delta*rank


class BalancedTradeoffSolver(AssignmentStrategy):
    """Weighted preference and skill fit, protecting the worst-off student"""

    def __init__(
        self, preference_weight: float = 0.5, fairness_weight: float = 1.0
    ) -> None:
        """Initializes the balanced strategy

        Args:
            preference_weight: Lambda, weight of preference vs. skill fit
            fairness_weight: Mu, penalty weight on the worst assigned rank
        """
        super().__init__(
            name="BALANCED",
            description=(
                "Weighted sum of normalized preference score and skill fit, "
                "minus a penalty on the worst assigned rank."
            ),)
        self.preference_weight=preference_weight
        self.fairness_weight=fairness_weight

    def calculate_cost_or_utility(
        self,
        student: models.Student,
        project: models.Project,
        max_preferences: int,
    ) -> float:
        """Returns lambda*pi+(1-lambda)*sigma

        Args:
            student: The candidate student
            project: The target semester project
            max_preferences: Number of projects in the catalog (m)

        Returns:
            Utility coefficient of x[s, p]
        """
        rank=_effective_rank(student, project.id, max_preferences)
        pref_score= (max_preferences + 1 - rank) / max_preferences
        fit, _= _skill_fit(student, project)
        lam =self.preference_weight
        return lam*pref_score+(1-lam)*fit

    def _add_extra_terms(
        self,
        prob: pulp.LpProblem,
        x: dict[tuple[int, int], pulp.LpVariable],
        students: list[models.Student],
        projects: list[models.Project],
    ) -> pulp.LpAffineExpression | float:
        """Adds z >= rank of every student and the term -mu* (z -1)/ m.

        Args:
            prob: The problem under construction
            x: Assignment variables indexed by (student index, project index)
            students: Students in the cohort
            projects: Projects in the catalog

        Returns:
            The fairness penalty expression added to the objective.
        """
        num_projects = len(projects)
        z = pulp.LpVariable("worst_rank", lowBound=1, upBound=num_projects + 1)
        for i, student in enumerate(students):
            prob += (
                z
                >= pulp.lpSum(
                    _effective_rank(student, p.id, num_projects) * x[i, j]
                    for j, p in enumerate(projects)
                ),
                f"worst_rank_{i}",
            )
        return -(self.fairness_weight / num_projects) * (z - 1)


class AssignmentEngine(contract.AssignmentEngineContract):
    """Main Assignment Engine orchestrating validation, execution, and persistence.

    Implements the internal component contract (AssignmentEngineContract)
    connecting Component B to Component A.
    """

    def __init__(
        self, run_repo: repositories.RunRepository | None = None
    ) -> None:
        """Initializes the AssignmentEngine with persistence repositories.

        Args:
            run_repo: Optional repository for persisting runs and solutions.
        """
        self.run_repo = (
            run_repo if run_repo is not None else repositories.RunRepository()
        )
        self.strategies: dict[str, AssignmentStrategy] = {
            strategy.name: strategy
            for strategy in (
                PreferenceOrientedSolver(),
                SkillFitOrientedSolver(),
                BalancedTradeoffSolver(),
            )
        }

    def validate_inputs(
        self, request: contract.RunRequest
    ) -> contract.ValidationOutcome:
        """Validates cohort and constraints before attempting optimization.

        Args:
            request: The run request containing students, projects, etc.

        Returns:
            ValidationOutcome with validity, feasibility, errors, and warnings.
        """
        val_result = validation.validate_cohort(
            students=request.students,
            projects=request.projects,
            skills=request.skills,
            fixed_assignments=request.fixed_assignments,
        )
        return contract.ValidationOutcome(
            is_valid=val_result.is_valid,
            is_feasible=val_result.is_feasible,
            errors=list(val_result.errors),
            warnings=list(val_result.warnings),
            infeasibility_reasons=list(val_result.infeasibility_reasons),
        )

    def execute_run(
        self, request: contract.RunRequest
    ) -> models.AssignmentRun:
        """Validates, solves for distinct alternatives, and persists the run.

        Args:
            request: The run request containing students, projects, etc.

        Returns:
            The created AssignmentRun populated with alternative solutions.
        """
        run_id = str(uuid.uuid4())
        configuration = {
            "primary_strategy": request.strategy_key,
            "max_alternatives": request.max_alternatives,
            "engine": "AssignmentEngine (PuLP/CBC ILP)",
            "notes": request.notes,
        }
        # Tables are created idempotently, so the engine also works when it is used without the Flask app (e.g. directly from tests).
        self.run_repo.db.initialize_schema()

        #1. Validate. Feasibility first: validation also lists its infeasibility reasons under errors.
        outcome =self.validate_inputs(request)
        if not outcome.is_feasible or not outcome.is_valid:
            status = (
                contract.RunStatus.INFEASIBLE
                if not outcome.is_feasible
                else contract.RunStatus.INVALID_INPUT)
            
            return self._finish(
                run_id,
                status,
                configuration,
                [],
                {
                    "solver_status": "NOT_SOLVED",
                    "message": "Input rejected by validation before solving.",
                    "reasons": outcome.infeasibility_reasons,
                    "errors": outcome.errors,
                    "warnings": outcome.warnings,
                    "distinct_alternatives": 0,
                },)

        strategy = self.strategies.get(request.strategy_key.upper())
        if strategy is None:
            return self._finish(
                run_id,
                contract.RunStatus.INVALID_INPUT,
                configuration,
                [],
                {
                    "solver_status": "NOT_SOLVED",
                    "errors": [
                        f"Unknown strategy '{request.strategy_key}'. "
                        f"Available: {sorted(self.strategies)}."
                    ],
                    "distinct_alternatives": 0,
                },)

        # 2. Synchronize entities so solutions satisfy foreign keys
        self._sync_entities(request)

        # 3. Solve repeatedly, cutting off every allocation already found
        found: list[list[tuple[str, str]]] = []
        solutions: list[models.Solution] = []
        last_status = "NOT_SOLVED"
        solve_time = 0.0
        first_diag: dict[str, Any] = {}
        for alt_number in range(1, max(1, request.max_alternatives) + 1):
            last_status, assignments, objective, diag = strategy.solve(
                request.students,
                request.projects,
                request.fixed_assignments,
                found,
            )
            solve_time += diag["solve_time_seconds"]
            first_diag = first_diag or diag
            if not assignments:
                break
            found.append([(a.student_id, a.project_id) for a in assignments])
            solutions.append(
                models.Solution(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    alternative_number=alt_number,
                    strategy_name=strategy.name,
                    objective_value=(
                        round(objective, 6) if objective is not None else None
                    ),
                    assignments=assignments,
                    indicators=self._compute_indicators(request, assignments),
                    warnings=[diag["warning"]] if "warning" in diag else [],
                    diagnostics=diag,
                )
            )

        # 4. Derive run status and diagnostics
        diagnostics: dict[str, Any] = {
            "solver_status": first_diag.get("solver_status", last_status),
            "solve_time_seconds": round(solve_time, 4),
            "variables_count": first_diag.get("variables_count", 0),
            "constraints_count": first_diag.get("constraints_count", 0),
            "distinct_alternatives": len(solutions),
            "requested_alternatives": request.max_alternatives,
            "warnings": outcome.warnings,
        }
        if solutions:
            status = contract.RunStatus.COMPLETED
            if len(solutions) < request.max_alternatives:
                diagnostics["message"] = (
                    f"Only {len(solutions)} distinct allocation(s) exist "
                    f"under the hard constraints."
                )
        elif last_status == "Infeasible":
            status = contract.RunStatus.INFEASIBLE
            diagnostics["reasons"] = [
                "The solver proved that no allocation satisfies all hard "
                "constraints (capacities, locks and mandatory skills combined)."
            ]
        else:
            status = contract.RunStatus.FAILED
            diagnostics["errors"] = [
                f"Solver ended without a solution (status: {last_status})."
            ]
        return self._finish(
            run_id, status, configuration, solutions, diagnostics
        )

    def _finish(
        self,
        run_id: str,
        status: contract.RunStatus,
        configuration: dict[str, Any],
        solutions: list[models.Solution],
        diagnostics: dict[str, Any],
    ) -> models.AssignmentRun:
        """Builds, persists and returns an AssignmentRun.

        Args:
            run_id: Identifier of the run.
            status: Final run status.
            configuration: Run configuration metadata.
            solutions: Distinct solutions found (may be empty).
            diagnostics: Run-level diagnostics shown in the UI.

        Returns:
            The persisted AssignmentRun.
        """
        run = models.AssignmentRun(
            id=run_id,
            status=status.value,
            configuration=configuration,
            solutions=solutions,
            diagnostics=diagnostics,
        )
        self.run_repo.save_run(run)
        return run

    def _sync_entities(self, request: contract.RunRequest) -> None:
        """Saves skills, projects, students and locks to the database.

        Args:
            request: The run request whose entities are persisted.
        """
        db = self.run_repo.db
        skill_repo = repositories.SkillRepository(db)
        for skill in request.skills or []:
            skill_repo.save(skill)
        project_repo = repositories.ProjectRepository(db)
        for project in request.projects:
            project_repo.save(project)
        student_repo = repositories.StudentRepository(db)
        for student in request.students:
            student_repo.save(student)
        fixed_repo = repositories.FixedAssignmentRepository(db)
        for fixed in request.fixed_assignments or []:
            fixed_repo.save(fixed)

    def _compute_indicators(
        self,
        request: contract.RunRequest,
        assignments: list[models.Assignment],
    ) -> dict[str, Any]:
        """Computes solution indicators via the metrics module.

        Args:
            request: The run request with the cohort.
            assignments: The allocation to evaluate.

        Returns:
            Indicator dictionary, or {} while metrics are not implemented.
        """
        try:
            return metrics.compute_solution_indicators(
                request.students,
                request.projects,
                assignments,
                request.fixed_assignments,
            )
        except NotImplementedError:
            # TODO(Team B): Remove once metrics.compute_solution_indicators
            # is implemented.
            return {}

    def run_assignment(
        self,
        students: list[models.Student],
        projects: list[models.Project],
        skills: list[models.Skill] | None = None,
        fixed_assignments: list[models.FixedAssignment] | None = None,
        strategy_name: str = "PREFERENCE",
        max_alternatives: int = 3,
        notes: str = "",
    ) -> models.AssignmentRun:
        """Convenience method delegating to execute_run via RunRequest.

        Args:
            students: Student profiles.
            projects: Project specifications.
            skills: Optional skills catalog.
            fixed_assignments: Optional pre-allocated locks.
            strategy_name: Strategy key name.
            max_alternatives: Max solutions to generate.
            notes: Administrative description or notes for the run.

        Returns:
            The created AssignmentRun.
        """
        req = contract.RunRequest(
            students=students,
            projects=projects,
            skills=skills or [],
            fixed_assignments=fixed_assignments or [],
            strategy_key=strategy_name,
            max_alternatives=max_alternatives,
            notes=notes,
        )
        return self.execute_run(req)

    def list_runs(self, limit: int = 20) -> list[models.AssignmentRun]:
        """Retrieves historical assignment runs from repository.

        Args:
            limit: Maximum number of runs to retrieve.

        Returns:
            List of historical AssignmentRun domain objects.
        """
        return self.run_repo.list_runs(limit=limit)

    def get_run(self, run_id: str) -> models.AssignmentRun | None:
        """Retrieves a specific run by identifier.

        Args:
            run_id: Unique run identifier.

        Returns:
            The AssignmentRun object, or None if not found.
        """
        return self.run_repo.get_run(run_id)

    def get_solution(self, solution_id: str) -> models.Solution | None:
        """Retrieves a specific solution and its student allocations.

        Args:
            solution_id: Unique solution identifier.

        Returns:
            The Solution object with assignments, or None if not found.
        """
        return self.run_repo.get_solution(solution_id)

    def compare_solutions(
        self, solution_a_id: str, solution_b_id: str
    ) -> models.RunComparison:
        """Compares two alternative solutions side-by-side using metrics module.

        Args:
            solution_a_id: Identifier of the baseline solution.
            solution_b_id: Identifier of the comparison solution.

        Returns:
            RunComparison containing delta metrics and changed assignments.

        Raises:
            KeyError: If either solution cannot be found.
        """
        sol_a = self.run_repo.get_solution(solution_a_id)
        sol_b = self.run_repo.get_solution(solution_b_id)
        if sol_a is None or sol_b is None:
            raise KeyError(
                f"Solutions not found: {solution_a_id}, {solution_b_id}"
            )
        comp_dict = metrics.compare_two_solutions(sol_a, sol_b)
        return models.RunComparison.from_dict(comp_dict)
