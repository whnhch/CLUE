"""
Gurobi formulation of the KPI repair problem (builds the model, does not solve it).

    min   sum_{j in M_U} | ln( m_j(X^) / m_j(X) ) - ln(1 + t_j) |  +  lam * sum_i ( ln( x^_i / s_i ) )^2

    s.t.  l_i <= x^_i / x_i <= u_i          for every data item i
          m_k(X^) >= (1 + G) * m_k(X)       KPI goal (a floor)

    s_i = anchor of the second term (default s_i = x_i, today's data)

Requires gurobipy >= 14.
"""
from __future__ import annotations

import math

import gurobipy as gp
from gurobipy import GRB, nlfunc

from kpi_metrics import call_metric


def _eq(md, y, expr):
    """y == expr, as a non-linear constraint when needed."""
    e = expr - y
    if isinstance(e, gp.NLExpr):
        md.addNLConstr(e, GRB.EQUAL, 0.0)
    else:
        md.addConstr(e == 0)


def build_model(data, metrics, kpi, targets, bounds, m0, kpi_value,
                lam=1e-3, positive_share=0.01, time_limit=30, anchor=None):
    """
    data:      {item: today's value}                 X
    metrics:   {name: fn(x) or fn(x, m)}             metric formulas (KPI included)
    kpi:       name of the KPI metric
    targets:   {metric: target % change}             t_j for j in M_U
    bounds:    {item: (lo, hi)} factors              l_i, u_i
    m0:        today's metric values                 m_j(X)
    kpi_value: minimum KPI value, or None to build the "maximise the KPI" model
               (used only to find the best achievable KPI)
    anchor:    {item: value} the second term measures moves from      s_i
               (default: data, i.e. s_i = x_i)

    Returns (model, data variables x^, metric variables m).
    """
    md = gp.Model()
    md.Params.OutputFlag = 0
    md.Params.TimeLimit = time_limit
    md.Params.MIPGap = 0
    # The second term is ~1e-5 at the optimum, near Gurobi's default tolerances (1e-6); at the
    # defaults, "proven optimal" answers can be far from optimal on that term. (1e-9 is too
    # tight: it reports the unreachable-goal re-solve as infeasible.)
    md.Params.FeasibilityTol = 1e-8
    md.Params.OptimalityTol = 1e-8
    xh = {i: md.addVar(lb=data[i] * lo, ub=data[i] * hi, name=f"x_{i}")
          for i, (lo, hi) in bounds.items()}
    mv = {}
    for j in metrics:                                                   # positivity assumption for positive metrics
        lb = positive_share * m0[j] if m0[j] > 0 else -GRB.INFINITY
        mv[j] = md.addVar(lb=lb, ub=GRB.INFINITY, name=f"m_{j}")
    for j, fn in metrics.items():
        _eq(md, mv[j], call_metric(fn, xh, mv))
    if kpi_value is None:
        md.setObjective(mv[kpi], GRB.MAXIMIZE)
        return md, xh, mv
    
    md.addConstr(mv[kpi] >= kpi_value, name="goal") # KPI goal constraint  m_k(X^) >= (1 + G) * m_k(X)  (exceeding it is fine)
    
    ##############################################
    # First objective term related constraints:
    # Add variables and constraints for the absolute values |ln(m_j(X^)) - ln(T_j)| for each target metric m_j
    ##############################################
    
    dev = []
    for j, t in targets.items():                                # metric m_j and its target t_j:  | ln(m_j(X^)/m_j(X)) - ln(1 + t_j) | 
        lj = md.addVar(lb=-GRB.INFINITY, name=f"ln_{j}")        # Make a variable a lj for ln(m_j(X^))
        md.addNLConstr(lj - nlfunc.log(mv[j]), GRB.EQUAL, 0.0)  # Add constraint: l_j = ln(m_j(X^))  (non-linear)
        ref = math.log(m0[j]) + math.log(1 + t)                 # Target reference: ln(m_j(X)) + ln(1 + t_j) = ln(T_j)
        a = md.addVar(name=f"dev_{j}")                          # Add variable a for the absolute deviation |ln(m_j(X^)) - ln(T_j)|
        md.addConstr(a >= lj - ref)                             # a ≥  (ln m_j − ln T_j)  
        md.addConstr(a >= ref - lj)                             # a ≥ −(ln m_j − ln T_j)   → with a minimised: a = |ln m_j − ln T_j|
        dev.append(a)                                           
    
    ##############################################
    # Second objective term related constraints:
    # Add variables and constraints for the quadratic regularization term lam * sum_i ( ln(x^_i / s_i) )^2
    ##############################################
    anchor = anchor or data
    moves = []
    for i, (lo, hi) in bounds.items():        # ( ln(x^_i / s_i) )^2  quadratic regularisation
        if lo == hi:
            continue                          # fixed item: never moves
        s = anchor[i]                         # s_i: where the move is measured from
        li = md.addVar(lb=math.log(lo * data[i] / s), ub=math.log(hi * data[i] / s), name=f"lnx_{i}")
        md.addNLConstr(li - nlfunc.log(xh[i] / s), GRB.EQUAL, 0.0) # Add constraint: l_i = ln(x^_i / s_i)  (non-linear)
        moves.append(li * li)

    # Objective: sum_{j in M_U} |ln m_j(X^) - ln T_j|  +  lam * sum_i ( ln(x^_i / s_i) )^2
    md.setObjective(gp.quicksum(dev) + lam * gp.quicksum(moves), GRB.MINIMIZE)
    
    return md, xh, mv
