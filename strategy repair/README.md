# Strategy repair (KPI intent repair)

A user states a goal for a KPI (for example, "pLTV +20%") together with targets for some of the
metrics that feed it (for example, "p +2%, v +2%"). Those targets often cannot reach the goal, or
cannot do so inside realistic limits on the underlying data. This code finds the scenario that
**meets the KPI goal while staying as close as possible to the user's targets**. It reports which
targets had to be relaxed, which data limits are binding, and whether the result checks out.

## The optimization problem

```
min   Σ_{j ∈ M_U} | ln( m_j(X̂) / m_j(X) ) − ln(1 + t_j) |   +   λ · Σ_i ( ln( x̂_i / s_i ) )²

s.t.  l_i ≤ x̂_i / x_i ≤ u_i            for every data item i
      m_k(X̂) ≥ (1 + G) · m_k(X)         KPI goal (a floor)
```

| Symbol | Meaning | In the code |
|---|---|---|
| `X`, `x_i` | today's data | `data` |
| `X̂`, `x̂_i` | scenario data (decision variables) | `xh` |
| `m_j` | metric formula built from data and/or other metrics using + − × ÷ | `metrics` |
| `k` | the KPI metric | `kpi` |
| `G` | KPI goal as a % change | `goal` |
| `t_j`, `M_U` | user targets and the metrics that have one | `targets` |
| `l_i`, `u_i` | allowed range for each data item, as a multiple of today's value | `bounds`, from `overrides` |
| `λ` | small weight on the second term (default 0.001) | `lam` |
| `s_i` | where the second term measures moves from (default `s_i = x_i`) | `anchor` |

- **First term.** Distance between each targeted metric's change and the user's target, measured
  in logs so that +10% and −10% are treated alike and products become sums.
- **Second term.** Among equally good answers, prefer small data changes spread over several
  items rather than one large change. Moves are measured from `s_i`: today's data by default, or
  pass `anchor` = the data the user's targets imply, so a shortfall is spread from the targets.
  The term counts moves of the *data items*, so what counts as data matters: with nested counts
  (buyers, orders, revenue) a change upstream moves every count below it and costs more; with the
  levers themselves as data (p, o, v) each lever costs the same.
- **Goal as a floor.** A scenario that beats the goal is kept as it is, never cut back to it.
- **Positive values.** Data must stay positive, and every metric that is positive today must
  stay at least 1% of today's value (`positive_share`), so all logs and divisions are defined.
- **Unreachable goal.** If no scenario within the bounds meets the goal, the code first finds
  the highest achievable KPI. It then solves again with the goal set just below that value and
  reports the outcome as `unreachable`.

## Files

| File | Role | Needs Gurobi |
|---|---|---|
| [kpi_inputs.py](kpi_inputs.py) | Example scenarios (data, metrics, targets, bounds). **Run this file.** | via `kpi_repair` |
| [kpi_repair.py](kpi_repair.py) | `repair()`, the entry point: validates inputs, solves, handles an unreachable goal, builds the result dict | yes |
| [kpi_model.py](kpi_model.py) | `build_model()`: writes the problem above as a Gurobi model (does not solve it) | yes |
| [kpi_metrics.py](kpi_metrics.py) | `evaluate()` computes all metrics for given data; `factor_range()` turns a bound setting into `(lo, hi)` | no |
| [kpi_check.py](kpi_check.py) | After solving: `consistency_check()`, `bounds_hit()`, `large_moves()` | no |
| [kpi_report.py](kpi_report.py) | `print_result()` prints a result dict | no |

## How the files work together

