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
from retirement_engine import RetirementEngine, load_config


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
        # Annual plan spreads £6k over 12 months (£500/mo).  After month 11
        # the remaining £500 < monthly target (£1k), so the last-residual
        # drawdown sweeps it → depletion at month 11.
        self.assertEqual(self.s["depletion_events"][0]["month"], 11)

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
#  Scenario 6: Baseline realistic projection (config_active.json)
#  Uses the real-world configuration with LOOSE tolerances.
#  Only a few meaningful checkpoints — not overfitted.
#
#  Expected baseline (captured 2026-03-09):
#    sustainable: True
#    num_years: 23
#    first_pot_exhausted_age: 75 (Employer DC Pot)
#    remaining_capital: ~£93,811
#    yr0 capital: ~£307,767
#    yr5 capital: ~£296,744
# ===================================================================
class TestGold_BaselineRealistic(unittest.TestCase):
    """Real-world config with loose checkpoints to catch major regressions."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config("config_active.json")
        cls.r = RetirementEngine(cls.cfg).run_projection()
        cls.s = cls.r["summary"]

    def test_sustainable(self):
        self.assertTrue(self.s["sustainable"])

    def test_num_years(self):
        self.assertEqual(self.s["num_years"], 23)

    def test_first_pot_exhausted_is_employer_dc(self):
        self.assertGreater(len(self.s["depletion_events"]), 0)
        self.assertEqual(
            self.s["depletion_events"][0]["pot"], "Employer DC Pot")

    def test_employer_dc_depletes_around_age_75(self):
        evt = self.s["depletion_events"][0]
        self.assertAlmostEqual(evt["age"], 75, delta=1)

    def test_yr0_capital_around_308k(self):
        self.assertAlmostEqual(
            self.r["years"][0]["total_capital"], 307767, delta=5000)

    def test_yr5_capital_around_297k(self):
        self.assertAlmostEqual(
            self.r["years"][5]["total_capital"], 296744, delta=5000)

    def test_remaining_capital_around_94k(self):
        self.assertAlmostEqual(
            self.s["remaining_capital"], 93811, delta=5000)

    def test_total_tax_reasonable(self):
        self.assertAlmostEqual(
            self.s["total_tax_paid"], 156300, delta=5000)

    def test_yr0_guaranteed_income_positive(self):
        self.assertGreater(self.r["years"][0]["guaranteed_total"], 20000)

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


if __name__ == "__main__":
    unittest.main()
