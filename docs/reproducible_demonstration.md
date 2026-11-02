# TECH5 Assignment Support System: Reproducible Demonstration Walkthrough

## 1. Demonstration Overview

This guide provides instructors, evaluators, and students with an exact, reproducible walkthrough of the **Student-to-Project Assignment Decision Support System**. It exercises all core functional capabilities across the four benchmark cohorts pre-configured in the platform.

### Quick Start
1. Activate the virtual environment and install dependencies:
   ```powershell
   # Windows
   .\.venv\Scripts\activate
   ```
   ```bash
   # macOS / Linux
   source .venv/bin/activate
   ```
   Then, on any OS:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the integrated application:
   ```powershell
   python run.py
   ```
3. Open your browser to: **`http://127.0.0.1:5000`**

---

## 2. Scenario 1: Standard Cohort (Trade-Off Benchmark)

### 2.1 Scenario Objective
Demonstrates multi-objective Pareto alternatives, distinct solutions generation via no-good integer cuts, and comparative trade-off analysis between student preference satisfaction and project skill fit.

### 2.2 Cohort Composition
- **Students**: 10 students (`S01` to `S10`) with complementary competencies across Python, SQL, Machine Learning, Web Dev, and FinTech.
- **Projects**: 4 projects (`P1`: FinTech, `P2`: Data Lakehouse, `P3`: Healthcare ML, `P4`: Full-Stack Web) with capacity bounds $[1, 3]$ each (Total Capacity = 12 $\ge 10$ students).
- **Constraints**: No fixed pre-allocations initially.

### 2.3 Step-by-Step Execution (Web Interface)
1. In the top navigation, click **Dashboard** or **Scenarios**.
2. Click the green button **"Load Scenario"** under **Standard Trade-Off Benchmark**.
3. A success notification will confirm the cohort is loaded into SQLite (10 students, 4 projects, 5 skills).
4. In the **Optimization Run Trigger Panel**:
   - Strategy: `Student Preference Maximization (Minimize Rank Regret)`
   - Distinct Alternatives: `3 Distinct Solutions`
   - Click **"Launch Optimization Run"**.
5. You are redirected to `/runs/{run_id}`:
   - Notice that **3 distinct solutions** have been computed and persisted.
   - **Alternative 1 (Preference-Oriented)**:
     - Mean Skill Fit: ~`82.5%`
     - Mean Preference Rank: ~`1.20` (8 students get 1st choice, 2 get 2nd choice)
     - Worst Rank: `2`
     - Gini Inequality: `0.167`
   - **Alternative 2 (Skill-Fit Oriented)**:
     - Mean Skill Fit increases to ~`92.5%`
     - Mean Preference Rank adjusts to ~`1.50`
   - **Alternative 3 (Balanced Trade-Off)**:
     - Provides an egalitarian compromise between skill fit and preference satisfaction.

### 2.4 Side-by-Side Solution Comparison
1. In the top navigation, click **Compare**.
2. Select:
   - Solution A: `Alternative 1 (PREFERENCE)`
   - Solution B: `Alternative 2 (SKILL_FIT)`
   - Click **"Compare Solutions"**.
3. The comparison dashboard displays:
   - **Delta Metrics**: Visual indicator badges displaying $\Delta$ Mean Skill Fit (+10.0%), $\Delta$ Mean Rank (+0.30), and $\Delta$ Gini.
   - **Re-Allocation Table**: Highlights the exact students who moved projects, along with their individual rank change ($\Delta Rank$).

### 2.5 Inspecting Decision-Support Recommendations
1. Navigate into any generated solution (e.g. `/solutions/{solution_id}`).
2. The **Decision Support & Recommendations Panel** presents three inspectable recommendations:
   - **Student Preference Maximization**: Identifies the alternative with lowest average rank and minimum regret, supported by exact calculated metrics.
   - **Project Skill Quality Assurance**: Identifies the alternative with maximum skill fit and minimum unmet soft requirements.
   - **Balanced Egalitarian Compromise**: Identifies the alternative minimizing the rank Gini coefficient and rank variance.
3. Each recommendation explicitly details the **criteria evaluated**, the **calculated evidence**, and the **administrative policy advice**, distinguishing objective facts from normative guidance.

