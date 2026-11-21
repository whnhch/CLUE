"""
Example scenarios for KPI repair. Edit the data / metrics / targets / bounds below and run:
    python kpi_inputs.py

Bound overrides per data item: {"factor": (lo, hi)}, {"pct": (lo, hi)}, {"fixed": True}.
"""
from kpi_repair import repair
from kpi_report import print_result

# ------------------------------------------------------------------ funnel
# p = buyers/users, o = orders/buyers, v = revenue/orders, pLTV = p*o*v
FUNNEL_DATA = {"users": 10000, "buyers": 3000, "orders": 5000, "revenue": 500000}
FUNNEL = {"p": lambda x: x["buyers"] / x["users"],
          "o": lambda x: x["orders"] / x["buyers"],
          "v": lambda x: x["revenue"] / x["orders"],
          "pLTV": lambda x, m: m["p"] * m["o"] * m["v"]}
FUNNEL_TARGETS = {"p": 0.02, "v": 0.02}
USERS_FIXED = {"users": {"fixed": True}}

# ------------------------------------------------------------------ mixed KPI with sums
# K = p*o*v + u*o - cac
MIXED_DATA = dict(p=0.30, o=0.50, v=100.0, u=6.0, cac=8.0)
MIXED = {"P": lambda x: x["p"], "O": lambda x: x["o"], "V": lambda x: x["v"],
         "U": lambda x: x["u"], "CAC": lambda x: x["cac"],
         "K": lambda x, m: m["P"] * m["O"] * m["V"] + m["U"] * m["O"] - m["CAC"]}
MIXED_TARGETS = {"P": 0.02, "O": 0.02}
MIXED_BOUNDS = {"p": {"pct": (-.10, .15)}, "o": {"pct": (-.10, .12)}, "v": {"pct": (-.10, .08)},
                "u": {"pct": (-.10, .10)}, "cac": {"pct": (-.15, .10)}}

# ------------------------------------------------------------------ nested
# c = p*o (orders per user) has the target; pLTV = c*v
NESTED = {**{k: FUNNEL[k] for k in ("p", "o", "v")},
          "c": lambda x, m: m["p"] * m["o"],
          "pLTV": lambda x, m: m["c"] * m["v"]}
NESTED_TARGETS = {"c": 0.03, "v": 0.02}


if __name__ == "__main__":
    print_result("funnel, G = +12%",
                 repair(FUNNEL_DATA, FUNNEL, "pLTV", 0.12, FUNNEL_TARGETS, USERS_FIXED))
    print_result("funnel, G = +30%, orders ±10%",
                 repair(FUNNEL_DATA, FUNNEL, "pLTV", 0.30, FUNNEL_TARGETS,
                        {**USERS_FIXED, "orders": {"pct": (-0.10, 0.10)}}))
    print_result("funnel, G = +30%, orders ±10%, revenue ≤ +20%",
                 repair(FUNNEL_DATA, FUNNEL, "pLTV", 0.30, FUNNEL_TARGETS,
                        {**USERS_FIXED, "orders": {"pct": (-0.10, 0.10)},
                         "revenue": {"pct": (-0.20, 0.20)}}))

    for g in (0.20, 0.40, 0.90):
        print_result(f"mixed, G = +{g:.0%}",
                     repair(MIXED_DATA, MIXED, "K", g, MIXED_TARGETS, MIXED_BOUNDS))

    print_result("nested, targets c +3%, v +2%, G = +20%, orders ±10%",
                 repair(FUNNEL_DATA, NESTED, "pLTV", 0.20, NESTED_TARGETS,
                        {**USERS_FIXED, "orders": {"pct": (-0.10, 0.10)}}))