```
kpi_inputs.py
   │  repair(data, metrics, kpi, goal, targets, overrides)
   ▼
kpi_repair.py ──────────────────────────────────────────────────────────┐
   1. evaluate(metrics, data)            → today's metric values  m0     │ kpi_metrics.py
   2. factor_range(overrides[i])         → bounds (lo, hi) per item      │
   3. build_model(..., goal value)       → Gurobi model, then optimize   │ kpi_model.py
      └─ no solution? build_model(..., None) maximizes the KPI,          │
         then rebuild with goal = best achievable  → "unreachable"       │
   4. evaluate(metrics, X̂)               → metrics recomputed from X̂     │ kpi_metrics.py
   5. consistency_check / bounds_hit / large_moves                      │ kpi_check.py
   6. return result dict ◄──────────────────────────────────────────────┘
   │
   ▼
kpi_report.py   print_result(title, result)
```

`kpi_model.py` uses `call_metric()` from `kpi_metrics.py`, so the same metric formulas run both
on plain numbers (to get today's values and to check the answer) and on Gurobi variables (to
build the constraints). Step 4 recomputes the metrics from the solver's data with the original
formulas, which is an independent check of what the solver returned.

## Inputs

```python
data    = {"users": 10000, "buyers": 3000, "orders": 5000, "revenue": 500000}
metrics = {"p":    lambda x: x["buyers"] / x["users"],          # fn(x): uses data only
           "o":    lambda x: x["orders"] / x["buyers"],
           "v":    lambda x: x["revenue"] / x["orders"],
           "pLTV": lambda x, m: m["p"] * m["o"] * m["v"]}        # fn(x, m): uses other metrics
repair(data, metrics, kpi="pLTV", goal=0.20, targets={"p": 0.02, "v": 0.02},
       overrides={"users": {"fixed": True}, "orders": {"pct": (-0.10, 0.10)}})
```

Data items without an entry in `overrides` may range from 0.1× to 10× today's value
(`default_factor`). Each entry can take one of these forms:

| Bound setting | Meaning |
|---|---|
| `{"fixed": True}` | the item cannot change |
| `{"pct": (-0.10, 0.10)}` | change between −10% and +10% |
| `{"factor": (0.5, 2.0)}` | between 0.5× and 2× today's value |

Rules: the KPI itself cannot have a target, and today's KPI and every targeted metric must be
positive. A metric that depends on itself, directly or through others, raises an error.

Other `repair()` options: `lam` (weight of the second term), `anchor` (`s_i`), `positive_share`, `flag_move`
(flag any change larger than this, default 50%), and `time_limit` (seconds per solve).

## Output

`repair()` returns a dict:

| Key | Contents |
|---|---|
| `outcome` | `feasible` (all targets met), `relaxed` (some targets moved), `unreachable` (goal lowered to the best achievable), or `error` (with `message`) |
| `proven_optimal` | `True` if Gurobi proved optimality within `time_limit` |
| `kpi_change` | achieved KPI % change |
| `targets` | `{metric: {"target": t, "recommended": achieved}}` |
| `other_metrics` | % change of the metrics that had no target |
| `data` | % change of each data item |
| `bounds_hit` | items that ended at their min or max, and whether that limit was user-set or the default |
| `flags` | items and metrics that moved more than `flag_move` |
| `check` | recomputed metrics vs. solver values, KPI goal error (shortfall below the goal only), bounds respected, plus an overall `ok` |

Format of a `print_result()` printout (values shown as `<…>`):

```
=== <title>
  <OUTCOME> (proven optimal | best found)   KPI <+x.xx%>
   target <metric> <target %> -> <recommended %>  <- relaxed      (one line per target)
   other:  <metric> <change %>  ...
   data:   <item> <change %>  ...
   bound hit: <item> at its max (<+x%>, user | default)
   FLAG: <item or metric> moves <+x%>
   check: OK | FAILED  (metric mismatch <…>, KPI goal error <…>, bounds ok | violated)
```

## Running

```bash
pip install "gurobipy>=14"     # the nonlinear constraints need Gurobi 14 or later (addNLConstr)
python kpi_inputs.py
```

The pip version of Gurobi comes with a size-limited license, which is enough for small examples
like these. To try your own case, add data, metrics, targets and bounds to `kpi_inputs.py` and
call `repair()` and `print_result()` the way the existing examples do.
