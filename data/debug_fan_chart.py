"""Diagnostic: check if depleted windows produce year rows for all ages,
and verify percentile computation reflects depletion correctly."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest_engine import run_backtest, extract_stress_test

cfg = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config_active.json")))
cfg["drawdown_strategy"] = "vanguard_dynamic"
cfg["personal"]["end_age"] = 94

bt = run_backtest(cfg)
meta = bt["metadata"]
ret_age = meta["retirement_age"]
end_age = meta["end_age"]
expected_ages = list(range(ret_age, end_age + 1))
n_windows = meta["n_windows"]

print(f"=== {n_windows} windows, ages {ret_age}-{end_age} ({len(expected_ages)} ages expected) ===\n")

# Check each window for missing ages
depleted_windows = []
for w in bt["windows"]:
    years = w["result"]["years"]
    ages_present = {yr["age"] for yr in years}
    missing = set(expected_ages) - ages_present
    final_yr = years[-1] if years else None
    sust = w["result"]["summary"]["sustainable"]
    if not sust:
        depleted_windows.append(w)
        print(f"  DEPLETED: {w['window_label']}  rows={len(years)}  missing_ages={sorted(missing)}  "
              f"last_age={final_yr['age'] if final_yr else '?'}  "
              f"final_cap={final_yr['total_capital']:.0f}  "
              f"shortfall_age={w['result']['summary']['first_shortfall_age']}")

print(f"\nDepleted: {len(depleted_windows)} / {n_windows}")
print(f"Sustainable: {n_windows - len(depleted_windows)} / {n_windows}")

# Deep dive: worst depleted window
if depleted_windows:
    worst = min(depleted_windows, key=lambda w: w["result"]["years"][-1]["total_capital"])
    print(f"\n=== WORST WINDOW: {worst['window_label']} ===")
    year_lookup = {yr["age"]: yr for yr in worst["result"]["years"]}
    for age in expected_ages:
        yr = year_lookup.get(age)
        if yr:
            print(f"  Age {age}: capital={yr['total_capital']:>10,.0f}  income={yr.get('net_income_achieved',0):>8,.0f}  target={yr.get('target_net',0):>8,.0f}")
        else:
            print(f"  Age {age}: *** MISSING ***")

# Now check the percentile data
print("\n=== PERCENTILE CHECK ===")
stress = extract_stress_test(bt, target_income=cfg["target_income"].get("net_annual", 0))

# Check capital_by_age directly by re-collecting
import numpy as np
capital_by_age = {age: [] for age in expected_ages}
for w in bt["windows"]:
    year_lookup = {yr["age"]: yr for yr in w["result"]["years"]}
    for age in expected_ages:
        yr = year_lookup.get(age)
        if yr:
            capital_by_age[age].append(yr["total_capital"])
        else:
            capital_by_age[age].append(0)

# Show last 10 ages: how many zeros, and what percentiles look like
print(f"\nCapital distribution at final ages (n={n_windows} per age):")
for age in expected_ages[-10:]:
    vals = capital_by_age[age]
    n_zero = sum(1 for v in vals if v < 1)
    p10 = float(np.percentile(vals, 10))
    p25 = float(np.percentile(vals, 25))
    p50 = float(np.percentile(vals, 50))
    print(f"  Age {age}: zeros={n_zero}/{len(vals)}  P10={p10:>10,.0f}  P25={p25:>10,.0f}  P50={p50:>10,.0f}")

# Compare with stress test output
print(f"\nStress test P10 at final ages:")
p10_data = stress["percentile_trajectories"]["p10"]
for pt in p10_data[-10:]:
    print(f"  Age {pt['age']}: P10 capital = {pt['total_capital']:>10,.0f}")
