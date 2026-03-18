"""
Gold-scenario QA harness for the retirement projection engine.

Purpose
-------
A small set of named scenarios with explicit expected checkpoints.
Catches quiet regressions in projection logic before they reach the dashboard.

How to run
----------
    python -m pytest test_qa_gold.py -v

When to run
-----------
Run this before accepting any change to retirement_engine.py or related
projection logic.  It is deliberately small so there is no excuse to skip it.

Design principles
-----------------
- Each scenario is self-contained with an inline config.
- Expected values are explicit constants, not computed from the engine.
- Tolerances are generous for monetary values (floating-point, rounding).
- Structural checks (sustainable, depletion pot name, ages) are exact.
- The baseline-realistic scenario uses wider tolerances to avoid brittleness.
"""

import unittest
from retirement_engine import RetirementEngine


# ---------------------------------------------------------------------------
#  Helper: build a minimal config, same as test_engine.py
# ---------------------------------------------------------------------------
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


# ===================================================================
#  Scenario 1: Zero-growth exact depletion
#  £30k TF ISA, £12k/yr target, 0 CPI, 0 growth.
#  Year 1: 12k withdrawn → 18k
#  Year 2: 12k withdrawn → 6k
#  Year 3: 6 months × £1k → 0, depleted month 6
# ===================================================================
class TestGold_ZeroGrowthExactDepletion(unittest.TestCase):
    """Known-answer: TF pot depletes at a predictable month."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
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
        cls.r = RetirementEngine(cls.cfg).run_projection()
        cls.s = cls.r["summary"]

    def test_not_sustainable(self):
        self.assertFalse(self.s["sustainable"])

    def test_depletion_pot(self):
        self.assertEqual(self.s["depletion_events"][0]["pot"], "ISA")

    def test_depletion_age(self):
        self.assertEqual(self.s["depletion_events"][0]["age"], 70)

    def test_depletion_month(self):
        # Monthly source allocation draws £1k/month from £6k balance.
        # Pot depletes at month 6 (6 × £1k = £6k).
        self.assertEqual(self.s["depletion_events"][0]["month"], 6)

    def test_year1_capital(self):
        self.assertAlmostEqual(
            self.r["years"][0]["total_capital"], 18000, delta=1)

    def test_year2_capital(self):
        self.assertAlmostEqual(
            self.r["years"][1]["total_capital"], 6000, delta=1)


# ===================================================================
#  Scenario 2: No withdrawal — balance unchanged
#  Target = 0, single TF ISA £50k, 0 growth.
#  No withdrawals should occur.  Balance stays constant.
# ===================================================================
class TestGold_NoWithdrawalBalanceUnchanged(unittest.TestCase):
    """No income need → capital untouched throughout."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
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
        cls.r = RetirementEngine(cls.cfg).run_projection()
        cls.s = cls.r["summary"]

    def test_sustainable(self):
        self.assertTrue(self.s["sustainable"])

    def test_no_depletion_events(self):
        self.assertEqual(len(self.s["depletion_events"]), 0)

    def test_remaining_capital_unchanged(self):
        self.assertAlmostEqual(self.s["remaining_capital"], 50000, delta=1)

    def test_every_year_capital_50k(self):
        for yr in self.r["years"]:
            self.assertAlmostEqual(yr["total_capital"], 50000, delta=1)

    def test_no_tf_withdrawal(self):
        for yr in self.r["years"]:
            self.assertAlmostEqual(yr["tf_withdrawal"], 0, delta=0.01)


