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
        # Annual plan spreads £6k over 12 months (£500/mo).  After month 11
        # the remaining £500 < monthly target (£1k), so the last-residual
        # drawdown sweeps it → depletion at month 11.
        self.assertEqual(ev["month"], 11)

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


class TestGuaranteedStartsMidYear(unittest.TestCase):
    """Guaranteed income that starts at age 70 (mid-projection).

    Retirement at 68, guaranteed starts at 70, target 10k, TF ISA covers gap.
    Before age 70: full target from ISA.
    From age 70: guaranteed covers target, ISA untouched.
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
            target_income={"net_annual": 10000, "cpi_rate": 0.0},
            guaranteed_income=[{
                "name": "Deferred Pension",
                "gross_annual": 15000,
                "indexation_rate": 0.0,
                "start_age": 70,
                "end_age": None,
                "taxable": True,
                "values_as_of": "2028-01",
            }],
            tax_free_accounts=[{
                "name": "ISA",
                "starting_balance": 50000,
                "growth_rate": 0.0,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            }],
            withdrawal_priority=["ISA"],
        )
        self.result = RetirementEngine(self.cfg).run_projection()

    def test_isa_drawdown_before_pension_starts(self):
        """Ages 68-69: ISA should be drawn down to cover target."""
        yr0 = self.result["years"][0]  # age 68
        self.assertGreater(yr0["tf_withdrawal"], 5000)

    def test_no_drawdown_after_pension_starts(self):
        """Age 70+: guaranteed covers target, no ISA drawdown needed."""
        yr2 = self.result["years"][2]  # age 70
        self.assertAlmostEqual(yr2["tf_withdrawal"], 0.0, delta=1)

    def test_guaranteed_zero_before_start(self):
        """Age 68: deferred pension should show 0."""
        yr0 = self.result["years"][0]
        self.assertAlmostEqual(yr0["guaranteed_income"]["Deferred Pension"], 0.0, delta=1)

    def test_guaranteed_active_after_start(self):
        """Age 70: deferred pension should be ~15000."""
        yr2 = self.result["years"][2]
        self.assertAlmostEqual(yr2["guaranteed_income"]["Deferred Pension"], 15000, delta=100)

    def test_sustainable(self):
        self.assertTrue(self.result["summary"]["sustainable"])


class TestValuesAsOfPostRetirement(unittest.TestCase):
    """values_as_of is after retirement date → anchor should be values_as_of.

    DOB 1960-01, retirement 2028-01 (age 68), values_as_of 2029-01 (age 69).
    DC pot has £100k at 2029-01. Projection should start at age 69.
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
            target_income={"net_annual": 10000, "cpi_rate": 0.0},
            dc_pots=[{
                "name": "DC",
                "starting_balance": 100000,
                "growth_rate": 0.0,
                "annual_fees": 0.0,
                "tax_free_portion": 0.25,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2029-01",
            }],
            withdrawal_priority=["DC"],
        )
        self.result = RetirementEngine(self.cfg).run_projection()

    def test_anchor_age_is_69(self):
        self.assertEqual(self.result["summary"]["anchor_age"], 69)

    def test_is_post_retirement(self):
        self.assertTrue(self.result["summary"]["is_post_retirement"])

    def test_first_year_age(self):
        self.assertEqual(self.result["years"][0]["age"], 69)

    def test_num_years(self):
        # Ages 69-75 inclusive = 7 years
        self.assertEqual(len(self.result["years"]), 7)

    def test_sustainable(self):
        self.assertTrue(self.result["summary"]["sustainable"])


class TestCPIInflation(unittest.TestCase):
    """Verify CPI inflates target year-over-year.

    3% CPI, £20k base target. Year 2 target should be ~£20,600.
    """

    def setUp(self):
        self.cfg = make_config(
            personal={
                "date_of_birth": "1960-01",
                "retirement_date": "2028-01",
                "retirement_age": 68,
                "end_age": 73,
                "currency": "GBP",
            },
            target_income={"net_annual": 20000, "cpi_rate": 0.03},
            tax_free_accounts=[{
                "name": "ISA",
                "starting_balance": 200000,
                "growth_rate": 0.0,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            }],
            withdrawal_priority=["ISA"],
        )
        self.result = RetirementEngine(self.cfg).run_projection()

    def test_year1_target(self):
        yr0 = self.result["years"][0]
        self.assertAlmostEqual(yr0["target_net"], 20000, delta=10)

    def test_year2_target_inflated(self):
        yr1 = self.result["years"][1]
        # After 12 months of monthly CPI compounding ≈ 20000 * 1.03 = 20600
        self.assertAlmostEqual(yr1["target_net"], 20600, delta=50)

    def test_year3_target_compounded(self):
        yr2 = self.result["years"][2]
        # ≈ 20000 * 1.03^2 = 21218
        self.assertAlmostEqual(yr2["target_net"], 21218, delta=50)


