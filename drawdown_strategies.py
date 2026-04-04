"""Drawdown strategy registry and computation functions.

Each strategy determines HOW MUCH to withdraw each year.
The drawdown ORDER (which pots fund the withdrawal) is handled separately
by the engine's priority-based allocation.

Strategy functions signature:
    compute(params, state, portfolio_value, cpi_rate) -> (target_dict, new_state)

    params:          dict of strategy-specific parameters
    state:           dict carrying year-over-year state (None on first call)
    portfolio_value: total investable capital (DC pots + tax-free accounts)
    cpi_rate:        annual CPI rate from config

    Returns:
        target_dict: {"mode": "net"|"gross", "annual_amount": float}
        new_state:   dict to pass into next year's call
"""

import copy

# ------------------------------------------------------------------ #
#  Strategy registry
# ------------------------------------------------------------------ #

STRATEGIES = {
    "fixed_target": {
        "display_name": "Fixed Target",
        "description": "Withdraw a fixed net income target each year, adjusted by CPI.",
        "params": [
            {"key": "net_annual", "label": "Target Net Income (£)", "type": "number",
             "step": 500, "default": 30000},
        ],
    },
    "fixed_percentage": {
        "display_name": "Fixed Percentage",
        "description": "Withdraw a fixed percentage of the investable portfolio each year.",
        "params": [
            {"key": "withdrawal_rate", "label": "Withdrawal Rate (%)", "type": "number",
             "step": 0.1, "default": 4.0},
        ],
    },
    "vanguard_dynamic": {
        "display_name": "Vanguard Dynamic Spending",
        "description": "CPI-adjusted withdrawals with capped annual increases and decreases.",
        "params": [
            {"key": "initial_target", "label": "Initial Target Income (£)", "type": "number",
             "step": 500, "default": 30000},
            {"key": "max_increase_pct", "label": "Max Annual Increase (%)", "type": "number",
             "step": 0.5, "default": 5.0,
             "tooltip": "Ceiling: the maximum percentage income can rise in a single year, even if markets boom. Prevents over-spending in good years."},
            {"key": "max_decrease_pct", "label": "Max Annual Decrease (%)", "type": "number",
             "step": 0.5, "default": 2.5,
             "tooltip": "Floor: the maximum percentage income can fall in a single year, even if markets crash. Smooths income during downturns."},
        ],
    },
    "guyton_klinger": {
        "display_name": "Guyton-Klinger Guardrails",
        "description": "Income adjusted when withdrawal rate drifts outside guardrails.",
        "params": [
            {"key": "initial_target", "label": "Initial Target Income (£)", "type": "number",
             "step": 500, "default": 30000},
            {"key": "upper_guardrail_pct", "label": "Upper Guardrail (%)", "type": "number",
             "step": 0.5, "default": 5.5,
             "tooltip": "If your actual withdrawal rate exceeds this percentage of your portfolio, income is cut. Signals you are spending too fast."},
            {"key": "lower_guardrail_pct", "label": "Lower Guardrail (%)", "type": "number",
             "step": 0.5, "default": 3.5,
             "tooltip": "If your actual withdrawal rate drops below this percentage of your portfolio, income is raised. Signals you can afford to spend more."},
            {"key": "raise_pct", "label": "Raise (%)", "type": "number",
             "step": 0.5, "default": 10.0,
             "tooltip": "When the lower guardrail triggers, income is increased by this percentage. A 10% raise on \u00a330k = \u00a333k."},
            {"key": "cut_pct", "label": "Cut (%)", "type": "number",
             "step": 0.5, "default": 10.0,
             "tooltip": "When the upper guardrail triggers, income is reduced by this percentage. A 10% cut on £30k = £27k."},
        ],
    },
    "arva": {
        "display_name": "ARVA",
        "description": "Annually Recalculated Virtual Annuity — withdrawal recalculated each year to target depletion by end age.",
        "params": [
            {"key": "assumed_real_return_pct", "label": "Assumed Real Return (%)", "type": "number",
             "step": 0.5, "default": 3.0,
             "tooltip": "The real (after-inflation) return ARVA assumes when calculating withdrawals. Higher = larger withdrawals but more risk of depletion if actual returns are lower."},
            {"key": "target_end_age", "label": "Target End Age", "type": "number",
             "step": 1, "default": 90, "sandbox_hidden": True},
        ],
    },
    "arva_guardrails": {
        "display_name": "ARVA + Guardrails",
        "description": "ARVA with caps on year-to-year spending changes to reduce volatility.",
        "params": [
            {"key": "assumed_real_return_pct", "label": "Assumed Real Return (%)", "type": "number",
             "step": 0.5, "default": 3.0,
             "tooltip": "The real (after-inflation) return ARVA assumes when calculating withdrawals. Higher = larger withdrawals but more risk of depletion if actual returns are lower."},
            {"key": "target_end_age", "label": "Target End Age", "type": "number",
             "step": 1, "default": 90, "sandbox_hidden": True},
            {"key": "max_annual_increase_pct", "label": "Max Annual Increase (%)", "type": "number",
             "step": 1.0, "default": 10.0,
             "tooltip": "Ceiling: the maximum percentage ARVA income can rise year-to-year. Prevents over-spending after a single strong year."},
            {"key": "max_annual_decrease_pct", "label": "Max Annual Decrease (%)", "type": "number",
             "step": 1.0, "default": 10.0,
             "tooltip": "Floor: the maximum percentage ARVA income can fall year-to-year. Smooths the impact of bad years on your income."},
        ],
    },
}