# ===================================================================
#  Scenario 3: Guaranteed income covers target — no drawdown
#  Guaranteed = £24k/yr taxable, target = £12k/yr, DC pot present.
#  DC pot should be untouched.
# ===================================================================
class TestGold_GuaranteedCoversTarget(unittest.TestCase):
    """When guaranteed income exceeds target, DC pots stay untouched."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
            target_income={"net_annual": 12000, "cpi_rate": 0.0},
            guaranteed_income=[{
                "name": "Big Pension",
                "gross_annual": 24000,
                "indexation_rate": 0.0,
                "start_date": "2028-01",
                "end_date": None,
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
        cls.r = RetirementEngine(cls.cfg).run_projection()
        cls.s = cls.r["summary"]

    def test_sustainable(self):
        self.assertTrue(self.s["sustainable"])

    def test_dc_untouched(self):
        self.assertAlmostEqual(self.s["remaining_capital"], 100000, delta=1)

    def test_no_dc_withdrawal_any_year(self):
        for yr in self.r["years"]:
            self.assertAlmostEqual(yr["dc_withdrawal_gross"], 0, delta=0.01)


# ===================================================================
#  Scenario 4: Priority order — ISA depletes before DC
#  ISA (£5k, 0 growth) first, DC (£200k, 0 growth) second.
#  Target = £12k/yr, 0 CPI.
#  ISA should deplete at end of year 1, DC takes over year 2+.
# ===================================================================
class TestGold_PriorityOrderISAFirst(unittest.TestCase):
    """ISA is drawn first per priority; DC only used after ISA exhausted."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
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
        cls.r = RetirementEngine(cls.cfg).run_projection()
        cls.s = cls.r["summary"]

    def test_isa_depletes_first(self):
        dep_pots = [e["pot"] for e in self.s["depletion_events"]]
        self.assertIn("ISA", dep_pots)

    def test_isa_depletes_before_dc(self):
        dep_pots = [e["pot"] for e in self.s["depletion_events"]]
        if "DC" in dep_pots:
            isa_age = next(e["age"] for e in self.s["depletion_events"]
                          if e["pot"] == "ISA")
            dc_age = next(e["age"] for e in self.s["depletion_events"]
                          if e["pot"] == "DC")
            self.assertLessEqual(isa_age, dc_age)

    def test_isa_zero_after_year1(self):
        yr1_isa = self.r["years"][0]["tf_balances"].get("ISA", 0)
        self.assertAlmostEqual(yr1_isa, 0, delta=1)

    def test_dc_drawdown_year2(self):
        """After ISA gone, DC must supply withdrawals."""
        yr2 = self.r["years"][1]
        self.assertGreater(yr2["dc_withdrawal_gross"], 0)

    def test_sustainable(self):
        self.assertTrue(self.s["sustainable"])


# ===================================================================
#  Scenario 5: CPI compounds target correctly
#  £100k TF ISA, £10k target, 5% CPI, 0 growth.
#  Year 1 target: £10000, Year 2: £10500, Year 3: £11025.
# ===================================================================
class TestGold_CPICompoundsTarget(unittest.TestCase):
    """Verify CPI inflates the annual target correctly over time."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
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
        cls.r = RetirementEngine(cls.cfg).run_projection()

    def test_year1_target(self):
        self.assertAlmostEqual(
            self.r["years"][0]["target_net"], 10000, delta=1)

    def test_year2_target_inflated(self):
        self.assertAlmostEqual(
            self.r["years"][1]["target_net"], 10500, delta=50)

    def test_year3_target_compounded(self):
        self.assertAlmostEqual(
            self.r["years"][2]["target_net"], 11025, delta=50)

    def test_targets_increase_monotonically(self):
        targets = [yr["target_net"] for yr in self.r["years"]]
        for i in range(1, len(targets)):
            self.assertGreater(targets[i], targets[i - 1])


# ===================================================================
#  Scenario 6: Realistic multi-source projection (fixed config)
#  DB Pension £12k/yr (2% indexation), DC £150k (4% growth, 0.5% fees),
#  ISA £50k (3% growth). Target £20k/yr net, 2% CPI. IoM tax.
#
#  Expected baseline:
#    sustainable: True
#    num_years: 23
#    ISA depletes first (~age 74)
#    yr0 capital: ~£198,617
#    yr5 capital: ~£188,366
#    remaining_capital: ~£63,271
#    total_tax: ~£25,000
# ===================================================================
class TestGold_BaselineRealistic(unittest.TestCase):
    """Fixed multi-source config — deterministic, no user data dependency."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
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
                "start_date": "2028-01",
                "end_date": None,
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
        cls.r = RetirementEngine(cls.cfg).run_projection()
        cls.s = cls.r["summary"]

    def test_sustainable(self):
        self.assertTrue(self.s["sustainable"])

    def test_num_years(self):
        self.assertEqual(self.s["num_years"], 23)

    def test_isa_depletes_first(self):
        self.assertGreater(len(self.s["depletion_events"]), 0)
        self.assertEqual(self.s["depletion_events"][0]["pot"], "ISA")

    def test_yr0_capital(self):
        self.assertAlmostEqual(
            self.r["years"][0]["total_capital"], 198617, delta=500)

    def test_yr5_capital(self):
        self.assertAlmostEqual(
            self.r["years"][5]["total_capital"], 188366, delta=500)

    def test_remaining_capital(self):
        self.assertAlmostEqual(
            self.s["remaining_capital"], 62922, delta=500)

    def test_total_tax(self):
        self.assertAlmostEqual(
            self.s["total_tax_paid"], 24994, delta=500)

    def test_yr0_guaranteed_income_positive(self):
        self.assertGreater(self.r["years"][0]["guaranteed_total"], 0)

    def test_yr0_net_meets_target(self):
        yr0 = self.r["years"][0]
        self.assertGreaterEqual(yr0["net_income_achieved"], yr0["target_net"] - 1)


