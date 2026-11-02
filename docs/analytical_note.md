# Deliverable 6: Analytical Note & Mathematical Formulation
## Student Submission Template — TECH5 Collaborative Project

**Team:** Group number 9  
**Authors (Team B - Assignment Engine):** Olav Gramstad Berstad, Emil Lund Skålsvik  
**Authors (Team A - Visualization & Recommender):** Lan Nguyen, Maja Karlsen, Paulina Nguyen  
**Course:** TECH5 Programming & Application Design, NHH Norwegian School of Economics  
**Date:** 2 November 2026

---

> [!IMPORTANT]
> **Instructions for Students:**  
> This document serves as the formal deliverable template for **Deliverable 6 (Analytical Note)** as defined in Section 15 and Section 6 of the TECH5 project specification (`projectTech5.tex`).  
>
> Replace all bracketed text `[...]` with your team's mathematical formulation, indicator derivations, decision criteria, and critical reflections. Maintain rigorous mathematical notation and explain how your analytical design translates directly into your Python implementation in `app/engine/solvers.py` and `app/engine/metrics.py`.

---

## 1. Problem Definition & Mathematical Modeling Approach

### 1.1 Business Context & Decision Dilemma
*Describe the real-world allocation challenge faced by academic coordinators. Discuss the inherent conflict between collective project quality (skill matching) and individual student satisfaction (preference rank).*

A programme coordinator must place every student on exactly one project, within each project's minimum and maximum team size, with mandatory skills covered and fixed assignments respected. Students rank the projects they want, and projects need certain skill levels.

These goals conflict: giving students their preferred projects can leave a project without the skills it needs, while placing students by skill can push many down their lists. Rezaeinia et al. (2022) solve this problem for the CEMS master programme at NHH with a bi-objective integer program that weighs efficiency (total preference utility) against fairness, subject to company requirements. They report a small but real trade-off between the two (the "price of fairness") and clear gains over manual assignment. Our tool produces several alternatives, measures each on the same indicators, and leaves the final choice to the coordinator.

### 1.2 Chosen Assignment Methodology & Academic Justification
*Identify your approved assignment methodology (e.g., Integer Linear Programming with PuLP/CBC, stable matching variant, heuristic search, or bipartite min-cost flow).*

We model the problem as a **binary Integer Linear Program (ILP)**, solved with PuLP and the CBC solver.
- **Exactness:** only an exact solver can prove that no allocation exists (`INFEASIBLE`) and that no further distinct alternative exists (edge cases 13–15).
- **Side constraints:** mandatory skills constrain the composition of each project, which rules out the Hungarian algorithm and min-cost flow; stable matching ignores skill fit and minimum quotas.
- **Scale:** the model has $n \cdot m$ binary variables (40 for the demo cohort); each run of three alternatives solves in under 0.3 s.



---

## 2. Mathematical Formulation

### 2.1 Index Sets & Dimensions
Define the primary index sets used throughout your mathematical model:
- $S = \{s_1, s_2, \dots, s_n\}$: Set of students in the cohort ($|S| = n$).
- $P = \{p_1, p_2, \dots, p_m\}$: Set of available semester projects ($|P| = m$).
- $K = \{k_1, k_2, \dots, k_q\}$: Set of evaluated technical skills ($|K| = q$).
- $F \subseteq S \times P$: Set of pre-allocated fixed assignment pairs $(s, p)$.
- $R_p \subseteq K$: Set of skills required by project $p$. $R_p = \emptyset$ if the project has no requirements.
- $M \subseteq P \times K$: Set of mandatory requirements, i.e. pairs $(p, k)$ where skill $k \in R_p$ is flagged as mandatory.
- $Q_{p,k} = \{ s \in S : \text{skill}_{s,k} \ge \text{req}_{p, k} \}$: Set of students qualified for requirement $(p, k)$.
- $A^{(1)}, \dots, A^{(j)} \subseteq S \times P$: Allocation found in earlier iterations of the same run.