STRATEGY_IDS = list(STRATEGIES.keys())


def get_strategy_display_name(strategy_id):
    """Return user-friendly display name for a strategy ID."""
    entry = STRATEGIES.get(strategy_id)
    return entry["display_name"] if entry else strategy_id


# ------------------------------------------------------------------ #
#  Strategy compute functions
# ------------------------------------------------------------------ #

def _compute_fixed_target(params, state, portfolio_value, cpi_rate):
    """Fixed Target: return the CPI-adjusted net income target."""
    if state is None:
        state = {"current_target": params.get("net_annual", 30000)}
    else:
        # CPI adjustment applied by the engine's monthly loop for this strategy
        pass
    return {"mode": "net", "annual_amount": state["current_target"]}, state


def _compute_fixed_percentage(params, state, portfolio_value, cpi_rate):
    """Fixed Percentage: gross withdrawal = portfolio × rate."""
    rate = params.get("withdrawal_rate", 4.0) / 100.0
    gross = portfolio_value * rate
    if state is None:
        state = {}
    return {"mode": "gross", "annual_amount": gross}, state


def _compute_vanguard_dynamic(params, state, portfolio_value, cpi_rate):
    """Vanguard Dynamic Spending: CPI-adjust prior target, clamp by limits."""
    max_up = params.get("max_increase_pct", 5.0) / 100.0
    max_down = params.get("max_decrease_pct", 2.5) / 100.0

    if state is None:
        # First year: use the initial target directly
        target = params.get("initial_target", 30000)
        state = {"prev_target": target}
        return {"mode": "net", "annual_amount": target}, state

    prev = state["prev_target"]
    inflation_adjusted = prev * (1 + cpi_rate)

    max_up_val = prev * (1 + max_up)
    max_down_val = prev * (1 - max_down)

    new_target = max(max_down_val, min(inflation_adjusted, max_up_val))
    state = {"prev_target": new_target}
    return {"mode": "net", "annual_amount": new_target}, state


def _pmt(pv, r, n):
    """Annuity payment: amount to withdraw annually to deplete pv over n years at rate r.

    Returns the level annual payment that exactly exhausts pv given:
        pv  = present value (portfolio)
        r   = annual real return
        n   = number of remaining years
        FV  = 0 (target full depletion)
    """
    if n <= 0:
        return pv  # All remaining capital
    if abs(r) < 1e-10:
        return pv / n
    return pv * r / (1 - (1 + r) ** (-n))


