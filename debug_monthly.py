from retirement_engine import RetirementEngine, load_config

cfg = load_config("config_active.json")

# quick overrides
cfg["target_income_net"] = 12000
cfg["dc_pots"][0]["value"] = 120000
cfg["dc_pots"][0]["growth_rate"] = 0
cfg["dc_pots"][0]["annual_fee"] = 0

result = RetirementEngine(cfg).run_projection(include_monthly=True)

rows = result["monthly_rows"]

# Check for negative balances
negatives = [r for r in rows if any(b < 0 for b in r["dc_balances"].values())
             or any(b < 0 for b in r["tf_balances"].values())]
print(f"Negative balances found: {len(negatives)}")

# Show depletion zone
for i, row in enumerate(rows):
    if row["total_capital"] <= 0:
        print(f"\nDEPLETION: {row['year']}-{row['month']:02d} age {row['age']}")
        for r in rows[max(0, i-6):i+3]:
            print(
                f"  {r['year']}-{r['month']:02d} "
                f"capital={r['total_capital']} "
                f"dc={r['dc_drawdown_this_month']} "
                f"tf={r.get('tf_drawdown_this_month')} "
                f"depleted={r['depleted_this_month']}"
            )
        break
