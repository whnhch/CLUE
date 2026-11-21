"""
Metric formulas and data bounds -- plain Python, no solver.

A metric formula may use the data only, fn(x), or data and other metrics, fn(x, m).
Bound specs per data item: {"factor": (lo, hi)}, {"pct": (lo, hi)}, {"fixed": True}.
"""
from __future__ import annotations

import inspect


def call_metric(fn, x, m):
    """A metric formula may use the data only, fn(x), or data and other metrics, fn(x, m)."""
    return fn(x, m) if len(inspect.signature(fn).parameters) >= 2 else fn(x)


def evaluate(metrics, x):
    """Values of all metrics for data x, resolving metrics built from other metrics."""
    busy = set()

    class _M(dict):
        def __missing__(self, j):
            if j in busy:
                raise ValueError(f"Metric '{j}' depends on itself (cycle in definitions).")
            if j not in metrics:
                raise KeyError(f"Unknown metric '{j}'.")
            busy.add(j)
            v = float(call_metric(metrics[j], x, self))
            busy.discard(j)
            self[j] = v
            return v

    m = _M()
    return {j: m[j] for j in metrics}


def factor_range(spec, default):
    """Bound spec for one data item -> (lo, hi) as multiples of today's value."""
    if spec is None:
        return default
    if spec.get("fixed"):
        return (1.0, 1.0)
    if "factor" in spec:
        return tuple(spec["factor"])
    if "pct" in spec:
        return (1 + spec["pct"][0], 1 + spec["pct"][1])
    raise ValueError(f"bad bound spec: {spec}")
