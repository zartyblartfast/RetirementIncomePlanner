"""Diagnostic test for Guyton-Klinger strategy.

Runs a GK projection and prints year-by-year:
  portfolio_value, withdrawal, withdrawal_rate, initial_rate,
  upper_guardrail_threshold, lower_guardrail_threshold

This is NOT a pass/fail test — it outputs a table for manual inspection.
Run with:  python test_gk_diagnostic.py
"""
import copy
from retirement_engine import RetirementEngine


def make_gk_config(**overrides):
    """Build a config with Guyton-Klinger strategy and a single DC pot."""
    cfg = {
        "personal": {
            "date_of_birth": "1960-01",
            "retirement_date": "2028-01",
            "retirement_age": 68,
            "end_age": 95,
            "currency": "GBP",
        },
        "target_income": {
            "net_annual": 30000,
            "cpi_rate": 0.025,
        },
        "guaranteed_income": [
            {
                "name": "UK State Pension",
                "gross_annual": 11500,
                "start_date": "2028-01",
                "end_date": None,
                "taxable": True,
                "indexation_rate": 0.025,
                "values_as_of": "2028-01",
            },
            {
                "name": "BP Pension (DB)",
                "gross_annual": 8000,
                "start_date": "2028-01",
                "end_date": None,
                "taxable": True,
                "indexation_rate": 0.025,
                "values_as_of": "2028-01",
            },
        ],
        "dc_pots": [
            {
                "name": "Consolidated DC Pot",
                "starting_balance": 350000,
                "growth_rate": 0.05,
                "fee_rate": 0.004,
                "tax_free_portion": 0.25,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            },
        ],
        "tax_free_accounts": [
            {
                "name": "ISA",
                "starting_balance": 50000,
                "growth_rate": 0.04,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            },
        ],
        "withdrawal_priority": ["Consolidated DC Pot", "ISA"],
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
        "drawdown_strategy": "guyton_klinger",
        "drawdown_strategy_params": {
            "initial_target": 30000,
            "upper_guardrail_pct": 5.5,
            "lower_guardrail_pct": 3.5,
            "raise_pct": 10.0,
            "cut_pct": 10.0,
        },
    }
    for key, val in overrides.items():
        cfg[key] = val
    return cfg


def run_diagnostic(output_file="gk_diagnostic_output.txt"):
    cfg = make_gk_config()
    engine = RetirementEngine(cfg)
    result = engine.run_projection()

    upper_pct = cfg["drawdown_strategy_params"]["upper_guardrail_pct"] / 100.0
    lower_pct = cfg["drawdown_strategy_params"]["lower_guardrail_pct"] / 100.0

    lines = []
    def out(s=""):
        print(s)
        lines.append(s)

    out("GUYTON-KLINGER DIAGNOSTIC")
    out(f"Initial target: £{cfg['drawdown_strategy_params']['initial_target']:,.0f}")
    out(f"Upper guardrail: {upper_pct*100:.1f}%   Lower guardrail: {lower_pct*100:.1f}%")
    out(f"Raise: {cfg['drawdown_strategy_params']['raise_pct']:.1f}%   "
        f"Cut: {cfg['drawdown_strategy_params']['cut_pct']:.1f}%")
    out(f"CPI: {cfg['target_income']['cpi_rate']*100:.1f}%")
    out()
    out(f"{'Age':>4} {'Portfolio':>11} {'DC W/D':>10} {'TF W/D':>8} "
        f"{'WdRate':>7} {'UpGuard':>7} {'LoGuard':>7} "
        f"{'Target':>10} {'Net':>10} {'Action':>6}")
    out("-" * 90)

    initial_rate = None
    csv_rows = []

    for i, yr in enumerate(result["years"]):
        age = yr["age"]
        if i == 0:
            portfolio = sum(p["starting_balance"] for p in cfg["dc_pots"]) + \
                        sum(a["starting_balance"] for a in cfg["tax_free_accounts"])
        else:
            portfolio = result["years"][i - 1]["total_capital"]

        dc_gross = yr["dc_withdrawal_gross"]
        tf_wd = yr["tf_withdrawal"]
        pot_withdrawal = dc_gross + tf_wd

        wd_rate = pot_withdrawal / portfolio if portfolio > 0 else 0.0
        if i == 0:
            initial_rate = wd_rate

        # Determine action (from diagnostic viewpoint)
        if i > 0:
            if wd_rate > upper_pct:
                action = "CUT"
            elif wd_rate < lower_pct:
                action = "RAISE"
            else:
                action = "-"
        else:
            action = "INIT"

        out(f"{age:>4} {portfolio:>11,.0f} {dc_gross:>10,.0f} {tf_wd:>8,.0f} "
            f"{wd_rate*100:>6.2f}% {upper_pct*100:>6.2f}% {lower_pct*100:>6.2f}% "
            f"{yr['target_net']:>10,.0f} {yr['net_income_achieved']:>10,.0f} {action:>6}")
        csv_rows.append([age, round(portfolio), round(dc_gross), round(tf_wd),
                         round(wd_rate*100, 2), round(upper_pct*100, 2),
                         round(lower_pct*100, 2), round(yr['target_net']),
                         round(yr['net_income_achieved']), action])

    out("-" * 90)
    out(f"Initial withdrawal rate: {initial_rate*100:.2f}%")
    s = result["summary"]
    out(f"Sustainable: {s['sustainable']}")
    out(f"Remaining capital at {s['end_age']}: £{s['remaining_capital']:,.0f}")
    out(f"Total tax: £{s['total_tax_paid']:,.0f}")
    if not s["sustainable"]:
        out(f"First shortfall age: {s.get('first_shortfall_age', 'N/A')}")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nOutput written to {output_file}")

    # Also write CSV for clean spreadsheet/IDE viewing
    csv_file = output_file.replace(".txt", ".csv")
    with open(csv_file, "w", encoding="utf-8") as f:
        f.write("Age,Portfolio,DC_WD,TF_WD,WdRate%,UpperGuard%,LowerGuard%,Target,Net,Action\n")
        for row in csv_rows:
            f.write(",".join(str(x) for x in row) + "\n")
    print(f"CSV written to {csv_file}")


if __name__ == "__main__":
    run_diagnostic()