### 2.6 Headless In-Process Contract Execution (Python)
The Assignment Engine can be invoked directly in Python without starting the web server, demonstrating contract independence:
```python
from app.contract import contract
from app.engine import solvers
from app.samples import demo_data

# Initialize the engine (implements contract.AssignmentEngineContract)
scenario = demo_data.get_standard_scenario()
engine = solvers.AssignmentEngine()
request = contract.RunRequest(
    students=scenario["students"],
    projects=scenario["projects"],
    skills=scenario["skills"],
    strategy_key="PREFERENCE",
    max_alternatives=3,
)
outcome = engine.execute_run(request)
print(f"Status: {outcome.status}")
print(f"Solutions generated: {len(outcome.solutions)}")
for sol in outcome.solutions:
    print(f"Alt {sol.alternative_number} ({sol.strategy_name}): "
          f"Mean Rank={sol.indicators['fairness']['mean_rank']}, "
          f"Mean Skill Fit={sol.indicators['efficiency']['mean_skill_fit']:.2f}")
```

---

## 3. Scenario 2: Fixed Assignment & Ripple Effect Analysis

### 3.1 Scenario Objective
Demonstrates administrative pre-allocation locks ($x_{s^*, p^*} = 1$), strict constraint preservation, and the resulting ripple effect on peer assignments.

### 3.2 Cohort Composition
- Base standard cohort with student **`S02` (Bob Smith)** locked to project **`P2` (Cloud Data Pipeline)** under an approved research grant, even though Bob's #1 preference is `P1`.

### 3.3 Step-by-Step Execution
1. Navigate to **Scenarios** and click **Load Scenario** under **Fixed Assignment Scenario**.
2. In the top navigation, click **Fixed Locks**.
   - Notice `S02` $\to$ `P2` is listed with status `APPROVED` and justification noted.
3. Return to **Dashboard** and click **"Launch Optimization Run"**.
4. Inspect the generated solution:
   - In Solution 1, student `S02` is strictly assigned to `P2` (`Fixed: YES` badge).
   - Because `P2` now has 1 fewer open seat, observe how student `S03` or `S07` is re-routed to their 2nd preference.
5. In the solution view, use the **"Lock Student"** dropdown to interactively pin another student (e.g. `S01` to `P1`) and click **"Save Lock & Re-run Optimization"** to witness real-time interactive re-solving!

---

## 4. Scenario 3: Capacity Deficit (Mathematical Infeasibility)

### 4.1 Scenario Objective
Validates that the system rigorously detects structural infeasibility when total project capacity is strictly less than cohort size ($\sum u_p < |S|$), halting before solver failure and providing clear diagnostic guidance.

### 4.2 Cohort Composition
- **Students**: 10 students.
- **Projects**: Capacities reduced to 2, 2, 1, 1 (Total Capacity = 6 seats for 10 students).

### 4.3 Step-by-Step Execution
1. Navigate to **Scenarios** and click **Load Scenario** under **Capacity Deficit Scenario**.
2. On the Dashboard KPI cards:
   - Student Cohort: `10`
   - Total Max Capacity: `6`
   - Red Warning: `⚠️ Deficit: 4 unassignable students`
3. Click **"Launch Optimization Run"**.
4. The system immediately catches the mathematical violation:
   - Run Status: `INFEASIBLE`
   - Diagnostic Banner:
     ```
     Insufficient overall capacity: total cohort size (10) exceeds aggregate maximum project capacity (6).
     ```
   - Zero solutions are created, and helpful remediation advice is displayed (e.g. increase project capacities or enable partial allocations).

---

## 5. Scenario 4: Contradictory Fixed Constraints

### 5.1 Scenario Objective
Verifies domain validation and relational integrity rejection when an administrator attempts to lock more students to a project than its maximum capacity ($|F_p| > u_p$).

### 5.2 Cohort Composition
- Project `P1` has a maximum capacity of 3 students.
- 4 students (`S01`, `S02`, `S05`, `S08`) are locked to `P1`.

### 5.3 Step-by-Step Execution
1. Navigate to **Scenarios** and click **Load Scenario** under **Contradictory Fixed Assignments Scenario**.
2. Attempt to trigger an optimization run.
3. The platform displays a clear validation error:
   ```
   Fixed assignments (4) for project 'P1' exceed its maximum capacity (3).
   ```
4. Optimization is safely blocked, protecting database integrity.