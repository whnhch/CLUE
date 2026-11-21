"""
Printing a repair() result.
"""


def print_result(title, r):
    print(f"\n=== {title}")
    if r["outcome"] == "error":
        print("  ", r["message"])
        return
    tag = "proven optimal" if r["proven_optimal"] else "best found"
    print(f"  {r['outcome'].upper()} ({tag})   KPI {r['kpi_change']:+.2%}")
    for j, v in r["targets"].items():
        moved = "  <- relaxed" if abs(v["recommended"] - v["target"]) > 1e-4 else ""
        print(f"   target {j:<5} {v['target']:+.1%} -> {v['recommended']:+.2%}{moved}")
    print("   other:  " + "  ".join(f"{j} {v:+.2%}" for j, v in r["other_metrics"].items()))
    print("   data:   " + "  ".join(f"{i} {v:+.1%}" for i, v in r["data"].items()))
    for h in r["bounds_hit"]:
        print("   bound hit:", h)
    for fl in r["flags"]:
        print("   FLAG:", fl)
    c = r["check"]
    print(f"   check: {'OK' if c['ok'] else 'FAILED'}  (metric mismatch {c['max_metric_mismatch']:.1e}, "
          f"KPI goal error {c['kpi_goal_error']:.1e}, bounds {'ok' if c['bounds_ok'] else 'violated'})")
