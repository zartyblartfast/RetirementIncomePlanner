from retirement_engine import RetirementEngine, load_config
import copy

cfg = load_config("config_active.json")
cfg["personal"]["end_age"] = 120
r = RetirementEngine(cfg).run_projection()

for y in r["years"]:
    if 88 <= y["age"] <= 100:
        dc = sum(y["pot_balances"].values())
        tf = sum(y["tf_balances"].values())
        print(f"age {y['age']:3d}  capital={y['total_capital']:12.2f}  "
              f"dc={dc:10.2f}  tf={tf:10.2f}")