# ===================================================================
#  Scenario 7: Regression — total-capital depletion age vs pot depletion
#  Two pots deplete at different ages. The "Capital Depleted" marker
#  should be based on when TOTAL capital hits zero, not when the last
#  individual pot depletes.
#
#  ISA-A (£10k, priority 1) depletes first.
#  ISA-B (£5k, priority 2) depletes later.
#  Total capital depletion = when ISA-B hits zero (since it's the last).
#  The dashboard must use total_capital <= epsilon, not max(pot depletion ages).
# ===================================================================
class TestGold_TotalCapitalDepletionAge(unittest.TestCase):
    """Regression: depletion marker must reflect total capital, not last pot event."""

    # Match the dashboard logic: capital is "effectively depleted" when it
    # can't cover one month of target income.
    DEPLETION_EPSILON = 0.01  # For this scenario (TF-only, 0 growth), exact zero is reached

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
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
        cls.r = RetirementEngine(cls.cfg).run_projection()
        cls.s = cls.r["summary"]

    def test_isa_a_depletes_before_isa_b(self):
        dep = {e["pot"]: e["age"] for e in self.s["depletion_events"]}
        self.assertIn("ISA-A", dep)
        self.assertIn("ISA-B", dep)
        self.assertLessEqual(dep["ISA-A"], dep["ISA-B"])

    def test_total_capital_depletion_age(self):
        """The dashboard logic: first year where total_capital <= epsilon."""
        depletion_age = None
        for yr in self.r["years"]:
            if yr["total_capital"] <= self.DEPLETION_EPSILON:
                depletion_age = yr["age"]
                break
        # Total capital depletes when ISA-B (the last source) hits zero.
        # This must equal the ISA-B depletion age, NOT be later.
        isa_b_dep = next(e["age"] for e in self.s["depletion_events"]
                         if e["pot"] == "ISA-B")
        self.assertEqual(depletion_age, isa_b_dep)

    def test_depletion_age_not_after_last_pot(self):
        """Ensure total-capital depletion is never LATER than last pot depletion."""
        depletion_age = None
        for yr in self.r["years"]:
            if yr["total_capital"] <= self.DEPLETION_EPSILON:
                depletion_age = yr["age"]
                break
        max_pot_age = max(e["age"] for e in self.s["depletion_events"])
        if depletion_age is not None:
            self.assertLessEqual(depletion_age, max_pot_age)