### 2.2 Model Parameters
Formally define all input parameters, units, and ranges:
- $l_p \in \mathbb{Z}_{\ge 0}$: Minimum headcount capacity for project $p$.
- $u_p \in \mathbb{Z}_{\ge 1}$: Maximum headcount capacity for project $p$ ($l_p \le u_p$).
- $r_{s,p} \in \{1, \dots, m\}$: Stated preference rank of student $s$ for project $p$, if ranked.
- $\tilde r_{s, p}$: Effective rank used by the model. Unranked projects are not forbidden, but penalised:
  $$\tilde r_{s,p} = \begin{cases} r_{s,p} & \text{if } s \text{ ranked } p \\ m + 1 & \text{otherwise} \end{cases}$$
- $\pi_{s,p} \in [0,1]$: Normalised preference score (1 =first choice, 0 = unranked):
  $$\pi_{s,p} = \frac{m + 1 - \tilde r_{s,p}}{m}$$
- $\text{skill}_{s,k} \in \{0, 1, 2, 3, 4, 5\}$: Proficiency of student $s$ in skill $k$.
- $\text{req}_{p,k} \in \{1, 2, 3, 4, 5\}$: Stated requirement level of project $p$ for skill $k$.
- $\sigma_{s,p} \in [0, 1]$: Normalized skill-fit score of student $s$ assigned to project $p$.
  $$\sigma_{s,p} = \begin{cases} \dfrac{1}{|R_p|}\displaystyle\sum_{k \in R_p}\min\!\left(1, \frac{\text{skill}_{s,k}}{\text{req}_{p,k}}\right)& \text{if } R_p \neq \emptyset \\[2ex] 1 & \text{if } R_p = \emptyset \end{cases}$$
- $\lambda \in [0,1]$, $\mu \ge 0$: Weights of the balanced strategy in 2.5

### 2.3 Decision Variables
Define your optimization decision variables:
- $x_{s,p} \in \{0, 1\}$: Binary decision variable equal to $1$ if student $s$ is assigned to project $p$, and $0$ otherwise.
- $z \in [1, m+1]$: Auxiliary minimax variable equal to the worst effective rank received by any student.

### 2.4 Hard Mathematical Constraints
Formulate all mandatory system constraints mathematically:

1. **Exact Allocation Constraint:**
   $$\sum_{p \in P} x_{s,p} = 1 \quad \forall s \in S$$
   *Explanation: Every student must receive exactly one project.*

2. **Project Headcount Capacity Bounds:**
   $$l_p \le \sum_{s \in S} x_{s,p} \le u_p \quad \forall p \in P$$
   *Explanation: Project enrollments must respect minimum and maximum quotas.*

3. **Administrative Fixed Allocations (Locks):**
   $$x_{s^*, p^*} = 1 \quad \forall (s^*, p^*) \in F$$
   *Explanation: Pre-assigned pairs must be strictly enforced.*

4. **Mandatory Skill Qualification:**
   $$u_p\sum_{s \in Q_{p, k}} x_{s ,p} \;\ge\; \sum_{s \in S} x_{s, p} \quad \forall (p, k) \in M$$
   *Explanation: If project $p$ has members, at least one meets the requirement. Empty projects are allowed.*

5. **Distinct Alternative Solutions (No-Good Integer Cuts):**
   $$\sum_{(s, p) \in A^{(i)}} x_{s ,p} \;\le\; n - 1 \quad \forall i =1, \dots, j$$
   *Explanation: Each alternative solution must move at least one
   student compared with every previous solution.*

6. **Minimax Linking (balanced strategy):**
   $$z \;\ge\; \sum_{p \in P} \tilde r_{s,p}\, x_{s,p} \quad \forall s \in S$$


### 2.5 Optimization Objectives & Strategies
Formulate the objective functions corresponding to your implemented strategies in `solvers.py`:

