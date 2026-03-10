"""market_data.py – H2: Blended Return Calculator

Fetches live market data from the MarketDataAPI and calculates
weighted blended returns for each DC pot and ISA based on their
fund-level holdings.

Usage:
    from market_data import fetch_market_data, get_all_pot_intelligence

    api_data = fetch_market_data()
    if api_data:
        intelligence = get_all_pot_intelligence(config, api_data)
"""

import os
import requests
import logging

logger = logging.getLogger(__name__)

API_URL = os.environ.get("MARKET_DATA_API_URL", "https://marketdata.countdays.co.uk/api/v1/reference-data")
API_TIMEOUT = 10  # seconds


def fetch_market_data():
    """Fetch all market data from the MarketDataAPI.

    Returns:
        dict with keys 'benchmarks', 'inflation', 'interest_rates', 'as_of'
        or None if the API is unreachable / returns an error.
    """
    try:
        resp = requests.get(API_URL, timeout=API_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if data.get("status") != "ok":
            logger.warning("MarketDataAPI returned non-ok status: %s", data.get("status"))
            return None

        # Extract the nested structures into a flat, easy-to-use dict
        benchmarks_raw = data.get("benchmarks", {}).get("benchmarks", {})
        inflation_raw = data.get("inflation", {}).get("nations", {})
        interest_raw = data.get("interest_rates", {}).get("nations", {})

        return {
            "as_of": data.get("as_of"),
            "benchmarks": benchmarks_raw,
            "uk_cpi": inflation_raw.get("UK", {}).get("rate"),
            "uk_sonia": interest_raw.get("UK", {}).get("rate"),
            "inflation": inflation_raw,
            "interest_rates": interest_raw,
        }

    except requests.RequestException as e:
        logger.warning("Failed to fetch market data: %s", e)
        return None
    except (ValueError, KeyError) as e:
        logger.warning("Failed to parse market data response: %s", e)
        return None


def _resolve_benchmark_return(benchmark_key, market_data):
    """Resolve a holding's benchmark_key to a live return value.

    Args:
        benchmark_key: e.g. 'developed_equity', 'interest_rate'
        market_data: dict returned by fetch_market_data()

    Returns:
        tuple of (return_value, benchmark_label, proxy_ticker) or (None, None, None)
    """
    # Special case: cash holdings map to SONIA
    if benchmark_key == "interest_rate":
        rate = market_data.get("uk_sonia")
        if rate is not None:
            return (rate, "UK SONIA", "SONIA")
        return (None, None, None)

    # Standard benchmark lookup
    bm = market_data.get("benchmarks", {}).get(benchmark_key)
    if bm:
        return (
            bm.get("return_1y"),
            bm.get("label", benchmark_key),
            bm.get("proxy", "")
        )

    logger.warning("Unknown benchmark_key: %s", benchmark_key)
    return (None, None, None)


def normalize_holding(h):
    """Normalize a holding dict to the canonical format.

    Handles backward compatibility with old format where 'isin' was a
    top-level field and 'input_type'/'input_value' did not exist.

    Canonical format:
        fund_name, input_type, input_value, benchmark_key, weight

    Where input_type is one of: 'isin', 'lookup', 'manual_asset_class'

    Returns:
        dict in canonical format (new dict, does not mutate input)
    """
    normalized = {
        "fund_name": h.get("fund_name", "Unknown"),
        "benchmark_key": h.get("benchmark_key", ""),
        "weight": h.get("weight", 0.0),
    }

    if "input_type" in h:
        normalized["input_type"] = h["input_type"]
        normalized["input_value"] = h.get("input_value", "")
    elif h.get("isin"):
        normalized["input_type"] = "isin"
        normalized["input_value"] = h["isin"]
    elif h.get("benchmark_key"):
        normalized["input_type"] = "manual_asset_class"
        normalized["input_value"] = ""
    else:
        normalized["input_type"] = "manual_asset_class"
        normalized["input_value"] = ""

    return normalized


def normalize_holdings(holdings):
    """Normalize a list of holdings to canonical format.

    Args:
        holdings: list of holding dicts (old or new format)

    Returns:
        list of holding dicts in canonical format
    """
    if not holdings:
        return []
    return [normalize_holding(h) for h in holdings]


def calc_pot_blended_return(holdings, market_data):
    """Calculate the blended market return for a single pot.

    Args:
        holdings: list of holding dicts from config (old or new format)
                  [{fund_name, input_type, input_value, benchmark_key, weight}, ...]
        market_data: dict returned by fetch_market_data()

    Returns:
        dict with:
            'holdings_detail': list of per-holding dicts
            'blended_return': weighted average return (float or None)
            'coverage': fraction of portfolio with valid market data
    """
    if not holdings or not market_data:
        return None

    normalized = normalize_holdings(holdings)
    details = []
    weighted_sum = 0.0
    covered_weight = 0.0

    for h in normalized:
        fund_name = h["fund_name"]
        benchmark_key = h["benchmark_key"]
        weight = h["weight"]
        input_type = h["input_type"]
        input_value = h["input_value"]

        live_return, bm_label, proxy = _resolve_benchmark_return(benchmark_key, market_data)

        detail = {
            "fund_name": fund_name,
            "input_type": input_type,
            "input_value": input_value,
            "benchmark_key": benchmark_key,
            "benchmark_label": bm_label,
            "proxy_ticker": proxy,
            "weight": weight,
            "weight_pct": round(weight * 100, 2),
            "live_return": live_return,
            "live_return_pct": round(live_return * 100, 2) if live_return is not None else None,
            "contribution": round(weight * live_return, 6) if live_return is not None else None,
        }
        details.append(detail)

        if live_return is not None:
            weighted_sum += weight * live_return
            covered_weight += weight

    blended = round(weighted_sum, 6) if covered_weight > 0 else None
    coverage = round(covered_weight, 4)

    return {
        "holdings_detail": details,
        "blended_return": blended,
        "blended_return_pct": round(blended * 100, 2) if blended is not None else None,
        "coverage": coverage,
        "coverage_pct": round(coverage * 100, 1),
    }


def get_all_pot_intelligence(config, market_data):
    """Process all DC pots and tax-free accounts, returning market intelligence.

    Args:
        config: full app config dict
        market_data: dict returned by fetch_market_data()

    Returns:
        dict with:
            'pots': {pot_name: blended_return_result, ...}
            'macro': {uk_cpi, uk_sonia, ...}
            'as_of': date string
        or None if market_data is None
    """
    if not market_data:
        return None

    pots = {}

    # Process DC pots
    for pot in config.get("dc_pots", []):
        name = pot.get("name", "Unknown DC Pot")
        holdings = pot.get("holdings", [])
        planning_rate = pot.get("growth_rate", 0.0)

        if holdings:
            result = calc_pot_blended_return(holdings, market_data)
            if result:
                result["planning_rate"] = planning_rate
                result["planning_rate_pct"] = round(planning_rate * 100, 2)
                # Variance: positive = market outperforming assumption
                if result["blended_return"] is not None:
                    variance = result["blended_return"] - planning_rate
                    result["variance"] = round(variance, 6)
                    result["variance_pct"] = round(variance * 100, 2)
                    # Traffic light: green if market >= planning, amber if within 1pp, red if market < planning by >1pp
                    if variance >= 0:
                        result["status"] = "green"  # Market meets or exceeds assumption
                    elif variance >= -0.01:
                        result["status"] = "amber"  # Within 1 percentage point
                    else:
                        result["status"] = "red"    # Market significantly below assumption
                else:
                    result["variance"] = None
                    result["variance_pct"] = None
                    result["status"] = "grey"
                result["pot_type"] = "dc"
                pots[name] = result

    # Process tax-free accounts (ISAs)
    for acc in config.get("tax_free_accounts", []):
        name = acc.get("name", "Unknown ISA")
        holdings = acc.get("holdings", [])
        planning_rate = acc.get("growth_rate", 0.0)

        if holdings:
            result = calc_pot_blended_return(holdings, market_data)
            if result:
                result["planning_rate"] = planning_rate
                result["planning_rate_pct"] = round(planning_rate * 100, 2)
                if result["blended_return"] is not None:
                    variance = result["blended_return"] - planning_rate
                    result["variance"] = round(variance, 6)
                    result["variance_pct"] = round(variance * 100, 2)
                    if variance >= 0:
                        result["status"] = "green"
                    elif variance >= -0.01:
                        result["status"] = "amber"
                    else:
                        result["status"] = "red"
                else:
                    result["variance"] = None
                    result["variance_pct"] = None
                    result["status"] = "grey"
                result["pot_type"] = "tax_free"
                pots[name] = result

    # Macro overview
    macro = {
        "uk_cpi": market_data.get("uk_cpi"),
        "uk_cpi_pct": round(market_data["uk_cpi"] * 100, 2) if market_data.get("uk_cpi") is not None else None,
        "uk_sonia": market_data.get("uk_sonia"),
        "uk_sonia_pct": round(market_data["uk_sonia"] * 100, 2) if market_data.get("uk_sonia") is not None else None,
        "assumed_cpi": config.get("cpi_rate", 0.025),
        "assumed_cpi_pct": round(config.get("cpi_rate", 0.025) * 100, 2),
    }

    return {
        "pots": pots,
        "macro": macro,
        "as_of": market_data.get("as_of"),
    }
