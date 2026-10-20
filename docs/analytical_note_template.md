# Deliverable 6: Analytical Note & Mathematical Formulation
## Student Submission Template — TECH5 Collaborative Project

**Team:** [Team Name / Group Number]  
**Authors (Team B - Assignment Engine):** [Student Names & IDs]  
**Authors (Team A - Visualization & Recommender):** [Student Names & IDs]  
**Course:** TECH5 Programming & Application Design, NHH Norwegian School of Economics  
**Date:** [Submission Date]

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

[Provide a 1–2 paragraph summary of the problem, referencing Rezaeinia et al. (2022) for context without copying their proprietary algorithm.]

### 1.2 Chosen Assignment Methodology & Academic Justification
*Identify your approved assignment methodology (e.g., Integer Linear Programming with PuLP/CBC, stable matching variant, heuristic search, or bipartite min-cost flow).*

We choose to model the problem as a **Binary Integer Linear Programming**, solved with PuLP/CBC.
This is appropriate for this problem scale, since only an exact solver can prove that there is no solution, which is required in several cases. 


---

## 2. Mathematical Formulation

### 2.1 Index Sets & Dimensions
Define the primary index sets used throughout your mathematical model:
- $S = \{s_1, s_2, \dots, s_n\}$: Set of students in the cohort ($|S| = n$).
- $P = \{p_1, p_2, \dots, p_m\}$: Set of available semester projects ($|P| = m$).
- $K = \{k_1, k_2, \dots, k_q\}$: Set of evaluated technical skills ($|K| = q$).
- $F \subseteq S \times P$: Set of pre-allocated fixed assignment pairs $(s, p)$.
- $R_p = \subseteq K$: Set of skills required by project $p$. $R_p = \emptyset$ if the project has no requirements.
- $M \subseteq P \times K$: Set of mandatory requirements, i.e. pairs $(p, k)$ where skill $k \in R_p$ is flagged as mandatory.
-$Q_{p,k} = \{ s \in S : \text{skill}_{s,k} \ge \text{req}_{p, k} \}$: Set of students qualified for requirement ${p, k}$.
- $A^{(1)}, \dots, A^{(j)} \subseteq S \times P$: Allocation found in earlier iterations of the same run.

### 2.2 Model Parameters
Formally define all input parameters, units, and ranges:
- $l_p \in \mathbb{Z}_{\ge 0}$: Minimum headcount capacity for project $p$.
- $u_p \in \mathbb{Z}_{\ge 1}$: Maximum headcount capacity for project $p$ ($l_p \le u_p$).
- $r_{s,p} \in \{1, 2, \dots, |P|\} \cup \{|P|+1\}$: Stated preference rank of student $s$ for project $p$.
- $\tilde r_{s, p}$: Effective rank used by the model. Unranked projects are not forbidden, but penalised:
  $$\tilde r_{s,p} = \begin{cases} r_{s,p} & \text{if } s \text{ ranked } p \\ m + 1 & \text{otherwise} \end{cases}$$
- $\pi_{s,p} \in [0,1]$: Normalised preference score (1 =first choice, 0 = unranked):
  $$\pi_{s,p} = \frac{m + 1 - \tilde r_{s,p}}{m}$$
- $\text{skill}_{s,k} \in \{0, 1, 2, 3, 4, 5\}$: Proficiency of student $s$ in skill $k$.
- $\text{req}_{p,k} \in \{1, 2, 3, 4, 5\}$: Stated requirement level of project $p$ for skill $k$.
- $m_{p,k} \in \{0, 1\}$: Binary flag indicating if skill $k$ is mandatory for project $p$.
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
   *Explanation: If project $p$ has members, at least one meets the requirement. Empty prjects is allowed.*

5. **Distinct Alternative Solutions (No-Good Integer Cuts):**
   $$\sum_{(s, p) \in A^{(i)}} x_{s ,p} \;\le\; n - 1 \quad \forall i =1, \dots, j$$
   *Explanation: Each alternative solution must move at least one student compared with every previous solution.*

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
'AssignmentEngine.execute_run' proceeds as given:
1. Validate the input. Check feasibility first then the validity of the input. 
2. Build the model with the objective of the requested strategy
3. For $i=1, \dots, $'max_alternatives': solve with CBC.
    - If an optimal allocation is found, record it and its no-good cut.
    - If the model is infeasible at $i =1$, the status is 'INFEASIBLE'
    - If it becomes infeasible at $i >1$, stop; since all allocations are found
4. Store information related to the distinct alternatives found
5. Perform computations for each solution and persist the run.

---

## 3. Evaluation Indicators & Analytical Metrics

Define the mathematical formulation for all evaluation metrics implemented in `app/engine/metrics.py`:

### 3.1 Feasibility Indicators
- Allocation completeness: $\sum_{s \in S} \sum_{p \in P} x_{s,p} = |S|$
- Capacity compliance check for all $p \in P$
- Fixed lock adherence check
- Mandatory requirement fulfillment count