def _compute_guyton_klinger(params, state, portfolio_value, cpi_rate):
    """Guyton-Klinger Guardrails: adjust income when rate drifts outside rails."""
    upper = params.get("upper_guardrail_pct", 5.5) / 100.0
    lower = params.get("lower_guardrail_pct", 3.5) / 100.0
    raise_pct = params.get("raise_pct", 10.0) / 100.0
    cut_pct = params.get("cut_pct", 10.0) / 100.0

    if state is None:
        # First year: establish baseline
        target = params.get("initial_target", 30000)
        state = {
            "current_target": target,
            "starting_rate": None,  # set after first year's gross is known
            "prev_gross": None,
        }
        return {"mode": "net", "annual_amount": target}, state

    # CPI-adjust the current target as baseline
    current_target = state["current_target"] * (1 + cpi_rate)

    # Check guardrails using last year's gross and current portfolio
    starting_rate = state.get("starting_rate")
    prev_gross = state.get("prev_gross")

    if starting_rate is not None and prev_gross is not None and portfolio_value > 0:
        current_rate = prev_gross / portfolio_value
        if current_rate > upper:
            current_target *= (1 - cut_pct)
        elif current_rate < lower:
            current_target *= (1 + raise_pct)

    state = copy.copy(state)
    state["current_target"] = current_target
    return {"mode": "net", "annual_amount": current_target}, state


def _compute_arva(params, state, portfolio_value, cpi_rate, current_age=None):
    """ARVA: recalculate withdrawal each year using annuity formula targeting depletion."""
    r = params.get("assumed_real_return_pct", 3.0) / 100.0
    target_end_age = params.get("target_end_age", 90)

    if state is None:
        state = {}

    # +1 so ARVA plans income THROUGH end_age (inclusive)
    remaining_years = max(1, target_end_age - (current_age or target_end_age - 1) + 1)
    # Use monthly PMT to match the engine's monthly execution model
    remaining_months = remaining_years * 12
    monthly_r = (1 + r) ** (1.0 / 12) - 1
    monthly_pmt = _pmt(portfolio_value, monthly_r, remaining_months)
    withdrawal = max(0, monthly_pmt * 12)

    state = {"prev_withdrawal": withdrawal}
    return {"mode": "pot_net", "annual_amount": withdrawal}, state


def _compute_arva_guardrails(params, state, portfolio_value, cpi_rate, current_age=None):
    """ARVA + Guardrails: ARVA with capped year-to-year spending changes."""
    r = params.get("assumed_real_return_pct", 3.0) / 100.0
    target_end_age = params.get("target_end_age", 90)
    max_up = params.get("max_annual_increase_pct", 10.0) / 100.0
    max_down = params.get("max_annual_decrease_pct", 10.0) / 100.0

    # +1 so ARVA plans income THROUGH end_age (inclusive)
    remaining_years = max(1, target_end_age - (current_age or target_end_age - 1) + 1)
    # Use monthly PMT to match the engine's monthly execution model
    remaining_months = remaining_years * 12
    monthly_r = (1 + r) ** (1.0 / 12) - 1
    monthly_pmt = _pmt(portfolio_value, monthly_r, remaining_months)
    raw_withdrawal = max(0, monthly_pmt * 12)

    if state is None:
        # First year: no prior withdrawal to clamp against
        state = {"prev_withdrawal": raw_withdrawal}
        return {"mode": "pot_net", "annual_amount": raw_withdrawal}, state

    prev = state.get("prev_withdrawal", raw_withdrawal)
    max_val = prev * (1 + max_up)
    min_val = prev * (1 - max_down)
    clamped = max(min_val, min(raw_withdrawal, max_val))

    state = {"prev_withdrawal": clamped}
    return {"mode": "pot_net", "annual_amount": clamped}, state


_COMPUTE_MAP = {
    "fixed_target": _compute_fixed_target,
    "fixed_percentage": _compute_fixed_percentage,
    "vanguard_dynamic": _compute_vanguard_dynamic,
    "guyton_klinger": _compute_guyton_klinger,
    "arva": _compute_arva,
    "arva_guardrails": _compute_arva_guardrails,
}