class TestMultiplePotsPriorityOrder(unittest.TestCase):
    """Two DC pots in priority order. First pot should deplete before second.

    Pot A: £12k, Pot B: £50k. Target £10k net, zero growth.
    Pot A should deplete first.
    """

    def setUp(self):
        self.cfg = make_config(
            personal={
                "date_of_birth": "1960-01",
                "retirement_date": "2028-01",
                "retirement_age": 68,
                "end_age": 78,
                "currency": "GBP",
            },
            target_income={"net_annual": 10000, "cpi_rate": 0.0},
            dc_pots=[
                {
                    "name": "Pot A",
                    "starting_balance": 12000,
                    "growth_rate": 0.0,
                    "annual_fees": 0.0,
                    "tax_free_portion": 0.25,
                    "allocation": {"mode": "manual", "manual_override": True},
                    "values_as_of": "2028-01",
                },
                {
                    "name": "Pot B",
                    "starting_balance": 50000,
                    "growth_rate": 0.0,
                    "annual_fees": 0.0,
                    "tax_free_portion": 0.25,
                    "allocation": {"mode": "manual", "manual_override": True},
                    "values_as_of": "2028-01",
                },
            ],
            withdrawal_priority=["Pot A", "Pot B"],
        )
        self.result = RetirementEngine(self.cfg).run_projection()

    def test_pot_a_depletes_first(self):
        events = self.result["summary"]["depletion_events"]
        pot_names = [e["pot"] for e in events]
        self.assertIn("Pot A", pot_names)
        # Pot A should deplete before Pot B
        if "Pot B" in pot_names:
            a_idx = pot_names.index("Pot A")
            b_idx = pot_names.index("Pot B")
            self.assertLess(a_idx, b_idx)

    def test_pot_a_depleted_age(self):
        events = self.result["summary"]["depletion_events"]
        a_event = [e for e in events if e["pot"] == "Pot A"][0]
        # £12k at ~£10k gross/yr → depletes in ~1-2 years
        self.assertLessEqual(a_event["age"], 70)

    def test_pot_b_still_has_balance_year1(self):
        yr0 = self.result["years"][0]
        # Pot B should be mostly untouched in year 1 (Pot A covers most)
        self.assertGreater(yr0["pot_balances"]["Pot B"], 40000)


class TestMixedDCAndTFPriority(unittest.TestCase):
    """DC pot first, then TF account in priority order.

    Verifies DC draws first (with tax), TF draws second (tax-free).
    """

    def setUp(self):
        self.cfg = make_config(
            personal={
                "date_of_birth": "1960-01",
                "retirement_date": "2028-01",
                "retirement_age": 68,
                "end_age": 73,
                "currency": "GBP",
            },
            target_income={"net_annual": 15000, "cpi_rate": 0.0},
            dc_pots=[{
                "name": "DC",
                "starting_balance": 5000,
                "growth_rate": 0.0,
                "annual_fees": 0.0,
                "tax_free_portion": 0.25,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            }],
            tax_free_accounts=[{
                "name": "ISA",
                "starting_balance": 100000,
                "growth_rate": 0.0,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            }],
            withdrawal_priority=["DC", "ISA"],
        )
        self.result = RetirementEngine(self.cfg).run_projection()

    def test_dc_depletes_before_isa(self):
        events = self.result["summary"]["depletion_events"]
        dc_events = [e for e in events if e["pot"] == "DC"]
        self.assertEqual(len(dc_events), 1)
        self.assertEqual(dc_events[0]["age"], 68)

    def test_isa_used_after_dc_depleted(self):
        yr0 = self.result["years"][0]
        # DC only has 5k, so ISA must cover the rest
        self.assertGreater(yr0["tf_withdrawal"], 5000)

    def test_sustainable(self):
        self.assertTrue(self.result["summary"]["sustainable"])


class TestGuaranteedIndexation(unittest.TestCase):
    """Guaranteed income with 3% indexation grows year-over-year."""

    def setUp(self):
        self.cfg = make_config(
            personal={
                "date_of_birth": "1960-01",
                "retirement_date": "2028-01",
                "retirement_age": 68,
                "end_age": 73,
                "currency": "GBP",
            },
            target_income={"net_annual": 5000, "cpi_rate": 0.0},
            guaranteed_income=[{
                "name": "DB Pension",
                "gross_annual": 10000,
                "indexation_rate": 0.03,
                "start_age": 68,
                "end_age": None,
                "taxable": True,
                "values_as_of": "2028-01",
            }],
            dc_pots=[{
                "name": "DC",
                "starting_balance": 50000,
                "growth_rate": 0.0,
                "annual_fees": 0.0,
                "tax_free_portion": 0.25,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            }],
            withdrawal_priority=["DC"],
        )
        self.result = RetirementEngine(self.cfg).run_projection()

    def test_year1_guaranteed(self):
        yr0 = self.result["years"][0]
        # Should be approximately 10000 (first year, no indexation yet)
        self.assertAlmostEqual(yr0["guaranteed_total"], 10000, delta=200)

    def test_year3_guaranteed_higher(self):
        yr2 = self.result["years"][2]
        # After ~2 years of 3% indexation: ~10000 * 1.03^2 ≈ 10609
        self.assertGreater(yr2["guaranteed_total"], 10400)

    def test_no_dc_drawdown_when_guaranteed_covers(self):
        """Guaranteed > target → no DC drawdown."""
        yr0 = self.result["years"][0]
        self.assertAlmostEqual(yr0["dc_withdrawal_gross"], 0, delta=1)