- **Strategy 1: Preference-Oriented (Minimize Regret)**
  $$\min Z_{\text{pref}} = \sum_{s \in S} \sum_{p \in P} \tilde r_{s,p}\, x_{s,p} \;-\; \varepsilon \sum_{s \in S} \sum_{p \in P} \sigma_{s,p}\, x_{s,p}, \qquad \varepsilon = \frac{1}{n + 1}$$
- **Strategy 2: Skill-Fit-Oriented (Maximize Quality)**
  $$\max Z_{\text{skill}} = \sum_{s \in S} \sum_{p \in P} \sigma_{s,p}\, x_{s,p} \;-\; \delta \sum_{s \in S} \sum_{p \in P} \tilde r_{s,p}\, x_{s,p}, \qquad \delta = \frac{10^{-3}}{n\,(m + 1)}$$
- **Strategy 3: Balanced Trade-Off (Compromise)**
  $$\max Z_{\text{bal}} = \sum_{s \in S} \sum_{p \in P} \big(\lambda\, \pi_{s,p} + (1 - \lambda)\, \sigma_{s,p}\big)\, x_{s,p} \;-\; \mu\, \frac{z - 1}{m}$$


### 2.6 Solution Procedure & Run Status
`AssignmentEngine.execute_run` proceeds as follows:
1. **Validate.** If the input is proven infeasible, return `INFEASIBLE` without solving; otherwise, if it is invalid or the strategy is unknown, return `INVALID_INPUT`. Feasibility is checked first, because infeasibility is also reported as a validation error.
2. **Save the cohort** (students, projects, skills, locks), since solutions reference them in the database.
3. **Solve** up to `max_alternatives` times with CBC, adding a no-good cut after each solution. Infeasible at $i = 1$ gives `INFEASIBLE`; infeasible at $i > 1$ stops the loop, as all distinct allocations have been found.
4. **Store** each solution with its assignments, objective value and indicators from `metrics.compute_solution_indicators`.
5. **Report** `COMPLETED` if at least one solution exists (`FAILED` if the solver stops without one), with diagnostics: solver status, solve time, model size, `distinct_alternatives`, and the message "Only N distinct allocation(s) exist" when fewer than requested.

---

## 3. Evaluation Indicators & Analytical Metrics

All indicators are computed after solving, from the final allocation $x$, in `app/engine/metrics.py`. They do not depend on which strategy produced a solution, so every alternative is measured on the same scale. Ranks always use the effective rank $\tilde r_{s,p}$ from Section 2.2, so a student placed outside their list counts as rank $m+1$. This is the same rule the solver optimises, so what is optimised and what is reported agree.

Notation: $p(s)$ is the project assigned to student $s$ (the $p$ with $x_{s,p} = 1$), $\tilde r_s = \tilde r_{s,p(s)}$, $\sigma_s = \sigma_{s,p(s)}$, and $n_p = \sum_{s \in S} x_{s,p}$ is the headcount of project $p$.

### 3.1 Feasibility Indicators
The solver enforces the constraints of Section 2.4, but the metrics check them again independently. A solution loaded from the database, or produced by a faulty strategy, can therefore never be shown as valid by mistake. Each check gives pass/fail plus a list of violations naming the student or project.
- **Allocation completeness:** every student has exactly one project: $\sum_{p \in P} x_{s,p} = 1 \quad \forall s \in S$
- **Capacity compliance:** $l_p \le n_p \le u_p \quad \forall p \in P$
- **Fixed assignment adherence:** $x_{s,p} = 1 \quad \forall (s,p) \in F$, reported as the number of locks respected out of $|F|$.
- **Mandatory requirement fulfilment:** every non-empty project has at least one qualified member per mandatory skill: $\sum_{s \in Q_{p,k}} x_{s,p} \ge 1 \quad \forall (p,k) \in M : n_p > 0$. Reported as the number of fulfilled mandatory requirements out of those that apply.
- A solution is reported as **feasible** only if all four checks pass.

