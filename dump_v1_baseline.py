"""Dump V1 engine output for cross-check with V2 TypeScript port."""
import json
from retirement_engine import RetirementEngine, load_config
from drawdown_strategies import normalize_config

cfg = load_config("config_default.json")
normalize_config(cfg)
engine = RetirementEngine(cfg)
result = engine.run_projection()
s = result["summary"]
y = result["years"]

out = {
    "summary": {
        "sustainable": s["sustainable"],
        "first_shortfall_age": s["first_shortfall_age"],
        "end_age": s["end_age"],
        "anchor_age": s["anchor_age"],
        "is_post_retirement": s["is_post_retirement"],
        "num_years": s["num_years"],
        "remaining_capital": s["remaining_capital"],
        "total_tax_paid": s["total_tax_paid"],
        "total_uk_tax_paid": s["total_uk_tax_paid"],
        "uk_tax_saving": s["uk_tax_saving"],
        "avg_effective_tax_rate": s["avg_effective_tax_rate"],
        "first_pot_exhausted_age": s["first_pot_exhausted_age"],
        "remaining_pots": s["remaining_pots"],
        "remaining_tf": s["remaining_tf"],
        "depletion_events": s["depletion_events"],
    },
    "year1": {
        "age": y[0]["age"],
        "target_net": y[0]["target_net"],
        "guaranteed_total": y[0]["guaranteed_total"],
        "guaranteed_income": y[0]["guaranteed_income"],
        "dc_withdrawal_gross": y[0]["dc_withdrawal_gross"],
        "dc_tax_free_portion": y[0]["dc_tax_free_portion"],
        "tf_withdrawal": y[0]["tf_withdrawal"],
        "total_taxable_income": y[0]["total_taxable_income"],
        "tax_due": y[0]["tax_due"],
        "uk_tax_due": y[0]["uk_tax_due"],
        "net_income_achieved": y[0]["net_income_achieved"],
        "shortfall": y[0]["shortfall"],
        "total_capital": y[0]["total_capital"],
        "pot_balances": y[0]["pot_balances"],
        "tf_balances": y[0]["tf_balances"],
    },
    "last_year": {
        "age": y[-1]["age"],
        "target_net": y[-1]["target_net"],
        "net_income_achieved": y[-1]["net_income_achieved"],
        "total_capital": y[-1]["total_capital"],
        "shortfall": y[-1]["shortfall"],
    },
}

print(json.dumps(out, indent=2))
