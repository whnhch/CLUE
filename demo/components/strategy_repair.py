"""
strategy_repair.py
------------------
Connects the KPI strategy-repair solver (``../strategy repair/``) to the CLUE
simulator.

The simulator already has the shape the solver expects:

    KPI      90-Day Customer Value = conversion x orders per customer x AOV
    goal G   the planning uplift (% above the historical baseline)
    targets  the three sliders, read as % changes from the baseline

The sliders move freely, so a scenario can land below the goal. Repair finds
the scenario that **meets the goal while staying as close as possible to the
slider values**, and says which assumptions had to move. The panel re-solves
whenever a slider, the goal, or the "Keep close to" choice changes.

The mapping to the solver's inputs (see ``strategy repair/README.md``):

    data X     the three factors themselves -- the levers the sliders move
    metrics    conversion_rate, orders_per_purchasing_customer,
               average_order_value (each equal to its data item) and
               customer_value, the KPI; named after the Scenario attributes so
               the result maps straight back to one
    bounds     conversion at most 100%; otherwise the solver's 0.1x-10x default

Why the factors, not the four counts, are the data: with counts as data the
solver's tie-break term (smallest data changes) counts how many *counts* move.
Raising AOV moves one count (gross value), raising conversion moves three, so
every shortfall was filled by AOV whatever the sliders said, and every
relaxation looked alike. With the factors as data the shortfall is shared
across the assumptions, favouring those the participant has not already
pushed. (Orders also cancel out of the KPI in the count formulation, which
left them free to take arbitrary values when not targeted.)

The counts are not lost: a Scenario still propagates purchasing customers,
orders and gross value from the repaired factors on the future cohort.

One departure from the paper, on by default (``anchor="sliders"``): the
tie-break term measures moves from the slider values instead of from the
baseline. The first term is indifferent to how a shortfall is split among the
targets, so a baseline-anchored tie-break picks the same balanced point near
the baseline whatever the sliders say. Anchored at the sliders, the shortfall
is spread evenly from where the participant put them. ``anchor="baseline"``
restores the paper's version exactly.

Two layers in one file:

  * ``suggest_repair()`` -- plain inputs in, ``RepairSuggestion`` out. Needs
    gurobipy >= 14 but no Streamlit session.
  * ``render_strategy_repair(baseline)`` -- the simulator panel: repairs the
    current sliders and goal live, and offers "Apply to sliders" and "Pin".

gurobipy is imported only when a repair runs, so the app still starts without
it; the panel then reports that it is missing.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

import streamlit as st

from data.metrics import BaselineMetrics, money, percent
from data.scenario import Scenario, goal_value
from .styles import (
    CARD_DIVIDER,
    CARD_MUTED_TEXT,
    CARD_RULE,
    GOAL_MET_BG,
    GOAL_MET_TEXT,
    GOAL_MISSED_BG,
    GOAL_MISSED_TEXT,
)
from utils.slider_calculations import (
    CONVERSION_KEY,
    MAX_RAIL_CARDS,
    ORDER_VALUE_KEY,
    ORDERS_KEY,
    can_pin,
    current_scenario,
    next_scenario_name,
    pin_scenario,
    slider_bounds,
    uplift_percent,
)

# The solver lives outside the demo package, in a folder whose name has a
# space, so it is put on sys.path rather than imported as a package.
REPAIR_DIR = Path(__file__).resolve().parents[2] / "strategy repair"

# ---------------------------------------------------------------------------
# Problem definition
# ---------------------------------------------------------------------------

KPI = "customer_value"
FACTORS = (
    "conversion_rate",
    "orders_per_purchasing_customer",
    "average_order_value",
)
FACTOR_LABELS = {
    "conversion_rate": "90-Day Purchase Conversion Rate",
    "orders_per_purchasing_customer": "Orders per Purchasing Customer",
    "average_order_value": "Average Order Value",
}
FACTOR_FORMAT = {
    "conversion_rate": percent,
    "orders_per_purchasing_customer": lambda v: f"{v:,.2f}",
    "average_order_value": money,
}

# Data items carry the display label, so the solver's "bound hit" messages
# read naturally in the panel.
DATA_KEY = FACTOR_LABELS

METRICS = {
    **{f: (lambda key: lambda x: x[key])(DATA_KEY[f]) for f in FACTORS},
    KPI: lambda x, m: (
        m["conversion_rate"]
        * m["orders_per_purchasing_customer"]
        * m["average_order_value"]
    ),
}

# Solver default range for data items without an explicit bound (matches
# repair()'s own default).
DEFAULT_FACTOR = (0.1, 10.0)

# Relative slack when deciding a scenario already meets the goal, so values
# applied from a repair (which sit exactly on the goal) are not re-solved.
GOAL_TOLERANCE = 1e-6


@dataclass(frozen=True)
class RepairSuggestion:
    """
    The outcome of one repair, mapped back to the simulator's terms.

    outcome:  feasible | relaxed | unreachable | error
    scenario: the repaired assumptions as a Scenario (None on error)
    targets:  {factor: (assumption as set, suggested value)} for each factor
              the solver was asked to stay close to
    result:   the raw dict repair() returned, for anything not surfaced here
    """

    outcome: str
    message: str = ""
    scenario: Scenario | None = None
    kpi_change: float = 0.0
    targets: dict = field(default_factory=dict)
    unchanged: bool = False   # the sliders already meet the goal; nothing solved
    bounds_hit: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    result: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.outcome != "error"


def _range(spec: dict | None) -> tuple[float, float]:
    """A bound spec -> (lo, hi) as multiples of the *baseline* value."""
    if spec is None:
        return DEFAULT_FACTOR
    if spec.get("fixed"):
        return (1.0, 1.0)
    if "factor" in spec:
        return tuple(spec["factor"])
    if "pct" in spec:
        return (1 + spec["pct"][0], 1 + spec["pct"][1])
    raise ValueError(f"bad bound spec: {spec}")


def default_overrides(baseline: BaselineMetrics) -> dict[str, dict]:
    """
    Bound specs per factor, relative to the baseline: conversion can never
    exceed 100%; the others use the default 0.1x-10x range.
    """
    lo, hi = DEFAULT_FACTOR
    return {"conversion_rate": {"factor": (lo, min(hi, 1.0 / baseline.conversion_rate))}}


def _import_repair():
    if str(REPAIR_DIR) not in sys.path:
        sys.path.insert(0, str(REPAIR_DIR))
    from kpi_repair import repair  # noqa: E402  (needs gurobipy >= 14)

    return repair


@lru_cache(maxsize=64)
def _solve(
    data_items: tuple,
    targets_items: tuple,
    goal: float,
    overrides_items: tuple,
    lam: float,
    time_limit: float,
) -> dict:
    """repair() on hashable inputs, cached so a rerun does not re-solve."""
    repair = _import_repair()
    overrides = {item: dict(spec) for item, spec in overrides_items}
    return repair(
        dict(data_items),
        METRICS,
        KPI,
        goal,
        dict(targets_items),
        overrides,
        default_factor=DEFAULT_FACTOR,
        lam=lam,
        time_limit=time_limit,
    )


def suggest_repair(
    baseline: BaselineMetrics,
    assumptions: Scenario,
    uplift: float,
    keep_close: tuple[str, ...] = FACTORS,
    overrides: dict[str, dict] | None = None,
    anchor: str = "sliders",
    lam: float | None = None,
    flag_move: float = 0.5,
    time_limit: float = 10,
) -> RepairSuggestion:
    """
    The scenario that meets the goal and stays closest to ``assumptions``.

    baseline:    observed history (today's metric values)
    assumptions: the slider values, as a Scenario
    uplift:      planning goal, in % above the baseline (e.g. 15 for +15%)
    keep_close:  which factors count as user targets; the others are free
    overrides:   {factor: bound spec}, relative to the baseline
                 (defaults: default_overrides)
    anchor:      where the tie-break term measures moves from.
                 "sliders" -- the slider values. The solver is handed the
                   sliders as X, with t_j = 0 and the goal rescaled, so the
                   first term is unchanged (|ln m_j(X^) - ln T_j|) but the
                   shortfall is spread evenly, in log terms, from where the
                   sliders are. The suggestion follows the sliders.
                 "baseline" -- today's values, exactly as in the paper. The
                   first term is indifferent to how the shortfall is split, so
                   the tie-break picks one balanced point near the baseline
                   and suggestions cluster there whatever the sliders say.
    lam:         tie-break weight. Defaults to 0.1 when anchored at the
                 sliders (both terms then pull toward the sliders, so a larger
                 weight changes nothing but makes the tie-break register above
                 the solver's tolerances), and to the paper's 0.001 otherwise.
    flag_move:   flag factors that end more than this far from the baseline
    """
    goal_value = baseline.customer_value * (1 + uplift / 100.0)

    # The goal is a floor (here, in data/scenario.py, and in the solver), so a
    # scenario at or above it is already the answer; returned without a solve.
    if assumptions.customer_value >= goal_value * (1 - GOAL_TOLERANCE):
        return RepairSuggestion(
            outcome="feasible",
            unchanged=True,
            message="The assumptions already meet the goal; nothing to repair.",
            scenario=assumptions,
            kpi_change=assumptions.customer_value / baseline.customer_value - 1,
            targets={f: (getattr(assumptions, f),) * 2 for f in keep_close},
        )

    if anchor not in ("sliders", "baseline"):
        raise ValueError(f"anchor must be 'sliders' or 'baseline', not {anchor!r}")
    if lam is None:
        lam = 0.1 if anchor == "sliders" else 1e-3
    base = {f: float(getattr(baseline, f)) for f in FACTORS}
    wanted = {f: float(getattr(assumptions, f)) for f in FACTORS}
    # X handed to the solver. A slider at zero cannot anchor a log, so that
    # factor falls back to its baseline value.
    start = {f: (wanted[f] if anchor == "sliders" and wanted[f] > 0 else base[f])
             for f in FACTORS}

    # ln(1 + t) needs a positive target; a factor dragged to zero cannot be a
    # target, so it is left free rather than failing the whole repair.
    targets = {f: wanted[f] / start[f] - 1 for f in keep_close if wanted[f] > 0}

    # Bounds stay relative to the baseline, whatever X is.
    specs = default_overrides(baseline) if overrides is None else overrides
    ranges = {f: _range(specs.get(f)) for f in FACTORS}
    solver_bounds = tuple(sorted(
        (DATA_KEY[f], (("factor", (lo * base[f] / start[f], hi * base[f] / start[f])),))
        for f, (lo, hi) in ranges.items()
    ))
    start_kpi = (start["conversion_rate"] * start["orders_per_purchasing_customer"]
                 * start["average_order_value"])

    try:
        result = _solve(
            tuple(sorted((DATA_KEY[f], v) for f, v in start.items())),
            tuple(sorted((f, round(t, 12)) for f, t in targets.items())),
            goal_value / start_kpi - 1,
            solver_bounds,
            float(lam),
            float(time_limit),
        )
    except ImportError as exc:
        return RepairSuggestion(
            "error",
            f"Strategy repair needs gurobipy >= 14 (pip install \"gurobipy>=14\"). ({exc})",
        )
    except Exception as exc:  # solver/licence errors surface in the panel
        return RepairSuggestion("error", f"Repair failed: {exc}")

    if result.get("outcome") == "error":
        return RepairSuggestion("error", result.get("message", "Repair failed."), result=result)

    changes = {**result["other_metrics"],
               **{j: v["recommended"] for j, v in result["targets"].items()}}
    values = {f: start[f] * (1 + changes[f]) for f in FACTORS}
    scenario = Scenario(
        conversion_rate=values["conversion_rate"],
        orders_per_purchasing_customer=values["orders_per_purchasing_customer"],
        average_order_value=values["average_order_value"],
        acquired_users=assumptions.acquired_users,
    )

    # Limits and large moves, stated against the baseline (the solver's own
    # messages are relative to X, which may be the sliders).
    hits, flags = [], []
    for f, (lo, hi) in ranges.items():
        ratio = values[f] / base[f]
        who = "user" if overrides is not None and f in overrides else "default"
        if lo < hi and abs(ratio - hi) < 1e-4 * hi:
            hits.append(f"{FACTOR_LABELS[f]} at its max ({hi - 1:+.0%} vs baseline, {who})")
        elif lo < hi and abs(ratio - lo) < 1e-4 * lo:
            hits.append(f"{FACTOR_LABELS[f]} at its min ({lo - 1:+.0%} vs baseline, {who})")
        if abs(ratio - 1) > flag_move:
            flags.append(f"{FACTOR_LABELS[f]} moves {ratio - 1:+.0%} from the baseline")

    return RepairSuggestion(
        outcome=result["outcome"],
        scenario=scenario,
        kpi_change=scenario.customer_value / baseline.customer_value - 1,
        targets={f: (wanted[f], values[f]) for f in targets},
        bounds_hit=hits,
        flags=flags,
        result=result,
    )


# ---------------------------------------------------------------------------
# Streamlit panel
# ---------------------------------------------------------------------------

KEEP_CLOSE_KEY = "sim_repair_keep_close"

OUTCOME_TEXT = {
    "unchanged": ("met", "✓ Your assumptions already reach the goal"),
    "feasible": ("met", "Goal reached by moving only the flexible assumptions"),
    "relaxed": ("met", "To reach the goal: {moves}"),
    "unreachable": ("missed", "Goal out of reach — this is the most these limits allow"),
    "error": ("missed", "Repair failed"),
}

# Short names for the picker chips; the table keeps the full metric names.
SHORT_LABELS = {
    "conversion_rate": "Conversion rate",
    "orders_per_purchasing_customer": "Orders per customer",
    "average_order_value": "Avg order value",
}

# Matched to the simulator's own type scale (components/styles.py): 12.5-13.5px
# body text, 11px labels, 10.5px pills.
PANEL_CSS = f"""
<style>
.st-key-card_sim_repair [data-testid="stCaptionContainer"] p,
.st-key-card_sim_repair [data-testid="stCaptionContainer"] {{
    font-size: 12px !important;
    line-height: 1.45 !important;
}}
.st-key-card_sim_repair [data-testid="stWidgetLabel"] p {{
    font-size: 12.5px !important;
    font-weight: 600;
    color: {CARD_MUTED_TEXT};
}}
.st-key-card_sim_repair [data-baseweb="select"] > div {{
    min-height: 34px;
    font-size: 12.5px;
}}
.st-key-card_sim_repair [data-baseweb="tag"],
.st-key-card_sim_repair [data-baseweb="tag"] span {{
    font-size: 12px !important;
}}
.st-key-card_sim_repair [data-baseweb="tag"] {{
    height: 24px !important;
    margin-top: 2px !important;
    margin-bottom: 2px !important;
}}
.st-key-card_sim_repair div.stButton > button p {{
    font-size: 13px;
}}
.clue-repair-head {{
    font-size: 13.5px;
    line-height: 1.6;
    color: #2F3E7C;
}}
.clue-repair-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
    margin: 4px 0 2px 0;
}}
.clue-repair-table th {{
    font-size: 11px;
    font-weight: 600;
    color: {CARD_MUTED_TEXT};
    text-align: right;
    padding: 4px 10px;
    border-bottom: 1px solid {CARD_DIVIDER};
    white-space: nowrap;
}}
.clue-repair-table td {{
    text-align: right;
    padding: 5px 10px;
    border-bottom: 1px solid {CARD_RULE};
    color: #2F3E7C;
    white-space: nowrap;
}}
.clue-repair-table th:first-child,
.clue-repair-table td:first-child {{
    text-align: left;
    white-space: normal;
}}
.clue-repair-table td.is-suggested {{
    font-weight: 700;
}}
.clue-repair-note {{
    display: inline-block;
    font-size: 10.5px;
    font-weight: 600;
    padding: 1px 8px;
    border-radius: 999px;
}}
.clue-repair-note.raised,
.clue-repair-note.lowered {{ background: {GOAL_MISSED_BG}; color: {GOAL_MISSED_TEXT}; }}
.clue-repair-note.as-set {{ background: {GOAL_MET_BG}; color: {GOAL_MET_TEXT}; }}
.clue-repair-note.flexible {{ background: {CARD_RULE}; color: {CARD_MUTED_TEXT}; }}
</style>
"""


def _is_kept(suggestion: RepairSuggestion, factor: str, value: float) -> bool:
    if factor not in suggestion.targets:
        return False
    wanted = suggestion.targets[factor][0]
    return bool(wanted) and abs(value / wanted - 1) <= 1e-4


def _snap_to_sliders(baseline: BaselineMetrics, suggestion: RepairSuggestion,
                     goal: float) -> RepairSuggestion:
    """
    Put the suggestion on the sliders' step grid, still meeting the goal.

    The browser snaps a slider to its step (39.06% -> 39.0%), so an applied
    suggestion sitting exactly on the goal landed just below it. Kept
    assumptions stay exactly as set; the other ones are rounded to their step,
    and the remainder goes to one of them -- AOV first, the finest step --
    rounded *up*, so the result meets the goal on the grid.
    """
    s = suggestion.scenario
    bounds = slider_bounds(baseline)
    grid = {  # factor: (step, max) in the factor's own units
        "conversion_rate": (bounds[CONVERSION_KEY][2] / 100, bounds[CONVERSION_KEY][1] / 100),
        "orders_per_purchasing_customer": (bounds[ORDERS_KEY][2], bounds[ORDERS_KEY][1]),
        "average_order_value": (bounds[ORDER_VALUE_KEY][2], bounds[ORDER_VALUE_KEY][1]),
    }
    values = {f: getattr(s, f) for f in FACTORS}
    movable = [f for f in FACTORS if not _is_kept(suggestion, f, values[f])]
    if not movable:
        return suggestion

    def on_grid(f, x, how=round):
        step, top = grid[f]
        return min(round(how(x / step - 1e-9 if how is math.ceil else x / step) * step, 10), top)

    for f in movable:
        values[f] = on_grid(f, values[f])
    if suggestion.outcome != "unreachable":
        product = lambda: values["conversion_rate"] * values["orders_per_purchasing_customer"] \
            * values["average_order_value"]
        absorber = next(f for f in ("average_order_value", "orders_per_purchasing_customer",
                                    "conversion_rate") if f in movable)
        rest = product() / values[absorber]
        values[absorber] = on_grid(absorber, goal / rest, math.ceil)
        for f in movable:                    # absorber capped at its slider max
            if product() >= goal:
                break
            values[f] = on_grid(f, values[f] + grid[f][0] / 2, math.ceil)

    snapped = Scenario(
        conversion_rate=values["conversion_rate"],
        orders_per_purchasing_customer=values["orders_per_purchasing_customer"],
        average_order_value=values["average_order_value"],
        acquired_users=s.acquired_users,
    )
    return replace(suggestion, scenario=snapped,
                   kpi_change=snapped.customer_value / baseline.customer_value - 1)


def _apply_to_sliders(baseline: BaselineMetrics, scenario: Scenario) -> None:
    """
    Move the sliders to the repaired values (an on_click callback, so it runs
    before the sliders are drawn). Values are clamped to each slider's range.
    """
    bounds = slider_bounds(baseline)
    for key, value in (
        (CONVERSION_KEY, scenario.conversion_rate * 100),
        (ORDERS_KEY, scenario.orders_per_purchasing_customer),
        (ORDER_VALUE_KEY, scenario.average_order_value),
    ):
        low, high, _ = bounds[key]
        st.session_state[key] = float(min(max(round(value, 10), low), high))


# The gap between the suggestion and the slider, in the slider's own units.
CHANGE_FORMAT = {
    "conversion_rate": lambda d: f"{d * 100:+.1f} pts",
    "orders_per_purchasing_customer": lambda d: f"{d:+.1f}",
    "average_order_value": lambda d: f"{'+' if d >= 0 else '−'}${abs(d):,.2f}",
}
PILL_TEXT = {"raised": "↑ raised", "lowered": "↓ lowered",
             "as-set": "as set", "flexible": "flexible"}


def _status(suggestion: RepairSuggestion, wanted: Scenario, factor: str) -> str:
    """raised / lowered / as-set for a kept-close assumption; flexible otherwise."""
    if factor not in suggestion.targets:
        return "flexible"
    suggested = getattr(suggestion.scenario, factor)
    if _is_kept(suggestion, factor, suggested):
        return "as-set"
    return "raised" if suggested > getattr(wanted, factor) else "lowered"


def _moves_text(suggestion: RepairSuggestion, wanted: Scenario) -> str:
    """'raise Conversion rate and Avg order value; lower Orders per customer'."""
    def moved(direction):
        names = [SHORT_LABELS[f] for f in FACTORS if _status(suggestion, wanted, f) == direction]
        return " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 2 else names)
    parts = [f"{verb} {names}" for verb, names in
             (("raise", moved("raised")), ("lower", moved("lowered"))) if names]
    return "; ".join(parts) or "adjust the flexible assumptions"


def _table_html(baseline: BaselineMetrics, suggestion: RepairSuggestion,
                wanted: Scenario) -> str:
    """The assumptions table, as HTML so its type matches the rest of the page."""
    head = ("<tr><th>Assumption</th><th>Baseline</th><th>Your value</th>"
            "<th>Suggested</th><th>Change needed</th><th>vs baseline</th><th></th></tr>")
    body = []
    for factor in FACTORS:
        fmt = FACTOR_FORMAT[factor]
        base_value = getattr(baseline, factor)
        suggested = getattr(suggestion.scenario, factor)
        your_value = getattr(wanted, factor)
        status = _status(suggestion, wanted, factor)
        gap = suggested - your_value
        change = "—" if status == "as-set" or abs(gap) <= 1e-4 * abs(your_value or 1) \
            else CHANGE_FORMAT[factor](gap)
        body.append(
            f"<tr><td>{FACTOR_LABELS[factor]}</td><td>{fmt(base_value)}</td>"
            f"<td>{fmt(your_value)}</td><td class='is-suggested'>{fmt(suggested)}</td>"
            f"<td>{change}</td><td>{suggested / base_value - 1:+.1%}</td>"
            f"<td><span class='clue-repair-note {status}'>{PILL_TEXT[status]}</span></td></tr>"
        )
    return f"<table class='clue-repair-table'>{head}{''.join(body)}</table>"


def render_strategy_repair(baseline: BaselineMetrics) -> None:
    """
    The repair panel, recomputed from the current sliders and goal on every
    rerun. Repeat inputs come from the solve cache, so only a real change to a
    slider, the goal, or "Keep close to" costs a solve.
    """
    with st.container(border=True, key="card_sim_repair"):
        st.markdown(PANEL_CSS, unsafe_allow_html=True)
        st.markdown("###### 🔧 Strategy repair")
        st.caption(
            "Updates as you move the sliders: the scenario that reaches the goal "
            "while staying as close as possible to your assumptions, and which "
            "ones had to move."
        )

        keep = st.multiselect(
            "Keep close to",
            options=list(FACTORS),
            default=list(FACTORS),
            format_func=SHORT_LABELS.get,
            key=KEEP_CLOSE_KEY,
            help="Assumptions left out may move freely to reach the goal.",
        )

        goal = goal_value(baseline, uplift_percent())
        wanted = current_scenario(baseline)
        suggestion = suggest_repair(baseline, wanted, uplift_percent(), keep_close=tuple(keep))
        if not suggestion.ok:
            st.error(suggestion.message)
            return
        if not suggestion.unchanged:
            suggestion = _snap_to_sliders(baseline, suggestion, goal)

        key = "unchanged" if suggestion.unchanged else suggestion.outcome
        tone, headline = OUTCOME_TEXT.get(key, ("missed", suggestion.outcome))
        headline = headline.format(moves=_moves_text(suggestion, wanted))
        new_value = suggestion.scenario.customer_value
        st.markdown(
            f"<div class='clue-repair-head'><span class='clue-goal {tone}'>{headline}</span>"
            f"&nbsp;&nbsp;Customer value <b>{money(baseline.customer_value)} → "
            f"{money(new_value)}</b> ({suggestion.kpi_change:+.1%})</div>",
            unsafe_allow_html=True,
        )
        st.markdown(_table_html(baseline, suggestion, wanted), unsafe_allow_html=True)

        result = suggestion.result
        notes = [f"Limit reached: {hit}" for hit in suggestion.bounds_hit]
        notes += [f"Large move: {flag}" for flag in suggestion.flags]
        if not result.get("check", {}).get("ok", True):
            notes.append("Consistency check failed — treat this suggestion with caution.")
        if not result.get("proven_optimal", True):
            notes.append("Best solution found within the time limit (optimality not proven).")
        if not suggestion.unchanged:
            notes.append("Suggested values are rounded to the slider steps.")
        for note in notes:
            st.caption(note)

        if suggestion.unchanged:
            return  # the sliders already are the suggestion

        apply_col, pin_col, _ = st.columns([1, 1, 2])
        with apply_col:
            st.button(
                "Apply to sliders",
                key="sim_repair_apply",
                use_container_width=True,
                on_click=_apply_to_sliders,
                args=(baseline, suggestion.scenario),
            )
        with pin_col:
            # Slots used by non-pinned cards: just "Best observed" when shown
            # (mirrors comparison_cards() in simulator_view).
            other_cards = int(st.session_state.get("show_reference_card", True))
            room = can_pin(other_cards)
            st.button(
                f"📌 Pin as Scenario {next_scenario_name()}" if room
                else f"📌 List is full ({MAX_RAIL_CARDS})",
                key="sim_repair_pin",
                use_container_width=True,
                disabled=not room,
                on_click=pin_scenario,
                args=(suggestion.scenario, other_cards),
            )
