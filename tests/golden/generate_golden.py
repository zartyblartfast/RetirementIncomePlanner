"""Generate golden snapshot fixtures for all 6 drawdown strategies.

Run this script to regenerate fixtures after an intentional engine change.
The generated JSON files are committed to the repo and used by test_golden.py.

Usage:
    python tests/golden/generate_golden.py
"""
import json
import os
import sys
import copy

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from retirement_engine import RetirementEngine
from drawdown_strategies import normalize_config
from config_helpers import make_extended_config


# ---------- Base config shared by all strategies ----------
BASE_CONFIG = {
    "personal": {
        "date_of_birth": "1960-01",
        "retirement_date": "2028-01",
        "retirement_age": 68,
        "end_age": 78,
        "currency": "GBP",
    },
    "target_income": {
        "net_annual": 20000,
        "cpi_rate": 0.02,
    },
    "guaranteed_income": [
        {
            "name": "State Pension",
            "gross_annual": 11500,
            "indexation_rate": 0.02,
            "taxable": True,
            "start_date": "2028-01",
        }
    ],
    "dc_pots": [
        {
            "name": "Employer",
            "starting_balance": 80000,
            "growth_rate": 0.04,
            "fee_pct": 0.005,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }
    ],
    "tax_free_accounts": [
        {
            "name": "ISA",
            "starting_balance": 50000,
            "growth_rate": 0.04,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }
    ],
    "withdrawal_priority": ["Employer", "ISA"],
    "tax": {
        "regime": "Isle of Man",
        "personal_allowance": 14500,
        "bands": [
            {"name": "Lower rate", "width": 6500, "rate": 0.1},
            {"name": "Higher rate", "width": None, "rate": 0.2},
        ],
        "tax_cap_enabled": False,
        "tax_cap_amount": 200000,
    },
}

# ---------- Per-strategy overrides ----------
STRATEGY_CONFIGS = {
    "fixed_target": {
        "drawdown_strategy": "fixed_target",
        "drawdown_strategy_params": {"net_annual": 20000},
    },
    "fixed_percentage": {
        "drawdown_strategy": "fixed_percentage",
        "drawdown_strategy_params": {"withdrawal_rate": 4.0},
    },
    "vanguard_dynamic": {
        "drawdown_strategy": "vanguard_dynamic",
        "drawdown_strategy_params": {
            "initial_target": 20000,
            "max_increase_pct": 5.0,
            "max_decrease_pct": 2.5,
        },
    },
    "guyton_klinger": {
        "drawdown_strategy": "guyton_klinger",
        "drawdown_strategy_params": {
            "initial_target": 20000,
            "upper_guardrail_pct": 5.5,
            "lower_guardrail_pct": 3.5,
            "raise_pct": 10.0,
            "cut_pct": 10.0,
        },
    },
    "arva": {
        "drawdown_strategy": "arva",
        "drawdown_strategy_params": {"assumed_real_return_pct": 3.0},
    },
    "arva_guardrails": {
        "drawdown_strategy": "arva_guardrails",
        "drawdown_strategy_params": {
            "assumed_real_return_pct": 3.0,
            "max_annual_increase_pct": 10.0,
            "max_annual_decrease_pct": 10.0,
        },
    },
}

# Shortfall config: fixed_target with low balance so capital runs out before plan end
SHORTFALL_CONFIG = {
    "personal": {
        "date_of_birth": "1960-01",
        "retirement_date": "2028-01",
        "retirement_age": 68,
        "end_age": 78,
        "currency": "GBP",
    },
    "target_income": {"net_annual": 15000, "cpi_rate": 0.0},
    "guaranteed_income": [],
    "dc_pots": [],
    "tax_free_accounts": [
        {
            "name": "ISA",
            "starting_balance": 30000,
            "growth_rate": 0.0,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }
    ],
    "withdrawal_priority": ["ISA"],
    "tax": BASE_CONFIG["tax"],
    "drawdown_strategy": "fixed_target",
    "drawdown_strategy_params": {"net_annual": 15000},
}


def extract_year_data(yr):
    """Extract the fields we pin in golden tests."""
    return {
        "age": yr["age"],
        "target_net": round(yr["target_net"], 2),
        "net_income_achieved": round(yr["net_income_achieved"], 2),
        "total_capital": round(yr["total_capital"], 2),
        "shortfall": yr["shortfall"],
    }


def extract_summary(summary):
    """Extract pinned summary fields."""
    return {
        "sustainable": summary["sustainable"],
        "first_shortfall_age": summary["first_shortfall_age"],
        "remaining_capital": round(summary["remaining_capital"], 2),
        "end_age": summary["end_age"],
    }


def generate_fixture(name, cfg):
    """Run normal + extended projection, return fixture dict."""
    normalize_config(cfg)
    result = RetirementEngine(cfg).run_projection()

    ext_cfg = make_extended_config(cfg)
    ext_result = RetirementEngine(ext_cfg).run_projection()

    # Check that years within plan end are identical between normal and extended
    plan_end = cfg["personal"]["end_age"]
    normal_years = [extract_year_data(y) for y in result["years"]]
    ext_years_within_plan = [
        extract_year_data(y) for y in ext_result["years"]
        if y["age"] <= plan_end
    ]
    ext_years_all = [extract_year_data(y) for y in ext_result["years"]]

    return {
        "name": name,
        "config": cfg,
        "summary": extract_summary(result["summary"]),
        "years": normal_years,
        "ext_summary": extract_summary(ext_result["summary"]),
        "ext_years": ext_years_all,
        "parity_check": {
            "plan_end_age": plan_end,
            "normal_year_count": len(normal_years),
            "ext_years_within_plan_count": len(ext_years_within_plan),
            "years_match": normal_years == ext_years_within_plan,
        },
    }


def main():
    out_dir = os.path.dirname(__file__)

    # Standard strategy fixtures
    for sid, overrides in STRATEGY_CONFIGS.items():
        cfg = copy.deepcopy(BASE_CONFIG)
        cfg.update(overrides)
        fixture = generate_fixture(sid, cfg)
        path = os.path.join(out_dir, f"{sid}.json")
        with open(path, "w") as f:
            json.dump(fixture, f, indent=2)
        parity = fixture["parity_check"]
        status = "MATCH" if parity["years_match"] else "MISMATCH"
        print(f"  {sid}: sustainable={fixture['summary']['sustainable']}, "
              f"remaining=£{fixture['summary']['remaining_capital']:,.0f}, "
              f"ext_parity={status}")

    # Shortfall fixture
    cfg = copy.deepcopy(SHORTFALL_CONFIG)
    fixture = generate_fixture("fixed_target_shortfall", cfg)
    path = os.path.join(out_dir, "fixed_target_shortfall.json")
    with open(path, "w") as f:
        json.dump(fixture, f, indent=2)
    print(f"  fixed_target_shortfall: sustainable={fixture['summary']['sustainable']}, "
          f"shortfall_age={fixture['summary']['first_shortfall_age']}")

    print(f"\nGenerated {len(STRATEGY_CONFIGS) + 1} golden fixtures in {out_dir}")


if __name__ == "__main__":
    main()
