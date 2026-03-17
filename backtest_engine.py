"""Backtest Engine — Rolling-window historical backtesting wrapper.

Runs the existing RetirementEngine across multiple historical periods,
injecting year-varying growth rates and CPI from historical_returns.json.

Each pot's annual return is computed as a weighted blend of historical
asset-class returns, based on the pot's holdings → benchmark_key → asset class
mapping chain.
"""

import copy
import json
import math
import os

from retirement_engine import RetirementEngine, load_asset_model

# ------------------------------------------------------------------ #
#  Data loading
# ------------------------------------------------------------------ #
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
HIST_FILE = os.path.join(DATA_DIR, "historical_returns.json")


def load_historical_returns():
    """Load the unified historical return series."""
    with open(HIST_FILE) as f:
        return json.load(f)


# ------------------------------------------------------------------ #
#  Asset-class return resolver
# ------------------------------------------------------------------ #
def _resolve_asset_class_return(asset_class_id, year_str, annual_returns,
                                hist_data_mapping):
    """Compute the historical return for one asset class in one year.

    Uses the historical_data_mapping rules from asset_model.json to blend
    or derive returns from the raw series in historical_returns.json.
    """
    entry = annual_returns.get(year_str, {})
    mapping = hist_data_mapping.get(asset_class_id)
    if not mapping:
        return None

    method = mapping.get("method")

    if method == "single":
        series = mapping["series"]
        val = entry.get(series)
        if val is not None:
            return val
        # Try fallback
        fallback = mapping.get("fallback")
        if fallback:
            return entry.get(fallback)
        return None

    elif method == "blend":
        total = 0.0
        total_weight = 0.0
        for comp in mapping["components"]:
            series = comp["series"]
            weight = comp["weight"]
            # Handle recursive references like "_global_equity"
            if series.startswith("_"):
                # Recursively resolve
                sub_id = series[1:]  # strip leading underscore
                val = _resolve_asset_class_return(
                    sub_id, year_str, annual_returns, hist_data_mapping)
            else:
                val = entry.get(series)
            if val is not None:
                total += weight * val
                total_weight += weight
        if total_weight > 0:
            # Scale up if some components missing
            return total / total_weight * sum(c["weight"] for c in mapping["components"])
        # Try fallback
        fallback = mapping.get("fallback")
        if fallback:
            return entry.get(fallback)
        return None

    elif method == "derived":
        formula = mapping.get("formula", "")
        if " - " in formula:
            parts = formula.split(" - ")
            a = entry.get(parts[0].strip())
            b = entry.get(parts[1].strip())
            if a is not None and b is not None:
                return a - b
        return None

    return None


# ------------------------------------------------------------------ #
#  Per-pot annual return from holdings
# ------------------------------------------------------------------ #
def compute_pot_annual_return(pot_config, year_str, annual_returns,
                              asset_model, hist_data_mapping):
    """Compute the weighted annual return for a pot based on its holdings.

    Each holding has a benchmark_key and weight. The benchmark_key maps to
    an asset class via asset_model["benchmark_mappings"], which then maps
    to a historical return series.

    If the pot has no holdings, falls back to the pot's allocation template
    or its static growth_rate.
    """
    benchmark_mappings = asset_model.get("benchmark_mappings", {})
    holdings = pot_config.get("holdings", [])

    if holdings:
        total_return = 0.0
        total_weight = 0.0
        for h in holdings:
            bk = h.get("benchmark_key", "")
            w = h.get("weight", 0)
            asset_class = benchmark_mappings.get(bk)
            if asset_class and w > 0:
                ac_return = _resolve_asset_class_return(
                    asset_class, year_str, annual_returns, hist_data_mapping)
                if ac_return is not None:
                    total_return += w * ac_return
                    total_weight += w
        if total_weight > 0:
            # Scale to full weight if some holdings couldn't be resolved
            return total_return / total_weight
        return None

    # Fallback: use allocation template weights
    alloc = pot_config.get("allocation", {})
    mode = alloc.get("mode", "manual")

    if mode == "template":
        template_id = alloc.get("template_id", "")
        templates = {t["id"]: t for t in asset_model.get("portfolio_templates", [])}
        template = templates.get(template_id)
        if template:
            total_return = 0.0
            total_weight = 0.0
            for tw in template["weights"]:
                ac_id = tw["asset_class_id"]
                w = tw["weight"]
                ac_return = _resolve_asset_class_return(
                    ac_id, year_str, annual_returns, hist_data_mapping)
                if ac_return is not None:
                    total_return += w * ac_return
                    total_weight += w
            if total_weight > 0:
                return total_return / total_weight

    elif mode == "custom":
        custom_weights = alloc.get("custom_weights", {})
        if custom_weights:
            total_return = 0.0
            total_weight = 0.0
            for ac_id, w in custom_weights.items():
                ac_return = _resolve_asset_class_return(
                    ac_id, year_str, annual_returns, hist_data_mapping)
                if ac_return is not None:
                    total_return += w * ac_return
                    total_weight += w
            if total_weight > 0:
                return total_return / total_weight

    # Final fallback: return None (caller uses static growth_rate)
    return None