### 3.2 Efficiency Indicators
- **Mean Skill-Fit Score ($\bar{\sigma}$), our main efficiency measure:**
  $$\bar{\sigma} = \frac{1}{n} \sum_{s \in S} \sum_{p \in P} \sigma_{s,p} \cdot x_{s,p}$$
  *Meaning: the average share of their project's skill requirements a student covers, from 0 (none) to 1 (every required level met). A partial skill earns partial credit through $\min(1, \text{skill}/\text{req})$, and exceeding a level earns no extra credit, so the measure rewards covering requirements rather than stacking experts on one project. It is the quantity the skill-fit strategy optimises, and it reads naturally: "on average, students meet 82% of what their project asks for". The score of each assignment is stored with the solution when it is created, and the mean is taken over these stored scores.*
- **Minimum Skill Fit:** $\sigma_{\min} = \min_{s \in S} \sigma_s$, the worst-matched student.
- **Unmet Requirements Count:** the number of pairs $(s,k)$ with $k \in R_{p(s)}$ and $\text{skill}_{s,k} < \text{req}_{p(s),k}$, listed per project and split into soft and mandatory requirements. It shows where the skill gaps are, not only their average.
- **Mean Preference Rank ($\bar{r}$):**
  $$\bar{r} = \frac{1}{n} \sum_{s \in S} \sum_{p \in P} \tilde r_{s,p} \cdot x_{s,p}$$
  *Meaning: the average effective rank. 1.0 means every student got their first choice; lower is better. In the application it is grouped with the fairness indicators, since it describes student outcomes.*

### 3.3 Fairness Indicators
*Section 6.3 of the specification mandates: rank distribution, unranked count, worst assigned rank, and ONE proposed and justified fairness indicator.*

1. **Rank Distribution:** Histogram vector $[c_1, c_2, \dots, c_m, c_{\text{unranked}}]$ where $c_k = |\{s \in S : \tilde r_s = k\}|$ and $c_{\text{unranked}} = |\{s \in S : \tilde r_s = m+1\}|$. It shows what an average hides, e.g. whether a mean rank of 1.8 comes from many second choices or from a few very poor outcomes.
2. **Unranked Allocation Count ($U$):** $U = c_{\text{unranked}}$, the number of students placed outside their submitted list, also given as a percentage of $n$. Each of them is likely to be dissatisfied and may need a justification, so the application lists them by name.
3. **Worst Assigned Rank ($r_{\max}$):**
   $$r_{\max} = \max_{s \in S} \tilde r_s$$
   The outcome of the worst-off student. $r_{\max} = m+1$ means at least one student is outside their list.
4. **Proposed Fairness Indicator: Gini Coefficient of Effective Ranks ($G$):**
   $$G = \frac{\sum_{i=1}^n \sum_{j=1}^n |\tilde r_i - \tilde r_j|}{2 n \sum_{i=1}^n \tilde r_i}$$
   *Interpretation: $G$ is the average difference in rank between two students, divided by twice the mean rank. $G = 0$ when every student receives the same rank, and it grows as outcomes become more uneven. Because ranks lie between 1 and $m+1$, $G$ stays well below 1 in practice, so it is used to compare alternatives on the same cohort rather than read on its own.*

   *Why it captures inequality: the mean rank describes the average student and the worst rank describes a single student, but $G$ uses the whole distribution. Two solutions can have the same mean rank and treat students very differently: everyone getting their 2nd choice gives $G = 0$, while half getting their 1st and half their 3rd gives $G = 0.25$. $G$ separates these cases, which shows the decision-maker who pays for a higher average. It is also scale-free, so cohorts of different sizes can be compared, and it is a widely known inequality measure that is easy to explain.*

   *Limitation: $G$ divides by the mean, so the same spread counts as less unequal when ranks are generally worse ($[1, 3]$ gives 0.25, $[3, 5]$ gives 0.125). It is therefore always reported together with the mean rank and worst rank, never alone. The rank variance is also reported as a supporting measure.*

   Implementation: the equivalent sorted form $G = \frac{2 \sum_{i=1}^n i \, \tilde r_{(i)}}{n \sum_{i=1}^n \tilde r_{(i)}} - \frac{n+1}{n}$, with ranks sorted ascending, runs in $O(n \log n)$ instead of $O(n^2)$. $G = 0$ for an empty allocation.

