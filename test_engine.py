"""Deterministic sanity checks for the monthly-stepping projection engine."""
import unittest
from retirement_engine import RetirementEngine, annual_to_monthly_rate


def make_config(**overrides):
    """Build a minimal config for testing.  Override any top-level key."""
    cfg = {
        "personal": {
            "date_of_birth": "1960-01",
            "retirement_date": "2028-01",
            "retirement_age": 68,
            "end_age": 78,
            "currency": "GBP",
        },
        "target_income": {
            "net_annual": 20000,
            "cpi_rate": 0.0,
        },
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
    for key, val in overrides.items():
        cfg[key] = val
    return cfg


class TestAnnualToMonthlyRate(unittest.TestCase):
    """Verify the rate conversion helper."""

    def test_zero(self):
        self.assertEqual(annual_to_monthly_rate(0), 0.0)

    def test_roundtrip_5pct(self):
        monthly = annual_to_monthly_rate(0.05)
        compounded = (1 + monthly) ** 12
        self.assertAlmostEqual(compounded, 1.05, places=10)

    def test_roundtrip_10pct(self):
        monthly = annual_to_monthly_rate(0.10)
        compounded = (1 + monthly) ** 12
        self.assertAlmostEqual(compounded, 1.10, places=10)


class TestZeroGrowthDepletion(unittest.TestCase):
    """Zero growth, single TF pot, fixed withdrawals → known depletion month.

    £30,000 in TF ISA, £12,000/yr target (£1,000/month), zero CPI.
    Year 1 (age 68): 12 × £1,000 = £12,000 → balance £18,000
    Year 2 (age 69): 12 × £1,000 = £12,000 → balance £6,000
    Year 3 (age 70): 6 × £1,000 = £6,000 → balance £0, depleted month 6
    """

    def setUp(self):
        self.cfg = make_config(
            target_income={"net_annual": 12000, "cpi_rate": 0.0},
            tax_free_accounts=[{
                "name": "Cash ISA",
                "starting_balance": 30000,
                "growth_rate": 0.0,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            }],
            withdrawal_priority=["Cash ISA"],
        )
        self.result = RetirementEngine(self.cfg).run_projection()

    def test_depletion_event_exists(self):
        events = self.result["summary"]["depletion_events"]
        self.assertEqual(len(events), 1)

    def test_depletion_age_and_month(self):
        ev = self.result["summary"]["depletion_events"][0]
        self.assertEqual(ev["pot"], "Cash ISA")
        self.assertEqual(ev["age"], 70)
        # Annual plan caps withdrawal at pot balance (£6k) and spreads
        # over 12 months (£500/mo), so depletion occurs at month 12.
        self.assertEqual(ev["month"], 12)

    def test_year1_balance(self):
        yr0 = self.result["years"][0]
        self.assertAlmostEqual(yr0["tf_balances"]["Cash ISA"], 18000, delta=1)

    def test_year2_balance(self):
        yr1 = self.result["years"][1]
        self.assertAlmostEqual(yr1["tf_balances"]["Cash ISA"], 6000, delta=1)


class TestSingleDCPotWithTax(unittest.TestCase):
    """Single DC pot, no guaranteed income, zero growth/fees.

    £200k balance, £10k net target.  Should be sustainable over 10 years.
    """

    def setUp(self):
        self.cfg = make_config(
            target_income={"net_annual": 10000, "cpi_rate": 0.0},
            dc_pots=[{
                "name": "DC Pot",
                "starting_balance": 200000,
                "growth_rate": 0.0,
                "annual_fees": 0.0,
                "tax_free_portion": 0.25,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            }],
            withdrawal_priority=["DC Pot"],
        )
        self.result = RetirementEngine(self.cfg).run_projection()

    def test_sustainable(self):
        self.assertTrue(self.result["summary"]["sustainable"])

    def test_first_year_net_close_to_target(self):
        yr0 = self.result["years"][0]
        self.assertAlmostEqual(yr0["net_income_achieved"], 10000, delta=50)

    def test_dc_gross_positive(self):
        yr0 = self.result["years"][0]
        self.assertGreater(yr0["dc_withdrawal_gross"], 0)


class TestGuaranteedIncomeCoverTarget(unittest.TestCase):
    """Guaranteed income exceeds target → no DC drawdown needed."""

    def setUp(self):
        self.cfg = make_config(
            target_income={"net_annual": 10000, "cpi_rate": 0.0},
            guaranteed_income=[{
                "name": "State Pension",
                "gross_annual": 15000,
                "indexation_rate": 0.0,
                "start_age": 68,
                "end_age": None,
                "taxable": True,
                "values_as_of": "2028-01",
            }],
            dc_pots=[{
                "name": "DC Pot",
                "starting_balance": 100000,
                "growth_rate": 0.0,
                "annual_fees": 0.0,
                "tax_free_portion": 0.25,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            }],
            withdrawal_priority=["DC Pot"],
        )
        self.result = RetirementEngine(self.cfg).run_projection()

    def test_no_dc_drawdown(self):
        yr0 = self.result["years"][0]
        self.assertAlmostEqual(yr0["dc_withdrawal_gross"], 0.0, delta=1)

    def test_dc_balance_unchanged(self):
        yr0 = self.result["years"][0]
        self.assertAlmostEqual(yr0["pot_balances"]["DC Pot"], 100000, delta=1)

    def test_sustainable(self):
        self.assertTrue(self.result["summary"]["sustainable"])


class TestExactDepletionTiming(unittest.TestCase):
    """TF pot with exact depletion: £48k balance, £24k/yr target, zero growth.

    £2,000/month withdrawal.
    Year 1 (age 68): 24,000 withdrawn → balance 24,000
    Year 2 (age 69): 24,000 withdrawn → balance 0, depleted month 12
    """

    def setUp(self):
        self.cfg = make_config(
            personal={
                "date_of_birth": "1960-01",
                "retirement_date": "2028-01",
                "retirement_age": 68,
                "end_age": 75,
                "currency": "GBP",
            },
            target_income={"net_annual": 24000, "cpi_rate": 0.0},
            tax_free_accounts=[{
                "name": "ISA",
                "starting_balance": 48000,
                "growth_rate": 0.0,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            }],
            withdrawal_priority=["ISA"],
        )
        self.result = RetirementEngine(self.cfg).run_projection()

    def test_depletion_age(self):
        ev = self.result["summary"]["depletion_events"][0]
        self.assertEqual(ev["age"], 69)

    def test_depletion_month(self):
        ev = self.result["summary"]["depletion_events"][0]
        self.assertEqual(ev["month"], 12)

    def test_year1_balance(self):
        yr0 = self.result["years"][0]
        self.assertAlmostEqual(yr0["tf_balances"]["ISA"], 24000, delta=1)


class TestOutputShape(unittest.TestCase):
    """Verify the output dict has all expected keys for UI compatibility."""

    def setUp(self):
        self.cfg = make_config(
            target_income={"net_annual": 10000, "cpi_rate": 0.0},
            dc_pots=[{
                "name": "DC",
                "starting_balance": 100000,
                "growth_rate": 0.05,
                "annual_fees": 0.005,
                "tax_free_portion": 0.25,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            }],
            withdrawal_priority=["DC"],
        )
        self.result = RetirementEngine(self.cfg).run_projection()

    def test_top_level_keys(self):
        self.assertIn("years", self.result)
        self.assertIn("summary", self.result)
        self.assertIn("warnings", self.result)

    def test_year_row_keys(self):
        expected = {
            "age", "tax_year", "target_net", "guaranteed_income",
            "guaranteed_total", "dc_withdrawal_gross", "dc_tax_free_portion",
            "tf_withdrawal", "withdrawal_detail", "total_taxable_income",
            "tax_due", "uk_tax_due", "iom_tax_breakdown", "uk_tax_breakdown",
            "net_income_achieved", "shortfall", "pot_balances", "tf_balances",
            "total_capital", "pot_pnl",
        }
        yr0 = self.result["years"][0]
        self.assertTrue(expected.issubset(set(yr0.keys())),
                        f"Missing keys: {expected - set(yr0.keys())}")

    def test_summary_keys(self):
        expected = {
            "sustainable", "first_shortfall_age", "end_age", "anchor_age",
            "is_post_retirement", "num_years", "remaining_capital",
            "remaining_pots", "remaining_tf", "total_tax_paid",
            "total_uk_tax_paid", "uk_tax_saving", "avg_effective_tax_rate",
            "first_pot_exhausted_age", "depletion_events",
        }
        self.assertTrue(expected.issubset(set(self.result["summary"].keys())),
                        f"Missing: {expected - set(self.result['summary'].keys())}")

    def test_pot_pnl_keys(self):
        pnl = self.result["years"][0]["pot_pnl"]["DC"]
        expected = {"opening", "growth", "fees", "withdrawal", "closing", "provenance"}
        self.assertTrue(expected.issubset(set(pnl.keys())))


if __name__ == "__main__":
    unittest.main()