# ------------------------------------------------------------------ #
#  Build growth & CPI schedules for one historical window
# ------------------------------------------------------------------ #
def build_schedules(cfg, window_start_year, n_years, annual_returns,
                    asset_model, hist_data_mapping):
    """Build growth_rate_schedule and cpi_rate_schedule for a single window.

    Args:
        cfg: retirement config dict
        window_start_year: first historical year in this window
        n_years: number of projection years
        annual_returns: the "annual_returns" dict from historical_returns.json
        asset_model: loaded asset model
        hist_data_mapping: asset_model["historical_data_mapping"]

    Returns:
        dict with keys:
            _dc_growth_schedules: {pot_name: {age: rate, ...}, ...}
            _tf_growth_schedules: {acc_name: {age: rate, ...}, ...}
            cpi_rate_schedule: {age: rate, ...}
            window_label: "1929-1951" style label
    """
    retirement_age = cfg["personal"]["retirement_age"]

    dc_schedules = {}
    for pot in cfg["dc_pots"]:
        name = pot["name"]
        dc_schedules[name] = {}

    tf_schedules = {}
    for acc in cfg["tax_free_accounts"]:
        name = acc["name"]
        tf_schedules[name] = {}

    cpi_schedule = {}

    for offset in range(n_years):
        age = retirement_age + offset
        hist_year = window_start_year + offset
        year_str = str(hist_year)

        # CPI
        entry = annual_returns.get(year_str, {})
        uk_cpi = entry.get("uk_cpi")
        if uk_cpi is not None:
            cpi_schedule[age] = uk_cpi

        # DC pots
        for pot in cfg["dc_pots"]:
            name = pot["name"]
            ret = compute_pot_annual_return(
                pot, year_str, annual_returns, asset_model, hist_data_mapping)
            if ret is not None:
                dc_schedules[name][age] = ret

        # Tax-free accounts
        for acc in cfg["tax_free_accounts"]:
            name = acc["name"]
            ret = compute_pot_annual_return(
                acc, year_str, annual_returns, asset_model, hist_data_mapping)
            if ret is not None:
                tf_schedules[name][age] = ret

    end_year = window_start_year + n_years - 1
    return {
        "_dc_growth_schedules": dc_schedules,
        "_tf_growth_schedules": tf_schedules,
        "cpi_rate_schedule": cpi_schedule,
        "window_label": f"{window_start_year}-{end_year}",
        "window_start": window_start_year,
    }


# ------------------------------------------------------------------ #
#  Main backtest runner
# ------------------------------------------------------------------ #
def run_backtest(cfg, max_windows=None):
    """Run rolling-window backtest across all viable historical periods.

    Args:
        cfg: retirement config dict (will be deep-copied per window)
        max_windows: optional cap on number of windows (for testing)

    Returns:
        dict with:
            windows: list of {window_label, window_start, result}
            metadata: {n_windows, n_years, start_range, end_range, ...}
    """
    hist_data = load_historical_returns()
    annual_returns = hist_data["annual_returns"]
    asset_model = load_asset_model()
    hist_data_mapping = asset_model.get("historical_data_mapping", {})

    retirement_age = cfg["personal"]["retirement_age"]
    end_age = cfg["personal"]["end_age"]
    n_years = end_age - retirement_age

    # Determine viable window range
    available_years = sorted(int(y) for y in annual_returns.keys())
    min_year = available_years[0]
    max_year = available_years[-1]

    # We need n_years of consecutive data per window
    viable_starts = [y for y in available_years
                     if y + n_years - 1 <= max_year]

    if max_windows:
        viable_starts = viable_starts[:max_windows]

    windows = []
    for start_year in viable_starts:
        # Deep copy config for this window
        window_cfg = copy.deepcopy(cfg)

        # Build historical schedules
        schedules = build_schedules(
            window_cfg, start_year, n_years,
            annual_returns, asset_model, hist_data_mapping)

        # Inject schedules into config
        window_cfg["_dc_growth_schedules"] = schedules["_dc_growth_schedules"]
        window_cfg["_tf_growth_schedules"] = schedules["_tf_growth_schedules"]
        window_cfg["cpi_rate_schedule"] = schedules["cpi_rate_schedule"]

        # Run projection
        engine = RetirementEngine(window_cfg)
        result = engine.run_projection()

        windows.append({
            "window_label": schedules["window_label"],
            "window_start": start_year,
            "result": result,
        })

    return {
        "windows": windows,
        "metadata": {
            "n_windows": len(windows),
            "n_years": n_years,
            "start_range": viable_starts[0] if viable_starts else None,
            "end_range": viable_starts[-1] if viable_starts else None,
            "retirement_age": retirement_age,
            "end_age": end_age,
        }
    }