def compute_annual_target(strategy_id, params, state, portfolio_value, cpi_rate,
                          current_age=None):
    """Dispatch to the correct strategy compute function.

    Returns (target_dict, new_state).
    """
    fn = _COMPUTE_MAP.get(strategy_id, _compute_fixed_target)
    # Pass current_age for strategies that use it (ARVA)
    try:
        return fn(params, state, portfolio_value, cpi_rate, current_age=current_age)
    except TypeError:
        return fn(params, state, portfolio_value, cpi_rate)


# ------------------------------------------------------------------ #
#  Config normalization
# ------------------------------------------------------------------ #

def normalize_config(cfg):
    """Ensure drawdown_strategy fields exist with sensible defaults.

    Strategy params are the single source of truth for the income target.
    target_income.net_annual is kept in sync for display / backward compat.

    Mutates cfg in place for convenience; also returns it.
    """
    if "drawdown_strategy" not in cfg:
        cfg["drawdown_strategy"] = "fixed_target"

    fallback_target = cfg.get("target_income", {}).get("net_annual", 30000)
    sid = cfg["drawdown_strategy"]

    if "drawdown_strategy_params" not in cfg:
        if sid == "fixed_target":
            cfg["drawdown_strategy_params"] = {
                "net_annual": fallback_target,
            }
        elif sid in ("vanguard_dynamic", "guyton_klinger"):
            entry = STRATEGIES.get(sid, {})
            params = {p["key"]: p["default"] for p in entry.get("params", [])}
            params["initial_target"] = fallback_target
            cfg["drawdown_strategy_params"] = params
        elif sid in ("arva", "arva_guardrails"):
            entry = STRATEGIES.get(sid, {})
            params = {p["key"]: p["default"] for p in entry.get("params", [])}
            # Seed target_end_age from config's end_age when available
            params["target_end_age"] = cfg.get("personal", {}).get("end_age", 90)
            cfg["drawdown_strategy_params"] = params
        else:
            # Build defaults from registry
            entry = STRATEGIES.get(sid, {})
            cfg["drawdown_strategy_params"] = {
                p["key"]: p["default"] for p in entry.get("params", [])
            }

    # Always keep ARVA target_end_age in sync with personal.end_age
    if sid in ("arva", "arva_guardrails"):
        cfg["drawdown_strategy_params"]["target_end_age"] = cfg.get("personal", {}).get("end_age", 90)

    # Sync target_income.net_annual from the strategy's authoritative value
    params = cfg["drawdown_strategy_params"]
    if sid == "fixed_target":
        cfg.setdefault("target_income", {})["net_annual"] = params.get(
            "net_annual", fallback_target)
    elif sid in ("vanguard_dynamic", "guyton_klinger"):
        cfg.setdefault("target_income", {})["net_annual"] = params.get(
            "initial_target", fallback_target)
    # ARVA: no initial_target param; target_income.net_annual left as-is

    # Migrate guaranteed income from start_age/end_age to start_date/end_date.
    # Dates are the source of truth; age fields are informational only.
    dob_str = cfg.get("personal", {}).get("date_of_birth", "1960-01")
    try:
        _dob_y, _dob_m = int(dob_str[:4]), int(dob_str[5:7])
    except (ValueError, IndexError):
        _dob_y, _dob_m = 1960, 1
    for g in cfg.get("guaranteed_income", []):
        if "start_date" not in g and "start_age" in g:
            sa = g["start_age"]
            total_m = _dob_y * 12 + (_dob_m - 1) + int(round(sa * 12))
            sy, sm = divmod(total_m, 12)
            g["start_date"] = f"{sy:04d}-{sm + 1:02d}"
        if "end_date" not in g and g.get("end_age") is not None:
            ea = g["end_age"]
            total_m = _dob_y * 12 + (_dob_m - 1) + int(round(ea * 12))
            ey, em = divmod(total_m, 12)
            g["end_date"] = f"{ey:04d}-{em + 1:02d}"

    return cfg
