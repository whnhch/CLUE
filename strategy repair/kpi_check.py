"""
Post-solve checks and diagnostics on a repaired scenario -- plain Python, no solver.
"""
from __future__ import annotations


def consistency_check(solver_metrics, mvals, kpi, goal_value, xv, data, bounds):
    """
    Solver's metric values vs. recomputation from X^ with the original formulas;
    KPI goal (a floor: only a shortfall counts as error) and bounds verified on the
    recomputed values.
    """
    rel = lambda a, b: abs(a - b) / max(abs(b), 1e-12)
    check = {
        "max_metric_mismatch": max(rel(solver_metrics[j], mvals[j]) for j in mvals),
        "kpi_goal_error": max(0.0, goal_value - mvals[kpi]) / max(abs(goal_value), 1e-12),
        "bounds_ok": all(lo * (1 - 1e-6) <= xv[i] / data[i] <= hi * (1 + 1e-6)
                         for i, (lo, hi) in bounds.items()),
    }
    check["ok"] = (check["max_metric_mismatch"] < 1e-5 and check["kpi_goal_error"] < 1e-5
                   and check["bounds_ok"])
    return check


def bounds_hit(xv, data, bounds, overrides):
    """Data items that ended at their min or max, and whether that bound was user-set."""
    hits = []
    for i, (lo, hi) in bounds.items():
        f = xv[i] / data[i]
        who = "user" if i in overrides else "default"
        if lo < hi and abs(f - hi) < 1e-4:
            hits.append(f"{i} at its max ({hi - 1:+.0%}, {who})")
        elif lo < hi and abs(f - lo) < 1e-4:
            hits.append(f"{i} at its min ({lo - 1:+.0%}, {who})")
    return hits


def large_moves(xv, data, metric_changes, flag_move):
    """Data items and metrics whose change exceeds flag_move in absolute value."""
    data_changes = {i: xv[i] / data[i] - 1 for i in data}
    return [f"{k} moves {v:+.0%}" for k, v in
            list(data_changes.items()) + list(metric_changes.items())
            if abs(v) > flag_move]
