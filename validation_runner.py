"""
Validation Runner — runs gold scenarios and returns structured results
with human-readable descriptions, hand calculations, and pass/fail verdicts.

Used by the /validation route to display and export a validation report.
"""

from retirement_engine import RetirementEngine, load_config


# ------------------------------------------------------------------ #
#  Helper: build a minimal config (mirrors test_qa_gold._cfg)
# ------------------------------------------------------------------ #
def _cfg(**overrides):
    cfg = {
        "personal": {
            "date_of_birth": "1960-01",
            "retirement_date": "2028-01",
            "retirement_age": 68,
            "end_age": 78,
            "currency": "GBP",
        },
        "target_income": {"net_annual": 20000, "cpi_rate": 0.0},
        "guaranteed_income": [],
        "dc_pots": [],
        "tax_free_accounts": [],
        "withdrawal_priority": [],
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
    for k, v in overrides.items():
        cfg[k] = v
    return cfg


# ------------------------------------------------------------------ #
#  Check helper
# ------------------------------------------------------------------ #
def _check(label, actual, expected, delta, unit="£"):
    """Return a check dict with pass/fail, actual, expected, delta."""
    passed = abs(actual - expected) <= delta
    return {
        "label": label,
        "passed": passed,
        "actual": actual,
        "expected": expected,
        "delta": delta,
        "unit": unit,
    }


def _check_bool(label, actual, expected):
    """Return a boolean check dict."""
    return {
        "label": label,
        "passed": actual == expected,
        "actual": str(actual),
        "expected": str(expected),
        "delta": None,
        "unit": "",
    }


def _check_gte(label, actual, threshold):
    """Return a >= check dict."""
    passed = actual >= threshold - 1  # £1 tolerance
    return {
        "label": label,
        "passed": passed,
        "actual": actual,
        "expected": f"≥ {threshold:.2f}",
        "delta": None,
        "unit": "£",
    }


# ------------------------------------------------------------------ #
#  Scenario definitions
# ------------------------------------------------------------------ #

def _scenario_01_zero_growth_depletion():
    """Scenario 1: Zero-growth exact depletion."""
    cfg = _cfg(
        target_income={"net_annual": 12000, "cpi_rate": 0.0},
        tax_free_accounts=[{
            "name": "ISA",
            "starting_balance": 30000,
            "growth_rate": 0.0,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }],
        withdrawal_priority=["ISA"],
    )
    r = RetirementEngine(cfg).run_projection()
    s = r["summary"]
    dep = s["depletion_events"][0] if s["depletion_events"] else {}

    return {
        "id": 1,
        "title": "Zero-Growth Exact Depletion",
        "description": "£30,000 tax-free ISA, £12,000/yr target income, no growth, no inflation.",
        "purpose": "Verify that a simple pot depletes at the mathematically correct time.",
        "hand_calculation": (
            "Year 1: £12,000 withdrawn → £18,000 remaining. "
            "Year 2: £12,000 withdrawn → £6,000 remaining. "
            "Year 3: £6,000 at £1,000/mo → depletes after month 6. "
            "Depletion at age 70, month 6."
        ),
        "checks": [
            _check_bool("Sustainable", s["sustainable"], False),
            _check_bool("Depleted pot", dep.get("pot", ""), "ISA"),
            _check("Depletion age", dep.get("age", 0), 70, 0, "age"),
            _check("Depletion month", dep.get("month", 0), 6, 0, "month"),
            _check("Year 1 capital", r["years"][0]["total_capital"], 18000, 1),
            _check("Year 2 capital", r["years"][1]["total_capital"], 6000, 1),
        ],
    }


def _scenario_02_no_withdrawal():
    """Scenario 2: No withdrawal — balance unchanged."""
    cfg = _cfg(
        target_income={"net_annual": 0, "cpi_rate": 0.0},
        tax_free_accounts=[{
            "name": "ISA",
            "starting_balance": 50000,
            "growth_rate": 0.0,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }],
        withdrawal_priority=["ISA"],
    )
    r = RetirementEngine(cfg).run_projection()
    s = r["summary"]

    return {
        "id": 2,
        "title": "No Withdrawal — Balance Unchanged",
        "description": "£50,000 ISA, £0 target income, no growth.",
        "purpose": "Verify that when no income is needed, capital is completely untouched.",
        "hand_calculation": "Target = £0, so no withdrawals. Balance stays at £50,000 every year.",
        "checks": [
            _check_bool("Sustainable", s["sustainable"], True),
            _check("Remaining capital", s["remaining_capital"], 50000, 1),
            _check("Year 1 capital", r["years"][0]["total_capital"], 50000, 1),
            _check("Final year capital", r["years"][-1]["total_capital"], 50000, 1),
        ],
    }


def _scenario_03_guaranteed_covers_target():
    """Scenario 3: Guaranteed income covers target — no drawdown."""
    cfg = _cfg(
        target_income={"net_annual": 12000, "cpi_rate": 0.0},
        guaranteed_income=[{
            "name": "Big Pension",
            "gross_annual": 24000,
            "indexation_rate": 0.0,
            "start_age": 68,
            "end_age": None,
            "taxable": True,
            "values_as_of": "2028-01",
        }],
        dc_pots=[{
            "name": "DC",
            "starting_balance": 100000,
            "growth_rate": 0.0,
            "annual_fees": 0.0,
            "tax_free_portion": 0.25,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }],
        withdrawal_priority=["DC"],
    )
    r = RetirementEngine(cfg).run_projection()
    s = r["summary"]

    return {
        "id": 3,
        "title": "Guaranteed Income Covers Target",
        "description": "£24,000/yr guaranteed pension (taxable), £12,000/yr target, £100,000 DC pot.",
        "purpose": "When guaranteed income exceeds the target, DC pots should be untouched.",
        "hand_calculation": (
            "Guaranteed gross: £24,000. Tax: PA=£14,500, taxable=£9,500. "
            "Tax = £6,500 × 10% + £3,000 × 20% = £1,250. "
            "Net from guaranteed = £24,000 − £1,250 = £22,750 > £12,000 target. "
            "No DC drawdown needed. DC stays at £100,000."
        ),
        "checks": [
            _check_bool("Sustainable", s["sustainable"], True),
            _check("DC remaining", s["remaining_capital"], 100000, 1),
            _check("Year 1 DC withdrawal", r["years"][0]["dc_withdrawal_gross"], 0, 0.01),
        ],
    }


def _scenario_04_priority_order():
    """Scenario 4: Priority order — ISA depletes before DC."""
    cfg = _cfg(
        personal={
            "date_of_birth": "1960-01",
            "retirement_date": "2028-01",
            "retirement_age": 68,
            "end_age": 72,
            "currency": "GBP",
        },
        target_income={"net_annual": 12000, "cpi_rate": 0.0},
        tax_free_accounts=[{
            "name": "ISA",
            "starting_balance": 5000,
            "growth_rate": 0.0,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }],
        dc_pots=[{
            "name": "DC",
            "starting_balance": 200000,
            "growth_rate": 0.0,
            "annual_fees": 0.0,
            "tax_free_portion": 0.25,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }],
        withdrawal_priority=["ISA", "DC"],
    )
    r = RetirementEngine(cfg).run_projection()
    s = r["summary"]
    dep_pots = [e["pot"] for e in s["depletion_events"]]

    return {
        "id": 4,
        "title": "Priority Order — ISA Depletes Before DC",
        "description": "ISA £5,000 (priority 1), DC £200,000 (priority 2), £12,000/yr target.",
        "purpose": "Verify withdrawal priority is respected: ISA drawn first, DC only after ISA exhausted.",
        "hand_calculation": (
            "ISA (£5,000) is first in priority. Year 1: ISA provides £5,000, "
            "DC covers the remaining shortfall. ISA depletes in year 1. "
            "Year 2+: DC provides all income. Plan is sustainable (£205,000 >> £48,000 needed)."
        ),
        "checks": [
            _check_bool("Sustainable", s["sustainable"], True),
            _check_bool("ISA depletes", "ISA" in dep_pots, True),
            _check("ISA balance after year 1", r["years"][0]["tf_balances"].get("ISA", 0), 0, 1),
            _check_bool("DC drawdown in year 2", r["years"][1]["dc_withdrawal_gross"] > 0, True),
        ],
    }


def _scenario_05_cpi_compounds():
    """Scenario 5: CPI compounds target correctly."""
    cfg = _cfg(
        personal={
            "date_of_birth": "1960-01",
            "retirement_date": "2028-01",
            "retirement_age": 68,
            "end_age": 72,
            "currency": "GBP",
        },
        target_income={"net_annual": 10000, "cpi_rate": 0.05},
        tax_free_accounts=[{
            "name": "ISA",
            "starting_balance": 200000,
            "growth_rate": 0.0,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }],
        withdrawal_priority=["ISA"],
    )
    r = RetirementEngine(cfg).run_projection()

    return {
        "id": 5,
        "title": "CPI Compounds Target Correctly",
        "description": "£10,000/yr target, 5% annual CPI inflation, £200,000 ISA.",
        "purpose": "Verify that the target income inflates correctly each year with CPI.",
        "hand_calculation": (
            "Year 1: £10,000. Year 2: £10,000 × 1.05 = £10,500. "
            "Year 3: £10,500 × 1.05 = £11,025. Targets increase monotonically."
        ),
        "checks": [
            _check("Year 1 target", r["years"][0]["target_net"], 10000, 1),
            _check("Year 2 target (5% CPI)", r["years"][1]["target_net"], 10500, 50),
            _check("Year 3 target (compounded)", r["years"][2]["target_net"], 11025, 50),
        ],
    }


def _scenario_06_baseline_realistic():
    """Scenario 6: Realistic multi-source projection (fixed config)."""
    cfg = _cfg(
        personal={
            "date_of_birth": "1960-01",
            "retirement_date": "2028-01",
            "retirement_age": 68,
            "end_age": 90,
            "currency": "GBP",
        },
        target_income={"net_annual": 20000, "cpi_rate": 0.02},
        guaranteed_income=[{
            "name": "DB Pension",
            "gross_annual": 12000,
            "indexation_rate": 0.02,
            "start_age": 68,
            "end_age": None,
            "taxable": True,
            "values_as_of": "2028-01",
        }],
        dc_pots=[{
            "name": "Main DC",
            "starting_balance": 150000,
            "growth_rate": 0.04,
            "annual_fees": 0.005,
            "tax_free_portion": 0.25,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }],
        tax_free_accounts=[{
            "name": "ISA",
            "starting_balance": 50000,
            "growth_rate": 0.03,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }],
        withdrawal_priority=["ISA", "Main DC"],
    )
    r = RetirementEngine(cfg).run_projection()
    s = r["summary"]

    return {
        "id": 6,
        "title": "Realistic Multi-Source Projection",
        "description": (
            "DB Pension £12k/yr (2% indexation), DC pot £150k (4% growth, 0.5% fees), "
            "ISA £50k (3% growth). Target £20k/yr net with 2% CPI. IoM tax."
        ),
        "purpose": (
            "Integration test combining guaranteed income, DC drawdown with tax gross-up, "
            "ISA withdrawals, growth, fees, CPI, and IoM tax in one realistic scenario."
        ),
        "hand_calculation": (
            "Sustainable plan over 23 years. ISA depletes first (~age 74) since it's priority 1. "
            "Year 0 capital ~£199k (growth applied to £200k starting, minus withdrawals). "
            "Year 5 capital ~£188k. Remaining capital ~£63k. Total IoM tax ~£25k."
        ),
        "checks": [
            _check_bool("Sustainable", s["sustainable"], True),
            _check("Projection years", s["num_years"], 23, 0, "years"),
            _check_bool("ISA depletes first", s["depletion_events"][0]["pot"], "ISA"),
            _check("Year 0 capital", r["years"][0]["total_capital"], 198617, 500),
            _check("Year 5 capital", r["years"][5]["total_capital"], 188366, 500),
            _check("Remaining capital", s["remaining_capital"], 62922, 500),
            _check("Total IoM tax", s["total_tax_paid"], 24586, 500),
        ],
    }


def _scenario_07_total_capital_depletion():
    """Scenario 7: Total-capital depletion age vs pot depletion."""
    cfg = _cfg(
        personal={
            "date_of_birth": "1960-01",
            "retirement_date": "2028-01",
            "retirement_age": 68,
            "end_age": 78,
            "currency": "GBP",
        },
        target_income={"net_annual": 12000, "cpi_rate": 0.0},
        tax_free_accounts=[
            {
                "name": "ISA-A",
                "starting_balance": 10000,
                "growth_rate": 0.0,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            },
            {
                "name": "ISA-B",
                "starting_balance": 5000,
                "growth_rate": 0.0,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            },
        ],
        withdrawal_priority=["ISA-A", "ISA-B"],
    )
    r = RetirementEngine(cfg).run_projection()
    s = r["summary"]
    dep = {e["pot"]: e["age"] for e in s["depletion_events"]}

    # Find total capital depletion age
    total_dep_age = None
    for yr in r["years"]:
        if yr["total_capital"] <= 0.01:
            total_dep_age = yr["age"]
            break

    return {
        "id": 7,
        "title": "Total Capital Depletion Age",
        "description": "ISA-A £10,000 (priority 1) + ISA-B £5,000 (priority 2), £12,000/yr target.",
        "purpose": (
            "Regression test: the 'Capital Depleted' marker must reflect when TOTAL capital "
            "hits zero, not when individual pots deplete."
        ),
        "hand_calculation": (
            "ISA-A (£10k) depletes first at age 68. ISA-B (£5k) depletes at age 69. "
            "Total capital = 0 when ISA-B (the last source) is exhausted. "
            "Total depletion age must equal ISA-B depletion age."
        ),
        "checks": [
            _check_bool("ISA-A depletes before ISA-B", dep.get("ISA-A", 999) <= dep.get("ISA-B", 999), True),
            _check_bool("Total depletion = ISA-B depletion", total_dep_age, dep.get("ISA-B")),
        ],
    }


def _scenario_08_trust_test():
    """Scenario 8: THE TRUST TEST — sustainable means net >= target."""
    # Real-world config
    real_cfg = load_config("config_active.json")
    real_r = RetirementEngine(real_cfg).run_projection()
    real_s = real_r["summary"]

    # Synthetic DC-only
    synth_cfg = _cfg(
        personal={
            "date_of_birth": "1960-01",
            "retirement_date": "2028-01",
            "retirement_age": 68,
            "end_age": 90,
            "currency": "GBP",
        },
        target_income={"net_annual": 20000, "cpi_rate": 0.03},
        dc_pots=[{
            "name": "Big DC",
            "starting_balance": 800000,
            "growth_rate": 0.04,
            "annual_fees": 0.005,
            "tax_free_portion": 0.25,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }],
        withdrawal_priority=["Big DC"],
    )
    synth_r = RetirementEngine(synth_cfg).run_projection()
    synth_s = synth_r["summary"]

    checks = [
        _check_bool("Real config sustainable", real_s["sustainable"], True),
        _check_bool("Synthetic config sustainable", synth_s["sustainable"], True),
    ]

    # Check every year of real config
    real_all_met = True
    for yr in real_r["years"]:
        if yr["net_income_achieved"] < yr["target_net"] - 1:
            real_all_met = False
            break
    checks.append(_check_bool("Real: net ≥ target EVERY year", real_all_met, True))

    # Check every year of synthetic config
    synth_all_met = True
    max_overshoot_pct = 0
    for yr in synth_r["years"]:
        if yr["net_income_achieved"] < yr["target_net"] - 1:
            synth_all_met = False
        overshoot_pct = (yr["net_income_achieved"] - yr["target_net"]) / yr["target_net"] * 100
        max_overshoot_pct = max(max_overshoot_pct, overshoot_pct)
    checks.append(_check_bool("Synthetic: net ≥ target EVERY year", synth_all_met, True))
    checks.append(_check_bool("Gross-up accuracy (overshoot < 2%)", max_overshoot_pct < 2, True))

    return {
        "id": 8,
        "title": "THE TRUST TEST — Sustainable Means Net ≥ Target",
        "description": (
            "If the engine says 'sustainable', then every single year must deliver "
            "net income ≥ target. Tested against the real configuration AND a synthetic "
            "DC-only config with 3% CPI, 4% growth, 0.5% fees."
        ),
        "purpose": (
            "This is the test a real user cares about most: 'Can I rely on this number?' "
            "It verifies that the engine's gross-up solver correctly accounts for tax "
            "so the net income you actually receive meets your target."
        ),
        "hand_calculation": (
            "For each year: net_income_achieved = guaranteed_gross + DC_gross + TF_withdrawals − IoM_tax. "
            "This must be ≥ target_net for every year of the plan. "
            "Also checks that the gross-up doesn't overshoot by more than 2%."
        ),
        "checks": checks,
    }


def _scenario_09_dc_tax_grossup():
    """Scenario 9: DC tax gross-up — hand-calculated verification."""
    cfg = _cfg(
        personal={
            "date_of_birth": "1960-01",
            "retirement_date": "2028-01",
            "retirement_age": 68,
            "end_age": 72,
            "currency": "GBP",
        },
        target_income={"net_annual": 20000, "cpi_rate": 0.0},
        dc_pots=[{
            "name": "DC",
            "starting_balance": 500000,
            "growth_rate": 0.0,
            "annual_fees": 0.0,
            "tax_free_portion": 0.25,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }],
        withdrawal_priority=["DC"],
    )
    r = RetirementEngine(cfg).run_projection()
    yr0 = r["years"][0]

    return {
        "id": 9,
        "title": "DC Tax Gross-Up Verification",
        "description": "£500,000 DC pot, 25% tax-free portion, £20,000/yr net target, no growth.",
        "purpose": (
            "Verify that the engine correctly 'grosses up' DC withdrawals to account for tax, "
            "so the net income actually received equals the target."
        ),
        "hand_calculation": (
            "Need gross G where G − tax(0.75G) = £20,000. "
            "Taxable portion = 0.75G. With IoM bands: PA=£14,500, lower=£6,500 @ 10%. "
            "If 0.75G < £21,000: tax = (0.75G − 14,500) × 10%. "
            "Solving: 0.925G + 1,450 = 20,000 → G = £20,054.05. "
            "Tax = £54.05. Tax-free portion = £5,013.51. Taxable = £15,040.54."
        ),
        "checks": [
            _check("Net income = target", yr0["net_income_achieved"], 20000, 5),
            _check("Gross withdrawal", yr0["dc_withdrawal_gross"], 20054, 50),
            _check("Tax due", yr0["tax_due"], 54, 10),
            _check("Taxable income", yr0["total_taxable_income"], 15041, 50),
            _check("Tax-free portion", yr0["dc_tax_free_portion"], 5014, 50),
        ],
    }


def _scenario_10_growth_compounds():
    """Scenario 10: Growth compounds correctly."""
    cfg = _cfg(
        target_income={"net_annual": 0, "cpi_rate": 0.0},
        tax_free_accounts=[{
            "name": "ISA",
            "starting_balance": 100000,
            "growth_rate": 0.05,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }],
        withdrawal_priority=["ISA"],
    )
    r = RetirementEngine(cfg).run_projection()

    return {
        "id": 10,
        "title": "Investment Growth Compounds Correctly",
        "description": "£100,000 ISA at 5% annual growth, no withdrawals.",
        "purpose": "Verify monthly compound growth produces the correct annual balance.",
        "hand_calculation": (
            "Monthly rate = (1.05)^(1/12) − 1. After 12 months: £100,000 × 1.05 = £105,000. "
            "Year 2: £105,000 × 1.05 = £110,250. Year 5: £100,000 × 1.05^5 = £127,628."
        ),
        "checks": [
            _check("Year 1 balance", r["years"][0]["total_capital"], 105000, 5),
            _check("Year 2 balance", r["years"][1]["total_capital"], 110250, 10),
            _check("Year 5 balance", r["years"][4]["total_capital"], 127628, 20),
        ],
    }


def _scenario_11_fees_reduce_balance():
    """Scenario 11: Fees reduce balance correctly."""
    cfg = _cfg(
        target_income={"net_annual": 0, "cpi_rate": 0.0},
        dc_pots=[{
            "name": "DC",
            "starting_balance": 100000,
            "growth_rate": 0.0,
            "annual_fees": 0.01,
            "tax_free_portion": 0.25,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }],
        withdrawal_priority=["DC"],
    )
    r = RetirementEngine(cfg).run_projection()
    yr0 = r["years"][0]
    pnl = yr0["pot_pnl"]["DC"]

    return {
        "id": 11,
        "title": "Annual Fees Reduce Balance Correctly",
        "description": "£100,000 DC pot, 1% annual fee, no growth, no withdrawals.",
        "purpose": "Verify that platform fees are deducted correctly via monthly compounding.",
        "hand_calculation": (
            "Monthly fee rate = (1.01)^(1/12) − 1 ≈ 0.0830%. "
            "After 12 months: £100,000 × (1 − 0.000830)^12 ≈ £99,008. "
            "Fees charged ≈ £992. Slightly more than 1% due to monthly compounding on reducing balance."
        ),
        "checks": [
            _check("Year 1 balance after fees", yr0["total_capital"], 99008, 50),
            _check("Fees charged in year 1", pnl["fees"], 992, 50),
            _check("Growth (should be zero)", pnl["growth"], 0, 1),
        ],
    }


def _scenario_12_shortfall_reporting():
    """Scenario 12: Shortfall reporting."""
    cfg = _cfg(
        personal={
            "date_of_birth": "1960-01",
            "retirement_date": "2028-01",
            "retirement_age": 68,
            "end_age": 75,
            "currency": "GBP",
        },
        target_income={"net_annual": 20000, "cpi_rate": 0.0},
        tax_free_accounts=[{
            "name": "ISA",
            "starting_balance": 5000,
            "growth_rate": 0.0,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }],
        withdrawal_priority=["ISA"],
    )
    r = RetirementEngine(cfg).run_projection()
    s = r["summary"]
    shortfall_count = sum(1 for yr in r["years"] if yr["shortfall"])

    # Check post-depletion years
    post_depletion_ok = True
    depleted = False
    for yr in r["years"]:
        if depleted and yr["net_income_achieved"] > 1:
            post_depletion_ok = False
        if yr["total_capital"] <= 0.01:
            depleted = True

    return {
        "id": 12,
        "title": "Shortfall Reporting",
        "description": "£5,000 ISA, £20,000/yr target, plan to age 75. Capital runs out quickly.",
        "purpose": "Verify that when capital is insufficient, shortfall is correctly detected and reported.",
        "hand_calculation": (
            "£5,000 ISA with £20,000/yr target. ISA depletes in year 1 (only £5,000 available). "
            "Years 2-7: no capital, no guaranteed income → net = £0, all flagged as shortfall. "
            "Sustainable must be False."
        ),
        "checks": [
            _check_bool("Sustainable", s["sustainable"], False),
            _check_bool("First shortfall age exists", s["first_shortfall_age"] is not None, True),
            _check_bool("Shortfall years detected", shortfall_count > 0, True),
            _check_bool("Post-depletion net = £0", post_depletion_ok, True),
            _check_bool("Year 1 has some income", r["years"][0]["net_income_achieved"] > 0, True),
        ],
    }


def _scenario_13_delayed_guaranteed():
    """Scenario 13: Delayed guaranteed income changes drawdown."""
    cfg = _cfg(
        personal={
            "date_of_birth": "1960-01",
            "retirement_date": "2028-01",
            "retirement_age": 68,
            "end_age": 78,
            "currency": "GBP",
        },
        target_income={"net_annual": 20000, "cpi_rate": 0.0},
        guaranteed_income=[{
            "name": "State Pension",
            "gross_annual": 20000,
            "indexation_rate": 0.0,
            "start_age": 70,
            "end_age": None,
            "taxable": True,
            "values_as_of": "2028-01",
        }],
        dc_pots=[{
            "name": "DC",
            "starting_balance": 200000,
            "growth_rate": 0.0,
            "annual_fees": 0.0,
            "tax_free_portion": 0.25,
            "allocation": {"mode": "manual", "manual_override": True},
            "values_as_of": "2028-01",
        }],
        withdrawal_priority=["DC"],
    )
    r = RetirementEngine(cfg).run_projection()
    yr_68 = r["years"][0]
    yr_70 = r["years"][2]
    yr_72 = r["years"][4]

    # Check net meets target every non-shortfall year
    all_met = True
    for yr in r["years"]:
        if not yr["shortfall"] and yr["net_income_achieved"] < yr["target_net"] - 1:
            all_met = False

    return {
        "id": 13,
        "title": "Delayed Guaranteed Income",
        "description": (
            "State Pension £20,000/yr starting at age 70, retirement at 68. "
            "DC pot £200,000 (no growth). Target £20,000/yr."
        ),
        "purpose": (
            "Verify that DC drawdown is higher before guaranteed income starts, "
            "and drops significantly once it kicks in — simulating a real state pension gap."
        ),
        "hand_calculation": (
            "Ages 68-69: No guaranteed income. DC must provide full £20,000 net (grossed up for tax). "
            "Age 70+: State Pension provides £20,000 gross. After tax, this nearly covers the target. "
            "DC drawdown should drop by at least 50%."
        ),
        "checks": [
            _check_bool("Net ≥ target every year", all_met, True),
            _check("Guaranteed at age 68", yr_68["guaranteed_total"], 0, 1),
            _check("Guaranteed at age 70", yr_70["guaranteed_total"], 20000, 100),
            _check_bool(
                "DC drawdown higher before guaranteed",
                yr_68["dc_withdrawal_gross"] > yr_70["dc_withdrawal_gross"],
                True,
            ),
            _check_bool(
                "DC drawdown drops >50% after guaranteed",
                yr_72["dc_withdrawal_gross"] < yr_68["dc_withdrawal_gross"] * 0.5,
                True,
            ),
        ],
    }


# ------------------------------------------------------------------ #
#  Public API
# ------------------------------------------------------------------ #

ALL_SCENARIOS = [
    _scenario_01_zero_growth_depletion,
    _scenario_02_no_withdrawal,
    _scenario_03_guaranteed_covers_target,
    _scenario_04_priority_order,
    _scenario_05_cpi_compounds,
    _scenario_06_baseline_realistic,
    _scenario_07_total_capital_depletion,
    _scenario_08_trust_test,
    _scenario_09_dc_tax_grossup,
    _scenario_10_growth_compounds,
    _scenario_11_fees_reduce_balance,
    _scenario_12_shortfall_reporting,
    _scenario_13_delayed_guaranteed,
]


def run_all_scenarios() -> dict:
    """Run all validation scenarios and return structured results.

    Returns:
        {
            "scenarios": [scenario_result, ...],
            "total_checks": int,
            "passed_checks": int,
            "failed_checks": int,
            "all_passed": bool,
        }
    """
    results = []
    total = 0
    passed = 0

    for fn in ALL_SCENARIOS:
        try:
            scenario = fn()
        except Exception as e:
            scenario = {
                "id": "?",
                "title": fn.__doc__ or fn.__name__,
                "description": "",
                "purpose": "",
                "hand_calculation": "",
                "checks": [_check_bool("Scenario execution", False, True)],
                "error": str(e),
            }
        for c in scenario["checks"]:
            total += 1
            if c["passed"]:
                passed += 1
        results.append(scenario)

    return {
        "scenarios": results,
        "total_checks": total,
        "passed_checks": passed,
        "failed_checks": total - passed,
        "all_passed": passed == total,
    }