### 3.2 Efficiency Indicators
- **Mean Skill-Fit Score ($\bar{\sigma}$):**
  $$\bar{\sigma} = \frac{1}{|S|} \sum_{s \in S} \sum_{p \in P} \sigma_{s,p} \cdot x_{s,p}$$
- **Mean Preference Rank ($\bar{r}$):**
  $$\bar{r} = \frac{1}{|S|} \sum_{s \in S} \sum_{p \in P} r_{s,p} \cdot x_{s,p}$$

### 3.3 Fairness Indicators
*Section 6.3 of the specification mandates: rank distribution, unranked count, worst assigned rank, and ONE proposed and justified fairness indicator.*

1. **Rank Distribution:** Histogram vector $[c_1, c_2, \dots, c_{|P|}, c_{\text{unranked}}]$ where $c_k$ is the number of students assigned to their $k$-th choice.
2. **Unranked Allocation Count ($U$):** Count of students allocated outside their submitted preference list.
3. **Worst Assigned Rank ($r_{\max}$):**
   $$r_{\max} = \max_{(s,p) : x_{s,p}=1} r_{s,p}$$
4. **Team's Proposed Fairness Indicator (e.g., Gini Coefficient or Rank Variance):**
   *Provide the mathematical formula, justification, and interpretation:*
   $$G = \frac{\sum_{i=1}^n \sum_{j=1}^n |r_i - r_j|}{2 n \sum_{i=1}^n r_i}$$
   *[Explain why this metric captures inequality among student outcomes]*

### 3.4 Capacity Utilization Metrics
- Per-project utilization percentage:
  $$\text{Util}_p = \frac{\sum_{s \in S} x_{s,p}}{u_p} \times 100\%$$
- Aggregate cohort capacity slack and tightness

---

## 4. Trade-Off Analysis & Solution Comparison

### 4.1 Comparative Delta Formulation
Explain how the system computes performance deltas between Solution A and Solution B:
$$\Delta \bar{\sigma} = \bar{\sigma}_B - \bar{\sigma}_A$$
$$\Delta \bar{r} = \bar{r}_B - \bar{r}_A$$
$$\Delta r_{\max} = r_{\max, B} - r_{\max, A}$$
$$\Delta G = G_B - G_A$$

### 4.2 Allocation Diff & Displaced Student Identification
Define how student re-allocations are classified:
- **Changed Assignments:** $\{(s, p_A, p_B) : x_{s, p_A}^{(A)} = 1 \land x_{s, p_B}^{(B)} = 1 \land p_A \ne p_B\}$
- **Worsened Students ($\Delta r_s > 0$):** Students whose preference rank worsened in Solution B.
- **Improved Students ($\Delta r_s < 0$):** Students whose preference rank improved in Solution B.

---

## 5. Transparent Recommendation Rules

*In accordance with Section 9 of the specification, recommendations must separate calculated evidence from advice across distinct policy priorities.*

### 5.1 Policy Priority 1: Student Preference Maximization
- **Quantitative Selection Criterion:** [e.g., Lexicographic minimization of unranked count, then $\bar{r}$, then $r_{\max}$]
- **Calculated Evidence Reported:** [List indicators presented to the user]
- **Administrative Advice & Trade-Off Warning:** [When to apply and what compromises are made]

### 5.2 Policy Priority 2: Project Delivery & Technical Competence
- **Quantitative Selection Criterion:** [e.g., Maximization of mean skill fit $\bar{\sigma}$]
- **Calculated Evidence Reported:** [List indicators presented to the user]
- **Administrative Advice & Trade-Off Warning:** [When to apply and what compromises are made]

### 5.3 Policy Priority 3: Balanced & Egalitarian Compromise
- **Quantitative Selection Criterion:** [e.g., Multi-objective composite score or Gini minimization]
- **Calculated Evidence Reported:** [List indicators presented to the user]
- **Administrative Advice & Trade-Off Warning:** [When to apply and what compromises are made]

---

## 6. Assumptions, Boundary Conditions & Edge Cases

Document all operational assumptions:
1. **Student Submission Incompleteness:** A project the student did not rank receives the rank $\tilde r_{s, p}= m+1$. They are permitted but penalised by all strategies.
2. **Ties in Preferences:** When multiple allocations are optimal, CBC returns one of them. The others appear as alternatives.
3. **Skill Levels:** A missing skill is counted as level 0. Projects without any requirements are given $\sigma_{s, p} =1$.
4. **Fixed Assignments:** All fixed assignmetns are hard constraints **[CONFIRM]** 
5. **Feasibility Boundaries:** Simple capacity and lock checks are done before solving, cases not feasible are detected by the solver and reported as 'INFEASIBLE'. 

---

## 7. Limitations & Analytical Deficiencies

1. **Alternatives** Alternatives are the next-best solutions for an objective. They are not necessarily Pareto-optimal.
2. **Linear ranks** Every step in ranks are valued the same, e.g. 1->2 and 4->5.
3. **Weights** $\lambda$ and $\mu$ are policy choices, other values give other balanced solutions. 
4. **Scale** The size of the model grows as $n \cdot m$, and every alternative requires a new solve. This is fine for a course cohort, but less efficient for large ones.