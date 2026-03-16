"""Compare GKG £36k vs FT £36k — config, summary, year-by-year capital & income."""
import json
from retirement_engine import RetirementEngine

SCENARIOS = [
    ("GKG £36k", "scenarios/GKG_£36k.json"),
    ("FT £36k",  "scenarios/FT_£36k.json"),
]

def load_and_run(path):
    with open(path) as f:
        sc = json.load(f)
    cfg = sc["config"]
    result = RetirementEngine(cfg).run_projection()
    return cfg, result

configs = {}
results = {}
for label, path in SCENARIOS:
    cfg, result = load_and_run(path)
    configs[label] = cfg
    results[label] = result

labels = [s[0] for s in SCENARIOS]

# --- Config comparison ---
print("=" * 70)
print("CONFIG COMPARISON")
print("=" * 70)
for label in labels:
    c = configs[label]
    print(f"\n--- {label} ---")
    print(f"  drawdown_strategy:      {c['drawdown_strategy']}")
    print(f"  strategy_params:        {c.get('drawdown_strategy_params', {})}")
    print(f"  target_income.net_annual: {c['target_income']['net_annual']}")
    print(f"  cpi_rate:               {c['target_income'].get('cpi_rate', 'N/A')}")
    print(f"  withdrawal_priority:    {c.get('withdrawal_priority', [])}")

# --- Summary comparison ---
print("\n" + "=" * 70)
print("SUMMARY COMPARISON")
print("=" * 70)
header = f"{'Metric':<35}" + "".join(f"{l:>18}" for l in labels)
print(header)
print("-" * len(header))
for key in ["sustainable", "remaining_capital", "total_tax_paid",
            "first_shortfall_age", "avg_effective_tax_rate"]:
    vals = []
    for label in labels:
        v = results[label]["summary"].get(key, "N/A")
        if isinstance(v, float):
            vals.append(f"{v:>18,.1f}")
        else:
            vals.append(f"{str(v):>18}")
    print(f"{key:<35}" + "".join(vals))

# --- Year-by-year comparison ---
print("\n" + "=" * 70)
print("YEAR-BY-YEAR: INCOME & CAPITAL")
print("=" * 70)

years_data = {}
for label in labels:
    years_data[label] = {y["age"]: y for y in results[label]["years"]}

all_ages = sorted(set(
    list(years_data[labels[0]].keys()) + list(years_data[labels[1]].keys())
))

print(f"{'AGE':>4} | {'target_net':>11} {'tax':>8} {'capital':>10} | {'target_net':>11} {'tax':>8} {'capital':>10} | {'income_diff':>12} {'capital_diff':>13}")
print(f"{'':>4} | {'--- GKG ---':^31} | {'--- FT ---':^31} |")
print("-" * 115)

for age in all_ages:
    y0 = years_data[labels[0]].get(age)
    y1 = years_data[labels[1]].get(age)
    if y0 and y1:
        inc_diff = y0["target_net"] - y1["target_net"]
        cap_diff = y0["total_capital"] - y1["total_capital"]
        print(f"{age:>4} | {y0['target_net']:>11,.0f} {y0['tax_due']:>8,.0f} {y0['total_capital']:>10,.0f} | "
              f"{y1['target_net']:>11,.0f} {y1['tax_due']:>8,.0f} {y1['total_capital']:>10,.0f} | "
              f"{inc_diff:>+12,.0f} {cap_diff:>+13,.0f}")
    elif y0:
        print(f"{age:>4} | {y0['target_net']:>11,.0f} {y0['tax_due']:>8,.0f} {y0['total_capital']:>10,.0f} | {'N/A':>31} |")
    elif y1:
        print(f"{age:>4} | {'N/A':>31} | {y1['target_net']:>11,.0f} {y1['tax_due']:>8,.0f} {y1['total_capital']:>10,.0f} |")

# --- Cumulative income ---
print("\n" + "=" * 70)
print("CUMULATIVE NET INCOME")
print("=" * 70)
cum = {l: 0 for l in labels}
print(f"{'AGE':>4} | {'GKG cum':>12} {'FT cum':>12} {'diff':>12}")
print("-" * 50)
for age in all_ages:
    for label in labels:
        y = years_data[label].get(age)
        if y:
            cum[label] += y["target_net"]
    diff = cum[labels[0]] - cum[labels[1]]
    print(f"{age:>4} | {cum[labels[0]]:>12,.0f} {cum[labels[1]]:>12,.0f} {diff:>+12,.0f}")
