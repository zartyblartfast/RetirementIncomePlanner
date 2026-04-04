"""Config helper functions for the retirement projection engine.

Centralises config transformations so that every caller uses the same
logic.  In particular, extended projections must NEVER mutate
personal.end_age or drawdown_strategy_params.
"""

import copy
import logging

from drawdown_strategies import STRATEGY_IDS

logger = logging.getLogger(__name__)

# Valid strategy output modes
VALID_MODES = {"net", "pot_net", "gross"}


def validate_config(cfg):
    """Check config invariants before running a projection.

    Returns a list of error strings.  Empty list means valid.
    Called at the start of run_projection(); raises in test mode,
    logs warnings in production.
    """
    errors = []

    # Strategy must be known
    sid = cfg.get("drawdown_strategy")
    if sid not in STRATEGY_IDS:
        errors.append(f"Unknown drawdown_strategy: {sid!r}")

    # Strategy params must exist
    if not cfg.get("drawdown_strategy_params"):
        errors.append("Missing drawdown_strategy_params")

    personal = cfg.get("personal", {})
    end_age = personal.get("end_age")
    ret_age = personal.get("retirement_age")

    # Plan end must be > retirement age
    if end_age is not None and ret_age is not None and end_age <= ret_age:
        errors.append(f"end_age ({end_age}) must be > retirement_age ({ret_age})")

    # Projection must cover plan
    proj_end = cfg.get("projection_end_age", end_age)
    if proj_end is not None and end_age is not None and proj_end < end_age:
        errors.append(
            f"projection_end_age ({proj_end}) < end_age ({end_age})")

    # Pot balances must be non-negative
    for pot in cfg.get("dc_pots", []):
        if pot.get("starting_balance", 0) < 0:
            errors.append(f"Negative DC pot balance: {pot.get('name')}")
    for acc in cfg.get("tax_free_accounts", []):
        if acc.get("starting_balance", 0) < 0:
            errors.append(f"Negative TF account balance: {acc.get('name')}")

    # target_end_age must NOT exist in strategy params (removed — engine
    # derives plan_end_age from personal.end_age)
    params = cfg.get("drawdown_strategy_params", {})
    if "target_end_age" in params:
        errors.append(
            "target_end_age found in drawdown_strategy_params — "
            "this param has been removed; engine uses personal.end_age")

    return errors


def validate_strategy_output(result, strategy_id):
    """Validate a single strategy compute result.

    Called after each annual strategy dispatch.
    Returns a list of error strings.  Empty = valid.
    """
    errors = []
    if not isinstance(result, dict):
        errors.append(f"Strategy {strategy_id} returned non-dict: {type(result)}")
        return errors

    mode = result.get("mode")
    if mode not in VALID_MODES:
        errors.append(f"Strategy {strategy_id} returned invalid mode: {mode!r}")

    amount = result.get("annual_amount")
    if amount is None:
        errors.append(f"Strategy {strategy_id} returned no annual_amount")
    elif amount < 0:
        errors.append(
            f"Strategy {strategy_id} returned negative annual_amount: {amount}")

    return errors


def make_extended_config(cfg, horizon=120):
    """Create a config for an extended (chart) projection.

    Sets ``projection_end_age`` so the engine simulates further than the
    user's plan end age.  ``personal.end_age`` and all strategy params
    are left untouched — the engine uses ``config_end_age`` (derived from
    ``personal.end_age``) for strategy calculations (e.g. ARVA remaining
    years).

    Args:
        cfg:     The base config dict.
        horizon: How far forward to project (default 120).

    Returns:
        A deep copy of *cfg* with only ``projection_end_age`` added.
    """
    ext = copy.deepcopy(cfg)
    plan_end = ext["personal"]["end_age"]
    ext["projection_end_age"] = min(horizon, max(plan_end, horizon))
    return ext