### 3.4 Capacity Utilization Metrics
- Per-project utilization percentage:
  $$\text{Util}_p = \frac{n_p}{u_p} \times 100\%$$
- Overall utilization $\text{Util} = \frac{n}{\sum_{p \in P} u_p} \times 100\%$. The remainder is the aggregate slack: $\sum_{p \in P} u_p - n$ free places in the cohort.
- Per project: free places $u_p - n_p$ and margin above the minimum $n_p - l_p$. A project with no free places is flagged *full*; a project with $n_p = l_p > 0$ is flagged *at minimum*, since it cannot lose a student without becoming infeasible. These flags show which projects limit the alternatives.
- Projects with $n_p = 0$ are reported as *empty* (only possible when $l_p = 0$).

---

## 4. Trade-Off Analysis & Solution Comparison

### 4.1 Comparative Delta Formulation
For two solutions A and B, `compare_two_solutions` in `app/engine/metrics.py` shows every headline indicator for both, together with the difference B minus A:
$$\Delta \bar{\sigma} = \bar{\sigma}_B - \bar{\sigma}_A$$
$$\Delta \bar{r} = \bar{r}_B - \bar{r}_A$$
$$\Delta r_{\max} = r_{\max, B} - r_{\max, A}$$
$$\Delta U = U_B - U_A$$
$$\Delta G = G_B - G_A$$
- The number of unmet requirements is compared in the same way.
- Each delta is labelled *better* or *worse*, because the good direction differs: a positive $\Delta \bar{\sigma}$ is an improvement, while a positive $\Delta \bar{r}$, $\Delta r_{\max}$, $\Delta U$ or $\Delta G$ is a deterioration.
- The rank distributions are shown side by side rather than as one number.
- Values are rounded to four decimals to remove floating-point noise. A delta of 0 is reported as a *tie*, so equal scores are never presented as one solution being better.

### 4.2 Allocation Diff & Displaced Student Identification
- **Changed Assignments:** $C = \{(s, p_A, p_B) : x_{s, p_A}^{(A)} = 1 \land x_{s, p_B}^{(B)} = 1 \land p_A \ne p_B\}$. $|C|$ is the number of students who move. $C = \emptyset$ means the solutions are identical; the no-good cuts of Section 2.4 rule this out within one run.
- For every changed student: $\Delta r_s = \tilde r_s^{(B)} - \tilde r_s^{(A)}$ and $\Delta \sigma_s = \sigma_s^{(B)} - \sigma_s^{(A)}$.
- **Worsened Students ($\Delta r_s > 0$):** Students whose preference rank worsened in Solution B.
- **Improved Students ($\Delta r_s < 0$):** Students whose preference rank improved in Solution B.
- **Moved at Equal Rank ($\Delta r_s = 0$):** Students who changed project but kept the same rank, e.g. because of tied preferences. Their skill fit may still change.
- Changed students are listed one by one with old and new project, rank and skill fit, largest worsening first, so the decision-maker sees immediately who pays for a change.
- **Trade-Off Summary:** short plain-language statements generated from the deltas, e.g. "B raises mean skill fit by 0.40, but 2 students get a worse rank (mean rank +1.5)." This is calculated evidence only; the recommendation itself is made in Section 5.

---

## 5. Transparent Recommendation Rules

*In accordance with Section 9 of the specification, recommendations must separate calculated evidence from advice across distinct policy priorities.*

The rules are in `generate_recommendations` (`app/engine/recommendations.py`). For each priority, one solution is chosen among the alternatives of a run, using only the indicators of Section 3. The page shows calculated evidence and policy advice in separate blocks. Ties go to the next criterion.

