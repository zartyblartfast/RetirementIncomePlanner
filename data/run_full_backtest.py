"""Run full backtest across all viable historical windows and print summary."""
import json
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest_engine import run_backtest, extract_percentiles

with open("config_active.json") as f:
    cfg = json.load(f)

start = time.time()
result = run_backtest(cfg)
elapsed = time.time() - start

meta = result["metadata"]
print(f"Full backtest: {meta['n_windows']} windows, {meta['n_years']} years each")
print(f"Range: {meta['start_range']}-{meta['end_range']}")
print(f"Time: {elapsed:.2f}s ({elapsed/meta['n_windows']:.3f}s per window)")

pcts = extract_percentiles(result)
print(f"\nSustainability: {pcts['sustainability_rate']*100:.1f}% of periods")
print(f"Worst: {pcts['worst_window']['label']} "
      f"(depletion age {pcts['worst_window']['depletion_age']})")
print(f"Best:  {pcts['best_window']['label']} "
      f"(final capital: £{pcts['best_window']['final_capital']:,.0f})")

p50 = pcts["percentile_trajectories"]["p50"]
p25 = pcts["percentile_trajectories"]["p25"]
p75 = pcts["percentile_trajectories"]["p75"]
print(f"\nCapital at key ages (P25 / P50 / P75):")
for i, pt in enumerate(p50):
    if pt["age"] % 5 == 0 or pt["age"] == pcts["ages"][-1]:
        print(f"  Age {pt['age']}: "
              f"£{p25[i]['total_capital']:>10,.0f} / "
              f"£{pt['total_capital']:>10,.0f} / "
              f"£{p75[i]['total_capital']:>10,.0f}")