# ===================================================================
#  Scenario 8: THE TRUST TEST — sustainable means net >= target
#  If the engine says "sustainable", then every single year must
#  deliver net_income_achieved >= target_net.  This is the test a
#  real user cares about: "Can I rely on this number?"
#
#  We run this against a fixed multi-source config AND against a
#  synthetic config with only DC pots (taxable path).
# ===================================================================
class TestGold_SustainableMeansNetMeetsTarget(unittest.TestCase):
    """THE TRUST TEST: sustainable ⟹ net income ≥ target every year."""

    @classmethod
    def setUpClass(cls):
        # Multi-source config (same as Scenario 6)
        cls.real_cfg = _cfg(
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
                "start_date": "2028-01",
                "end_date": None,
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
        cls.real_r = RetirementEngine(cls.real_cfg).run_projection()
        cls.real_s = cls.real_r["summary"]

        # Synthetic: DC-only, taxable path, plenty of capital
        cls.synth_cfg = _cfg(
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
        cls.synth_r = RetirementEngine(cls.synth_cfg).run_projection()
        cls.synth_s = cls.synth_r["summary"]

    def test_real_config_is_sustainable(self):
        self.assertTrue(self.real_s["sustainable"])

    def test_real_net_meets_target_every_year(self):
        """Every year of the real config: net_income_achieved >= target_net."""
        for yr in self.real_r["years"]:
            self.assertGreaterEqual(
                yr["net_income_achieved"], yr["target_net"] - 1,
                f"Age {yr['age']}: net {yr['net_income_achieved']:.2f} "
                f"< target {yr['target_net']:.2f}")

    def test_synth_is_sustainable(self):
        self.assertTrue(self.synth_s["sustainable"])

    def test_synth_net_meets_target_every_year(self):
        """Every year of the synthetic DC config: net >= target."""
        for yr in self.synth_r["years"]:
            self.assertGreaterEqual(
                yr["net_income_achieved"], yr["target_net"] - 1,
                f"Age {yr['age']}: net {yr['net_income_achieved']:.2f} "
                f"< target {yr['target_net']:.2f}")

    def test_synth_net_not_wildly_over_target(self):
        """Net should not massively exceed target (gross-up accuracy)."""
        for yr in self.synth_r["years"]:
            overshoot = yr["net_income_achieved"] - yr["target_net"]
            self.assertLess(
                overshoot, yr["target_net"] * 0.02,  # < 2% overshoot
                f"Age {yr['age']}: overshoot £{overshoot:.2f} too large")


# ===================================================================
#  Scenario 9: DC tax gross-up — hand-calculated verification
#  £500k DC pot, £20k net target, 0 growth, 0 CPI, 25% tax-free.
#  IoM tax: PA=14500, lower=6500@10%, higher@20%.
#
#  Hand calculation (year 1):
#    Need gross G where G - tax(0.75G) = 20000
#    Taxable = 0.75G.  If 0.75G is in lower band (< 21000):
#    Tax = (0.75G - 14500) × 0.10
#    G - 0.075G + 1450 = 20000 → G = 20054.05
#    Tax = (15040.54 - 14500) × 0.10 = 54.05
#    Net = 20054.05 - 54.05 = 20000.00 ✓
# ===================================================================
class TestGold_DCTaxGrossUp(unittest.TestCase):
    """Verify DC gross-up produces correct tax and net income."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
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
        cls.r = RetirementEngine(cls.cfg).run_projection()
        cls.yr0 = cls.r["years"][0]

    def test_net_equals_target(self):
        self.assertAlmostEqual(
            self.yr0["net_income_achieved"], 20000, delta=5)

    def test_gross_withdrawal_matches_hand_calc(self):
        # Hand-calc: G ≈ 20054
        self.assertAlmostEqual(
            self.yr0["dc_withdrawal_gross"], 20054, delta=50)

    def test_tax_matches_hand_calc(self):
        # Hand-calc: tax ≈ 54
        self.assertAlmostEqual(self.yr0["tax_due"], 54, delta=10)

    def test_taxable_income_correct(self):
        # Taxable = 0.75 × gross ≈ 15041
        self.assertAlmostEqual(
            self.yr0["total_taxable_income"], 15041, delta=50)

    def test_tax_free_portion_correct(self):
        # Tax-free = 0.25 × gross ≈ 5014
        self.assertAlmostEqual(
            self.yr0["dc_tax_free_portion"], 5014, delta=50)

    def test_sustainable(self):
        self.assertTrue(self.r["summary"]["sustainable"])


# ===================================================================
#  Scenario 10: Growth compounds correctly
#  £100k ISA, 5% annual growth, 0 withdrawals (target=0), 0 CPI.
#  Monthly compounding: 100000 × (1.05)^(1/12)^12 = 105000 exactly.
# ===================================================================
class TestGold_GrowthCompoundsCorrectly(unittest.TestCase):
    """Verify investment growth is applied correctly via monthly compounding."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
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
        cls.r = RetirementEngine(cls.cfg).run_projection()

    def test_year1_balance(self):
        # 100000 × 1.05 = 105000
        self.assertAlmostEqual(
            self.r["years"][0]["total_capital"], 105000, delta=5)

    def test_year2_balance(self):
        # 105000 × 1.05 = 110250
        self.assertAlmostEqual(
            self.r["years"][1]["total_capital"], 110250, delta=10)

    def test_year5_balance(self):
        # 100000 × 1.05^5 = 127628.16
        self.assertAlmostEqual(
            self.r["years"][4]["total_capital"], 127628, delta=20)

    def test_growth_pnl_year1(self):
        pnl = self.r["years"][0]["pot_pnl"]["ISA"]
        self.assertAlmostEqual(pnl["growth"], 5000, delta=10)


# ===================================================================
#  Scenario 11: Fees reduce balance correctly
#  £100k DC pot, 0 growth, 1% annual fee, target=0 (no withdrawals).
#  After 1 year: 100000 × (1 - monthly_fee)^12
#  where monthly_fee = (1.01)^(1/12) - 1 ≈ 0.000830.
#  Expected: ~£99,008 (slightly more than 1% due to compounding).
# ===================================================================
class TestGold_FeesReduceBalance(unittest.TestCase):
    """Verify annual fees are deducted correctly via monthly compounding."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
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
        cls.r = RetirementEngine(cls.cfg).run_projection()

    def test_year1_balance_after_fees(self):
        # Slightly more than 1% deducted due to monthly compounding
        bal = self.r["years"][0]["total_capital"]
        self.assertAlmostEqual(bal, 99008, delta=50)
        self.assertLess(bal, 99100)   # clearly less than 99.1k
        self.assertGreater(bal, 98900)  # but not as much as 1.1%

    def test_fees_pnl_year1(self):
        pnl = self.r["years"][0]["pot_pnl"]["DC"]
        self.assertAlmostEqual(pnl["fees"], 992, delta=50)
        self.assertAlmostEqual(pnl["growth"], 0, delta=1)


# ===================================================================
#  Scenario 12: Shortfall reporting
#  Small pot (£5k ISA), large target (£20k/yr), end_age=75.
#  Sustainable must be False.  Shortfall years must exist.
#  After depletion, net_income_achieved should be 0.
# ===================================================================
class TestGold_ShortfallReporting(unittest.TestCase):
    """When capital runs out, shortfall is detected and reported."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
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
        cls.r = RetirementEngine(cls.cfg).run_projection()
        cls.s = cls.r["summary"]

    def test_not_sustainable(self):
        self.assertFalse(self.s["sustainable"])

    def test_first_shortfall_age_exists(self):
        self.assertIsNotNone(self.s["first_shortfall_age"])

    def test_shortfall_years_have_flag(self):
        shortfall_years = [yr for yr in self.r["years"] if yr["shortfall"]]
        self.assertGreater(len(shortfall_years), 0)

    def test_post_depletion_net_is_zero(self):
        """Years AFTER capital is gone (no guaranteed income) → net = 0."""
        depleted = False
        for yr in self.r["years"]:
            if depleted:
                # Capital was already 0 at start of this year
                self.assertAlmostEqual(yr["net_income_achieved"], 0, delta=1,
                    msg=f"Age {yr['age']}: expected 0 net after depletion")
            if yr["total_capital"] <= 0.01:
                depleted = True

    def test_year1_not_shortfall(self):
        """Year 1 should provide some income (ISA has £5k)."""
        yr0 = self.r["years"][0]
        self.assertGreater(yr0["net_income_achieved"], 0)


# ===================================================================
#  Scenario 13: Delayed guaranteed income changes drawdown
#  Guaranteed £20k/yr starts at age 70, retirement at 68.
#  Target = £20k net.  DC pot £200k with 0 growth.
#  Ages 68-69: DC must provide full income (no guaranteed).
#  Ages 70+: Guaranteed covers most/all, DC drawdown drops.
# ===================================================================
class TestGold_DelayedGuaranteedIncome(unittest.TestCase):
    """State pension starting mid-projection: DC drawdown higher before it kicks in."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
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
                "start_date": "2030-01",
                "end_date": None,
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
        cls.r = RetirementEngine(cls.cfg).run_projection()

    def test_net_meets_target_every_year(self):
        """Even with delayed guaranteed, net should meet target every year."""
        for yr in self.r["years"]:
            if not yr["shortfall"]:
                self.assertGreaterEqual(
                    yr["net_income_achieved"], yr["target_net"] - 1,
                    f"Age {yr['age']}: net {yr['net_income_achieved']:.2f}")

    def test_dc_drawdown_higher_before_guaranteed(self):
        """Before age 70, DC must provide more since no guaranteed income."""
        yr_68 = self.r["years"][0]  # age 68
        yr_70 = self.r["years"][2]  # age 70
        self.assertGreater(
            yr_68["dc_withdrawal_gross"], yr_70["dc_withdrawal_gross"],
            "DC drawdown should be higher before guaranteed income starts")

    def test_no_guaranteed_before_age_70(self):
        yr_68 = self.r["years"][0]
        self.assertAlmostEqual(yr_68["guaranteed_total"], 0, delta=1)

    def test_guaranteed_active_at_age_70(self):
        yr_70 = self.r["years"][2]
        self.assertAlmostEqual(yr_70["guaranteed_total"], 20000, delta=100)

    def test_dc_drawdown_drops_significantly(self):
        """DC drawdown at age 70+ should be much less than at 68."""
        yr_68 = self.r["years"][0]
        yr_72 = self.r["years"][4]  # well after guaranteed starts
        self.assertLess(
            yr_72["dc_withdrawal_gross"],
            yr_68["dc_withdrawal_gross"] * 0.5,
            "DC drawdown should drop by at least 50% once guaranteed covers target")


# ===================================================================
#  Scenario 14: Monthly source allocation — correct depletion timing
#  £30k TF ISA, £12k/yr target (£1k/month), 0 CPI, 0 growth.
#  Year 3: pot has £6k → monthly allocation draws £1k/month → depletes
#  at month 6, NOT month 11 or 12.
# ===================================================================
class TestGold_MonthlyAllocationDepletion(unittest.TestCase):
    """£6k pot at £1k/month must deplete in exactly month 6."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
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
        cls.r = RetirementEngine(cls.cfg).run_projection(include_monthly=True)
        cls.s = cls.r["summary"]

    def test_depletion_month_is_6(self):
        """Monthly allocation: £6k at £1k/month = 6 months, not 11."""
        ev = self.s["depletion_events"][0]
        self.assertEqual(ev["month"], 6)

    def test_monthly_draws_are_1000(self):
        """Each month draws exactly £1,000 until depletion."""
        # Year 3 (age 70): months 1-6 should each draw £1,000
        yr3_rows = [r for r in self.r["monthly_rows"] if r["age"] == 70]
        for i, row in enumerate(yr3_rows[:6]):
            wd = row["withdrawal_detail"].get("ISA", 0)
            self.assertAlmostEqual(wd, 1000, delta=1,
                                   msg=f"Month {i+1} of year 3 should draw £1,000")

    def test_no_spike_at_depletion(self):
        """No withdrawal should exceed £1,000 (no residual sweep spike)."""
        for row in self.r["monthly_rows"]:
            wd = row["withdrawal_detail"].get("ISA", 0)
            self.assertLessEqual(wd, 1001,
                                 msg=f"ISA draw at age {row['age']} mo {row['month_in_year']} "
                                     f"was {wd}, exceeds £1,000 target")


# ===================================================================
#  Scenario 15: Mid-year depletion rolls to next source immediately
#  ISA £5k (priority 1), DC £200k (priority 2). Target £12k/yr net.
#  ISA depletes mid-year; DC must pick up in the SAME month.
# ===================================================================
class TestGold_MidYearRollover(unittest.TestCase):
    """When a pot depletes mid-year, the next source fills the gap immediately."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
            target_income={"net_annual": 12000, "cpi_rate": 0.0},
            dc_pots=[{
                "name": "DC",
                "starting_balance": 200000,
                "growth_rate": 0.0,
                "annual_fees": 0.0,
                "tax_free_portion": 0.25,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            }],
            tax_free_accounts=[{
                "name": "ISA",
                "starting_balance": 5000,
                "growth_rate": 0.0,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            }],
            withdrawal_priority=["ISA", "DC"],
        )
        cls.r = RetirementEngine(cls.cfg).run_projection(include_monthly=True)
        cls.s = cls.r["summary"]

    def test_isa_depletes_first(self):
        dep_pots = [e["pot"] for e in self.s["depletion_events"]]
        self.assertIn("ISA", dep_pots)

    def test_no_income_gap_after_depletion(self):
        """The month after ISA depletes, DC must fill the shortfall."""
        dep = next(e for e in self.s["depletion_events"] if e["pot"] == "ISA")
        # Find the first month AFTER depletion
        found = False
        for row in self.r["monthly_rows"]:
            if found:
                dc_wd = row["withdrawal_detail"].get("DC", 0)
                self.assertGreater(dc_wd, 0,
                                   "DC must fill shortfall after ISA depletes")
                break
            if row["age"] == dep["age"] and row["month_in_year"] == dep["month"]:
                found = True

    def test_income_continuous(self):
        """Gross income should never be zero while capital remains."""
        for row in self.r["monthly_rows"]:
            if row["total_capital"] > 1:
                self.assertGreater(row["gross_income"], 0,
                                   f"Zero income at age {row['age']} mo {row['month_in_year']} "
                                   f"with capital {row['total_capital']}")


# ===================================================================
#  Scenario 16: No year-boundary smoothing
#  Single TF pot with balance that doesn't divide evenly by 12.
#  £7k ISA, £12k/yr target, 0 growth.  Should draw £1k/month for 7
#  months, not £583/month for 12 months.
# ===================================================================
class TestGold_NoYearBoundarySmoothing(unittest.TestCase):
    """Pots drain at the full monthly rate, not spread over 12 months."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
            personal={
                "date_of_birth": "1960-01",
                "retirement_date": "2028-01",
                "retirement_age": 68,
                "end_age": 70,
                "currency": "GBP",
            },
            target_income={"net_annual": 12000, "cpi_rate": 0.0},
            tax_free_accounts=[{
                "name": "ISA",
                "starting_balance": 7000,
                "growth_rate": 0.0,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            }],
            withdrawal_priority=["ISA"],
        )
        cls.r = RetirementEngine(cls.cfg).run_projection(include_monthly=True)
        cls.s = cls.r["summary"]

    def test_draws_1000_per_month(self):
        """First 7 months: draw £1,000 each (not £583 from annual smoothing)."""
        rows = self.r["monthly_rows"]
        for i in range(7):
            wd = rows[i]["withdrawal_detail"].get("ISA", 0)
            self.assertAlmostEqual(wd, 1000, delta=1,
                                   msg=f"Month {i+1} should draw £1,000")

    def test_depletion_at_month_7(self):
        """ISA depletes at month 7, not month 12."""
        ev = self.s["depletion_events"][0]
        self.assertEqual(ev["pot"], "ISA")
        self.assertEqual(ev["month"], 7)

    def test_zero_after_depletion(self):
        """Month 8+: ISA withdrawal should be zero."""
        rows = [r for r in self.r["monthly_rows"] if r["month_in_year"] > 7
                and r["age"] == 68]
        for row in rows:
            wd = row["withdrawal_detail"].get("ISA", 0)
            self.assertAlmostEqual(wd, 0, delta=0.01)


# ===================================================================
#  Scenario 17: Tax-aware monthly DC withdrawals
#  DC-only config. Verify that monthly gross-up uses YTD taxable
#  context and that net income meets target each year.
# ===================================================================
class TestGold_TaxAwareMonthlyDC(unittest.TestCase):
    """Monthly DC gross-up with YTD taxable context produces correct net income."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = _cfg(
            personal={
                "date_of_birth": "1960-01",
                "retirement_date": "2028-01",
                "retirement_age": 68,
                "end_age": 78,
                "currency": "GBP",
            },
            target_income={"net_annual": 25000, "cpi_rate": 0.0},
            dc_pots=[{
                "name": "DC",
                "starting_balance": 300000,
                "growth_rate": 0.0,
                "annual_fees": 0.0,
                "tax_free_portion": 0.25,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            }],
            withdrawal_priority=["DC"],
        )
        cls.r = RetirementEngine(cls.cfg).run_projection()
        cls.s = cls.r["summary"]

    def test_sustainable(self):
        self.assertTrue(self.s["sustainable"])

    def test_net_meets_target_every_year(self):
        """Each year's net income must meet or exceed target."""
        for yr in self.r["years"]:
            self.assertGreaterEqual(
                yr["net_income_achieved"], yr["target_net"] - 1,
                f"Year age {yr['age']}: net {yr['net_income_achieved']:.0f} "
                f"< target {yr['target_net']:.0f}")

    def test_dc_gross_withdrawal_reasonable(self):
        """DC gross should be higher than net (tax exists) but not wildly so."""
        yr0 = self.r["years"][0]
        self.assertGreater(yr0["dc_withdrawal_gross"], yr0["net_income_achieved"])
        # With 25% TFP and IoM tax, gross shouldn't exceed 1.5x net
        self.assertLess(yr0["dc_withdrawal_gross"], yr0["net_income_achieved"] * 1.5)

    def test_tax_free_portion_applied(self):
        """25% of DC gross should be tax-free."""
        yr0 = self.r["years"][0]
        expected_tf = yr0["dc_withdrawal_gross"] * 0.25
        self.assertAlmostEqual(yr0["dc_tax_free_portion"], expected_tf, delta=1)


if __name__ == "__main__":
    unittest.main()