### 5.1 Policy Priority 1: Student Preference Maximization
- **Quantitative Selection Criterion:** Lexicographic minimisation of $(U, \bar{r}, r_{\max})$.
- **Calculated Evidence Reported:** $\bar{r}$, $U$, $r_{\max}$ and $\bar{\sigma}$.
- **Administrative Advice & Trade-Off Warning:** Use when student satisfaction matters most. Skill fit may be lower than in the other alternatives.

### 5.2 Policy Priority 2: Project Delivery & Technical Competence
- **Quantitative Selection Criterion:** Maximise $\bar{\sigma}$, then minimise the number of unmet soft requirements.
- **Calculated Evidence Reported:** $\bar{\sigma}$, unmet soft requirements and $\bar{r}$.
- **Administrative Advice & Trade-Off Warning:** Use when project partners need strong technical teams. More students may get a lower-ranked project.

### 5.3 Policy Priority 3: Balanced & Egalitarian Compromise
- **Quantitative Selection Criterion:** Lexicographic minimisation of $(G, \text{Var}(\tilde r), \bar{r})$.
- **Calculated Evidence Reported:** $G$, rank variance, $\bar{\sigma}$ and $\bar{r}$.
- **Administrative Advice & Trade-Off Warning:** Use to avoid a few students carrying most of the cost. A low $G$ can come with a worse mean rank (Section 3.3), so read it together with $\bar{r}$ and $r_{\max}$.

---

## 6. Assumptions, Boundary Conditions & Edge Cases

Document all operational assumptions:
1. **Student Submission Incompleteness:** A project the student did not rank receives the rank $\tilde r_{s, p}= m+1$. They are permitted but penalised by all strategies.
2. **Ties in Preferences:** When multiple allocations are optimal, CBC returns one of them. The others appear as alternatives.
3. **Skill Levels:** A missing skill is counted as level 0. Projects without any requirements are given $\sigma_{s, p} =1$.
4. **Fixed Assignments:** All fixed assignments are hard constraints, as the specification requires locks to be strictly
preserved.
5. **Feasibility Boundaries:** Simple capacity and lock checks are done before solving, cases not feasible are detected by the solver and reported as 'INFEASIBLE'. 
6. **Input Validation:** Before the model is built, `app/domain/validation.py` checks the input. Malformed data is rejected with a message naming the record: unknown or duplicate identifiers (students, projects, skills), missing or non-integer capacities, $l_p > u_p$, skill levels outside 1 to 5, ranks outside 1 to $m$ (a stated rank above $m$ would rate a listed project below an unranked one), a project ranked twice, and a student fixed to two projects. Unusual but usable input only gives a warning: fewer than three preferences, tied ranks or gaps in ranks, a fixed assignment the student did not rank, and a project that must stay empty because nobody available is qualified.
7. **Infeasibility Pre-Checks:** The validator also tests necessary conditions, so that obvious infeasibility is explained in plain words instead of a bare solver status: $n > \sum_p u_p$, $n < \sum_p l_p$, $|F_p| > u_p$, $\sum_p \max(l_p, |F_p|) > n$, no available student in $Q_{p,k}$ for a project that must have members, a project filled by fixed students none of whom is in $Q_{p,k}$, and too few usable places once unstaffable projects are removed. Passing these checks does not prove feasibility; the solver remains the final test.

---

## 7. Limitations & Analytical Deficiencies

1. **Alternatives** Alternatives are the next-best solutions for an objective. They are not necessarily Pareto-optimal.
2. **Linear ranks** Every step in ranks are valued the same, e.g. 1->2 and 4->5.
3. **Weights** $\lambda$ and $\mu$ are policy choices, other values give other balanced solutions. 
4. **Scale** The size of the model grows as $n \cdot m$, and every alternative requires a new solve. This is fine for a course cohort, but less efficient for large ones.