# ------------------------------------------------------------------ #
#  Stress-test analysis: percentiles + income stability + timeline
# ------------------------------------------------------------------ #
def extract_stress_test(backtest_result, target_income=None,
                        percentiles=(5, 10, 25, 50, 75, 90)):
    """Extract stress-test metrics from backtest windows.

    Produces:
      - Percentile trajectories (capital & income fan chart data)
      - Sustainability rate
      - Income stability metrics (median as % of target, worst drop)
      - Worst-period year-by-year timeline
      - Best/worst window identification

    Args:
        backtest_result: output from run_backtest()
        target_income: annual target net income (for % comparison)
        percentiles: which percentiles to compute
    """
    import numpy as np

    windows = backtest_result["windows"]
    if not windows:
        return None

    meta = backtest_result["metadata"]
    retirement_age = meta["retirement_age"]
    end_age = meta["end_age"]
    ages = list(range(retirement_age, end_age + 1))

    # ── Collect per-age arrays across all windows ──
    capital_by_age = {age: [] for age in ages}
    income_by_age = {age: [] for age in ages}
    target_by_age = {age: [] for age in ages}

    for w in windows:
        year_lookup = {yr["age"]: yr for yr in w["result"]["years"]}
        for age in ages:
            yr = year_lookup.get(age)
            if yr:
                capital_by_age[age].append(yr["total_capital"])
                income_by_age[age].append(yr.get("net_income_achieved", 0))
                target_by_age[age].append(yr.get("target_net", 0))
            else:
                capital_by_age[age].append(0)
                income_by_age[age].append(0)
                target_by_age[age].append(0)

    # ── Percentile trajectories ──
    pct_trajectories = {}
    for p in percentiles:
        label = f"p{p}"
        pct_trajectories[label] = []
        for age in ages:
            cap_val = float(np.percentile(capital_by_age[age], p))
            inc_val = float(np.percentile(income_by_age[age], p))
            pct_trajectories[label].append({
                "age": age,
                "total_capital": round(cap_val, 2),
                "net_income": round(inc_val, 2),
            })

    # ── Sustainability rate ──
    DEPLETION_EPSILON = 1.0
    sustainable_count = sum(
        1 for v in capital_by_age[end_age] if v > DEPLETION_EPSILON
    )
    sustainability_rate = sustainable_count / len(windows) if windows else 0

    # ── Depletion age distribution (for windows that depleted) ──
    depletion_ages = {}
    for w in windows:
        depl_age = None
        for yr in w["result"]["years"]:
            if yr["total_capital"] <= DEPLETION_EPSILON:
                depl_age = yr["age"]
                break
        if depl_age is not None:
            depletion_ages[depl_age] = depletion_ages.get(depl_age, 0) + 1
    # Sort by age ascending
    depletion_age_dist = [{"age": a, "count": c}
                          for a, c in sorted(depletion_ages.items())]

    # ── Income stability metrics ──
    # Use target_income from first year of first window if not provided
    if target_income is None:
        first_yr = windows[0]["result"]["years"][0] if windows[0]["result"]["years"] else None
        if first_yr:
            target_income = first_yr.get("target_net", 0)

    # Median income achieved as fraction of target across all windows/years
    all_incomes = []
    all_income_ratios = []
    for w in windows:
        for yr in w["result"]["years"]:
            inc = yr.get("net_income_achieved", 0)
            tgt = yr.get("target_net", 0)
            all_incomes.append(inc)
            if tgt > 0:
                all_income_ratios.append(inc / tgt)

    median_income_ratio = float(np.median(all_income_ratios)) if all_income_ratios else 1.0

    # Worst / best single-year income (as % of that year's target)
    worst_income_ratio = min(all_income_ratios) if all_income_ratios else 1.0
    best_income_ratio = max(all_income_ratios) if all_income_ratios else 1.0

    # Per-window: average income achieved as % of target
    window_avg_ratios = []
    window_cumul_incomes = []
    for w in windows:
        ratios = []
        cumul = 0
        for yr in w["result"]["years"]:
            tgt = yr.get("target_net", 0)
            inc = yr.get("net_income_achieved", 0)
            cumul += inc
            if tgt > 0:
                ratios.append(inc / tgt)
        if ratios:
            window_avg_ratios.append(sum(ratios) / len(ratios))
        window_cumul_incomes.append(cumul)

    median_cumul_income = float(np.median(window_cumul_incomes)) if window_cumul_incomes else 0
    worst_cumul_income = min(window_cumul_incomes) if window_cumul_incomes else 0
    best_cumul_income = max(window_cumul_incomes) if window_cumul_incomes else 0

    # ── Worst / best window identification ──
    worst_idx = min(range(len(windows)),
                    key=lambda i: capital_by_age[end_age][i])
    worst_final = capital_by_age[end_age][worst_idx]
    worst_depl = None
    for age in ages:
        if capital_by_age[age][worst_idx] <= DEPLETION_EPSILON:
            worst_depl = age
            break

    best_idx = max(range(len(windows)),
                   key=lambda i: capital_by_age[end_age][i])

    # Median window: closest to median final capital
    finals = [capital_by_age[end_age][i] for i in range(len(windows))]
    sorted_finals = sorted(finals)
    median_val = sorted_finals[len(sorted_finals) // 2]
    median_idx = min(range(len(windows)),
                     key=lambda i: abs(capital_by_age[end_age][i] - median_val))

    # ── Build timelines for worst / median / best ──
    hist_data = load_historical_returns()
    asset_model = load_asset_model()
    hdm = asset_model.get("historical_data_mapping", {})

    def _build_timeline(w):
        timeline = []
        for yr in w["result"]["years"]:
            age = yr["age"]
            hist_year = w["window_start"] + (age - retirement_age)
            market_return = _resolve_asset_class_return(
                "global_equity", str(hist_year), hist_data["annual_returns"], hdm)
            tgt = yr.get("target_net", 0)
            inc = yr.get("net_income_achieved", 0)
            inc_ratio = inc / tgt if tgt > 0 else 1.0
            timeline.append({
                "age": age,
                "calendar_year": hist_year,
                "market_return": round(market_return * 100, 1) if market_return else None,
                "total_capital": round(yr["total_capital"], 0),
                "net_income": round(inc, 0),
                "target_income": round(tgt, 0),
                "income_ratio": round(inc_ratio, 3),
                "shortfall": yr.get("shortfall", False),
            })
        return timeline

    worst_w = windows[worst_idx]
    median_w = windows[median_idx]
    best_w = windows[best_idx]

    return {
        "ages": ages,
        "percentile_trajectories": pct_trajectories,
        "sustainability": {
            "rate": round(sustainability_rate, 4),
            "count": sustainable_count,
            "total": len(windows),
            "depletion_age_dist": depletion_age_dist,
        },
        "income_stability": {
            "median_income_ratio": round(median_income_ratio, 4),
            "worst_income_ratio": round(worst_income_ratio, 4),
            "best_income_ratio": round(best_income_ratio, 4),
            "target_income_used": round(target_income, 2) if target_income else 0,
        },
        "cumulative_income": {
            "median": round(median_cumul_income, 0),
            "worst": round(worst_cumul_income, 0),
            "best": round(best_cumul_income, 0),
        },
        "n_windows": len(windows),
        "worst_window": {
            "label": worst_w["window_label"],
            "start_year": worst_w["window_start"],
            "final_capital": round(worst_final, 2),
            "depletion_age": worst_depl,
            "timeline": _build_timeline(worst_w),
            "trajectory": [round(capital_by_age[age][worst_idx], 0) for age in ages],
        },
        "median_window": {
            "label": median_w["window_label"],
            "start_year": median_w["window_start"],
            "final_capital": round(capital_by_age[end_age][median_idx], 2),
            "timeline": _build_timeline(median_w),
        },
        "best_window": {
            "label": best_w["window_label"],
            "start_year": best_w["window_start"],
            "final_capital": round(capital_by_age[end_age][best_idx], 2),
            "timeline": _build_timeline(best_w),
        },
    }


# Backward compat alias
def extract_percentiles(backtest_result, percentiles=(10, 25, 50, 75, 90)):
    """Legacy wrapper — calls extract_stress_test."""
    return extract_stress_test(backtest_result, percentiles=percentiles)
