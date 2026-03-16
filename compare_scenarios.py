"""Quick scenario comparison script — not part of the app."""
import json
from retirement_engine import RetirementEngine

SCENARIO_FILES = [
    ("GKG_36k", "scenarios/GKG_£36k.json"),
    ("GKG_40k", "scenarios/GKG_£40k.json"),
]

def load_and_run(name, path):
    with open(path) as f:
        sc = json.load(f)
    cfg = sc["config"]
    engine = RetirementEngine(cfg)
    result = engine.run_projection()
    return cfg, result

def main():
    data = {}
    for name, path in SCENARIO_FILES:
        cfg, result = load_and_run(name, path)
        data[name] = (cfg, result)

    # --- Config comparison ---
    print("=" * 80)
    print("CONFIG COMPARISON")
    print("=" * 80)
    for name, (cfg, _) in data.items():
        print(f"\n--- {name} ---")
        print(f"  drawdown_strategy:      {cfg['drawdown_strategy']}")
        print(f"  strategy_params:        {cfg['drawdown_strategy_params']}")
        print(f"  target_income.net_annual: {cfg['target_income']['net_annual']}")
        print(f"  cpi_rate:               {cfg['target_income']['cpi_rate']}")
        print(f"  withdrawal_priority:    {cfg['withdrawal_priority']}")
        pots = [(p['name'], p['starting_balance']) for p in cfg.get('dc_pots', [])]
        tfs = [(a['name'], a['starting_balance']) for a in cfg.get('tax_free_accounts', [])]
        print(f"  dc_pots:                {pots}")
        print(f"  tax_free_accounts:      {tfs}")

    # --- Summary comparison ---
    print("\n" + "=" * 80)
    print("SUMMARY COMPARISON")
    print("=" * 80)
    header = f"{'Metric':<30s}"
    for name in data:
        header += f" {name:>15s}"
    print(header)
    print("-" * 80)

    keys = [
        ("sustainable", "sustainable"),
        ("remaining_capital", "remaining_capital"),
        ("total_tax_paid", "total_tax_paid"),
        ("first_shortfall_age", "first_shortfall_age"),
        ("avg_effective_tax_rate", "avg_effective_tax_rate"),
    ]
    for label, key in keys:
        row = f"{label:<30s}"
        for name in data:
            v = data[name][1]["summary"].get(key, "N/A")
            if isinstance(v, float):
                row += f" {v:>15,.1f}"
            else:
                row += f" {str(v):>15s}"
        print(row)

    # --- Year-by-year comparison ---
    print("\n" + "=" * 120)
    print("YEAR-BY-YEAR COMPARISON")
    print("=" * 120)
    names = list(data.keys())
    print(f"{'AGE':>3s} | ", end="")
    for n in names:
        print(f"{'target_net':>10s} {'tax':>7s} {'capital':>10s} {'guar':>8s} {'wd_detail':>30s} | ", end="")
    print()
    print("-" * 120)

    years_lists = [data[n][1]["years"] for n in names]
    max_len = max(len(y) for y in years_lists)
    for i in range(max_len):
        row = ""
        for j, yl in enumerate(years_lists):
            if i < len(yl):
                y = yl[i]
                age = y["age"]
                wd = y.get("withdrawal_detail", {})
                wd_str = " ".join(f"{k}:{v:,.0f}" for k, v in wd.items()) if wd else "-"
                if j == 0:
                    row += f"{age:3d} | "
                row += f"{y['target_net']:>10,.0f} {y['tax_due']:>7,.0f} {y['total_capital']:>10,.0f} {y['guaranteed_total']:>8,.0f} {wd_str:>30s} | "
            else:
                if j == 0:
                    row += f"{'':>3s} | "
                row += f"{'':>10s} {'':>7s} {'':>10s} {'':>8s} {'':>30s} | "
        print(row)

    # --- Pot depletion ages ---
    print("\n" + "=" * 80)
    print("POT DEPLETION AGES")
    print("=" * 80)
    for name in names:
        print(f"\n--- {name} ---")
        years = data[name][1]["years"]
        reported = set()
        for y in years:
            all_bals = {**y.get("pot_balances", {}), **y.get("tf_balances", {})}
            for pname, bal in all_bals.items():
                if bal < 1 and pname not in reported:
                    print(f"  {pname}: depleted at age {y['age']}")
                    reported.add(pname)

    # --- Anomaly checks ---
    print("\n" + "=" * 80)
    print("ANOMALY CHECKS")
    print("=" * 80)
    for name in names:
        years = data[name][1]["years"]
        print(f"\n--- {name} ---")
        # Check for income drops > 15%
        for i in range(1, len(years)):
            prev = years[i-1]["target_net"]
            curr = years[i]["target_net"]
            if prev > 0:
                change_pct = (curr - prev) / prev * 100
                if abs(change_pct) > 15:
                    print(f"  WARNING: Large income change at age {years[i]['age']}: "
                          f"{prev:,.0f} -> {curr:,.0f} ({change_pct:+.1f}%)")
        # Check for years where shortfall > 5% of target
        for y in years:
            shortfall = y.get("shortfall", 0)
            if shortfall > y["target_net"] * 0.05 and y["target_net"] > 0:
                print(f"  WARNING: Shortfall at age {y['age']}: "
                      f"£{shortfall:,.0f} ({shortfall/y['target_net']*100:.1f}% of target)")

if __name__ == "__main__":
    main()