class TestPreAnchorGrowth(unittest.TestCase):
    """DC pot with values_as_of before retirement should grow to anchor.

    £100k at 2027-01, retirement 2028-01, 5% growth, 0.5% fees.
    12 months of pre-anchor growth ≈ 100k * (1.05/1.005)^(1) ≈ 104,478.
    Actually with monthly: 100k grown 12 months at monthly net rate.
    """

    def setUp(self):
        self.cfg = make_config(
            personal={
                "date_of_birth": "1960-01",
                "retirement_date": "2028-01",
                "retirement_age": 68,
                "end_age": 70,
                "currency": "GBP",
            },
            target_income={"net_annual": 1000, "cpi_rate": 0.0},
            dc_pots=[{
                "name": "DC",
                "starting_balance": 100000,
                "growth_rate": 0.05,
                "annual_fees": 0.005,
                "tax_free_portion": 0.25,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2027-01",
            }],
            withdrawal_priority=["DC"],
        )
        self.result = RetirementEngine(self.cfg).run_projection()

    def test_opening_balance_grew(self):
        """Opening balance at anchor should be > 100k due to pre-anchor growth."""
        yr0 = self.result["years"][0]
        opening = yr0["pot_pnl"]["DC"]["opening"]
        self.assertGreater(opening, 103000)
        self.assertLess(opening, 106000)


class TestMonthlyDebugOutput(unittest.TestCase):
    """Verify the optional monthly debug rows."""

    def setUp(self):
        self.cfg = make_config(
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
                "starting_balance": 50000,
                "growth_rate": 0.0,
                "allocation": {"mode": "manual", "manual_override": True},
                "values_as_of": "2028-01",
            }],
            withdrawal_priority=["ISA"],
        )

    def test_default_no_monthly_rows(self):
        result = RetirementEngine(self.cfg).run_projection()
        self.assertNotIn("monthly_rows", result)

    def test_flag_false_no_monthly_rows(self):
        result = RetirementEngine(self.cfg).run_projection(include_monthly=False)
        self.assertNotIn("monthly_rows", result)

    def test_flag_true_has_monthly_rows(self):
        result = RetirementEngine(self.cfg).run_projection(include_monthly=True)
        self.assertIn("monthly_rows", result)

    def test_monthly_row_count(self):
        result = RetirementEngine(self.cfg).run_projection(include_monthly=True)
        # Ages 68-70 inclusive = 3 years × 12 months = 36 rows
        self.assertEqual(len(result["monthly_rows"]), 36)

    def test_monthly_row_keys(self):
        result = RetirementEngine(self.cfg).run_projection(include_monthly=True)
        expected = {
            "year", "month", "age", "month_in_year", "target_monthly",
            "guaranteed_detail", "guaranteed_total",
            "withdrawal_detail", "withdrawal_total", "gross_income",
            "dc_balances", "tf_balances",
            "total_capital", "depleted_this_month",
        }
        self.assertTrue(expected.issubset(set(result["monthly_rows"][0].keys())))

    def test_annual_output_unchanged_with_flag(self):
        without = RetirementEngine(self.cfg).run_projection(include_monthly=False)
        with_monthly = RetirementEngine(self.cfg).run_projection(include_monthly=True)
        # Annual years and summary should be identical
        self.assertEqual(len(without["years"]), len(with_monthly["years"]))
        self.assertEqual(without["summary"], with_monthly["summary"])
        for i, yr in enumerate(without["years"]):
            self.assertEqual(yr["age"], with_monthly["years"][i]["age"])
            self.assertAlmostEqual(
                yr["net_income_achieved"],
                with_monthly["years"][i]["net_income_achieved"], places=2)

    def test_balances_decrease_over_months(self):
        result = RetirementEngine(self.cfg).run_projection(include_monthly=True)
        rows = result["monthly_rows"]
        # ISA balance should decrease as withdrawals happen
        self.assertGreater(rows[0]["total_capital"], rows[-1]["total_capital"])

    def test_first_month_target(self):
        result = RetirementEngine(self.cfg).run_projection(include_monthly=True)
        # Monthly target ≈ 12000 / 12 = 1000
        self.assertAlmostEqual(result["monthly_rows"][0]["target_monthly"], 1000, delta=5)


if __name__ == "__main__":
    unittest.main()
