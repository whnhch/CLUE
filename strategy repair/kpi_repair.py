"""
KPI intent repair.

    min   sum_{j in M_U} | ln( m_j(X^) / m_j(X) ) - ln(1 + t_j) |  +  lam * sum_i ( ln( x^_i / s_i ) )^2

    s.t.  l_i <= x^_i / x_i <= u_i          for every data item i
          m_k(X^) >= (1 + G) * m_k(X)       KPI goal (a floor: exceeding it is fine)

    X  = today's data (given),  X^ = scenario data (decision variables)
    m_j = metric j, a formula of the data and/or earlier metrics (+, -, *, /)
    t_j = user's target % change for metric j in M_U,  G = KPI goal % change
    lam = small weight (default 0.001) on the quadratic regularisation term: among equally good
          answers, prefer small data changes spread over several items
    s_i = anchor the regularisation measures moves from (`anchor`; default s_i = x_i). Pass the
          data the user's targets imply to spread a shortfall from the targets, not from today

Handled in the code, as stated in the paper's text:
  * positivity: data stay positive (bounds), and every metric that is positive today
    stays positive (>= 1% of today), so all logs and divisions are defined
  * unreachable goal: if no X^ meets the goal within the bounds, the goal is replaced by
    the best achievable KPI value and the problem is solved again

Files, by role:
  kpi_repair.py   this file: repair() -- validate inputs, solve, fallback, assemble result
  kpi_metrics.py  metric evaluation and bound specs (plain Python)
  kpi_model.py    Gurobi model formulation
  kpi_check.py    post-solve consistency check, bounds hit, large-move flags
  kpi_report.py   print_result()
  kpi_inputs.py   example scenarios (run this file)

Requires gurobipy >= 14. Bound overrides: {"factor": (lo, hi)}, {"pct": (lo, hi)}, {"fixed": True}.
"""
from __future__ import annotations

from gurobipy import GRB

from kpi_check import bounds_hit, consistency_check, large_moves
from kpi_metrics import evaluate, factor_range
from kpi_model import build_model


def repair(data: dict, metrics: dict, kpi: str, goal: float, targets: dict,
           overrides: dict | None = None, default_factor=(0.1, 10.0),
           lam: float = 1e-3, positive_share: float = 0.01, flag_move: float = 0.5,
           time_limit: float = 30, anchor: dict | None = None) -> dict:
    """
    data:      {item: today's value}                 X
    metrics:   {name: fn(x) or fn(x, m)}             metric formulas (KPI included)
    kpi:       name of the KPI metric                kappa
    goal:      KPI % change, e.g. 0.20               G
    targets:   {metric: target % change}             t_j for j in M_U
    overrides: {data item: bound spec}               l_i, u_i (default 0.1x .. 10x)
    anchor:    {data item: value}                    s_i (default: data); missing items use data
    """
    overrides = overrides or {}
    if kpi in targets:
        raise ValueError("The KPI cannot also have a user target.")
    m0 = evaluate(metrics, data)
    if m0[kpi] <= 0:
        raise ValueError("Today's KPI must be positive.")
    for j in targets:
        if m0[j] <= 0:
            raise ValueError(f"Metric '{j}' must be positive today to take a target.")
    bounds = {i: factor_range(overrides.get(i), default_factor) for i in data}
    anchor = {**data, **(anchor or {})}
    if any(anchor[i] <= 0 for i in data):
        raise ValueError("Anchor values must be positive.")

    def build(kpi_value):
        return build_model(data, metrics, kpi, targets, bounds, m0, kpi_value,
                           lam=lam, positive_share=positive_share, time_limit=time_limit,
                           anchor=anchor)

    goal_value = (1 + goal) * m0[kpi]
    md, xh, mvar = build(goal_value)
    md.optimize()
    outcome = None
    if md.SolCount == 0:
        mx, _, _ = build(None)                # best achievable KPI within the bounds
        mx.optimize()
        if mx.SolCount == 0:
            return {"outcome": "error", "message": "No scenario satisfies the bounds."}
        best = mx.ObjVal
        # small margin below the maximum: the maximum itself can sit on the solver's
        # feasibility tolerance, and an exact equality there forces odd solutions
        goal_value = best * (1 - 1e-5)
        md, xh, mvar = build(goal_value)
        md.optimize()
        if md.SolCount == 0:
            return {"outcome": "error", "message": "Solver failed at the best achievable KPI."}
        outcome = "unreachable"

    xv = {i: xh[i].X for i in data}
    mvals = evaluate(metrics, xv)             # metrics recomputed from X^ with the original formulas
    check = consistency_check({j: mvar[j].X for j in metrics}, mvals, kpi, goal_value,
                              xv, data, bounds)
    ch = {j: mvals[j] / m0[j] - 1 for j in metrics}
    if outcome is None:
        outcome = ("feasible" if all(abs(ch[j] - t) < 1e-4 for j, t in targets.items())
                   else "relaxed")

    return {
        "outcome": outcome,
        "proven_optimal": md.Status == GRB.OPTIMAL,
        "kpi_change": ch[kpi],
        "targets": {j: {"target": t, "recommended": ch[j]} for j, t in targets.items()},
        "other_metrics": {j: ch[j] for j in metrics if j not in targets and j != kpi},
        "data": {i: xv[i] / data[i] - 1 for i in data},
        "bounds_hit": bounds_hit(xv, data, bounds, overrides),
        "flags": large_moves(xv, data, ch, flag_move),
        "check": check,
    }
