"""Unit tests for review_helpers.py — Annual Review data layer and state detection."""
import unittest
import os
import json
import tempfile
from unittest.mock import patch
from datetime import date

import review_helpers
from review_helpers import (
    load_reviews, save_reviews, compute_review_state,
    build_balances_snapshot, apply_review_balances_to_config,
    build_recommendation_from_result, build_initial_strategy_state,
)


def _make_cfg(**overrides):
    """Minimal config for testing."""
    cfg = {
        "personal": {
            "date_of_birth": "1960-01",
            "retirement_date": "2028-01",
            "retirement_age": 68,
            "end_age": 90,
            "currency": "GBP",
        },
        "target_income": {"net_annual": 20000, "cpi_rate": 0.03},
        "dc_pots": [
            {"name": "DC1", "starting_balance": 100000, "growth_rate": 0.04,
             "annual_fees": 0.005, "tax_free_portion": 0.25, "values_as_of": "2028-01"},
        ],
        "tax_free_accounts": [
            {"name": "ISA", "starting_balance": 30000, "growth_rate": 0.035,
             "values_as_of": "2028-01"},
        ],
        "withdrawal_priority": ["DC1", "ISA"],
        "drawdown_strategy": "fixed_target",
        "drawdown_strategy_params": {"net_annual": 20000},
    }
    cfg.update(overrides)
    return cfg


class TestLoadSaveReviews(unittest.TestCase):
    """Load/save reviews.json round-trip."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self._orig_path = review_helpers.REVIEWS_PATH
        review_helpers.REVIEWS_PATH = self.tmp.name

    def tearDown(self):
        review_helpers.REVIEWS_PATH = self._orig_path
        if os.path.exists(self.tmp.name):
            os.remove(self.tmp.name)

    def test_empty_load(self):
        os.remove(self.tmp.name)
        data = load_reviews()
        self.assertIsNone(data["baseline"])
        self.assertEqual(data["reviews"], [])

    def test_round_trip(self):
        data = {"baseline": {"ages": [68, 69]}, "reviews": [{"review_date": "2028-01-01"}]}
        save_reviews(data)
        loaded = load_reviews()
        self.assertEqual(loaded["baseline"]["ages"], [68, 69])
        self.assertEqual(len(loaded["reviews"]), 1)


class TestComputeReviewState(unittest.TestCase):
    """State detection for the 4 review page states."""

    @patch("review_helpers.date")
    def test_pre_retirement(self, mock_date):
        mock_date.today.return_value = date(2026, 6, 1)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        cfg = _make_cfg()
        state = compute_review_state(cfg, {"baseline": None, "reviews": []})
        self.assertEqual(state["state"], "pre_retirement")
        self.assertIn("year", state["countdown_text"])

    @patch("review_helpers.date")
    def test_bootstrap_due(self, mock_date):
        mock_date.today.return_value = date(2028, 3, 1)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        cfg = _make_cfg()
        state = compute_review_state(cfg, {"baseline": None, "reviews": []})
        self.assertEqual(state["state"], "bootstrap_due")

    @patch("review_helpers.date")
    def test_between_reviews(self, mock_date):
        mock_date.today.return_value = date(2028, 6, 1)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        cfg = _make_cfg()
        reviews_data = {"baseline": None, "reviews": [
            {"review_date": "2028-01-15", "review_age": 68, "review_type": "bootstrap",
             "balances": {}, "actual_drawdown": None, "recommendation": {}},
        ]}
        state = compute_review_state(cfg, reviews_data)
        self.assertEqual(state["state"], "between_reviews")
        self.assertIsNotNone(state["days_until_review"])
        self.assertGreater(state["days_until_review"], 0)

    @patch("review_helpers.date")
    def test_review_due(self, mock_date):
        mock_date.today.return_value = date(2029, 3, 1)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        cfg = _make_cfg()
        reviews_data = {"baseline": None, "reviews": [
            {"review_date": "2028-01-15", "review_age": 68, "review_type": "bootstrap",
             "balances": {}, "actual_drawdown": None, "recommendation": {}},
        ]}
        state = compute_review_state(cfg, reviews_data)
        self.assertEqual(state["state"], "review_due")
        self.assertIsNotNone(state["overdue_days"])
        self.assertGreater(state["overdue_days"], 0)


class TestBuildBalancesSnapshot(unittest.TestCase):
    def test_snapshot(self):
        cfg = _make_cfg()
        balances = build_balances_snapshot(cfg)
        self.assertIn("DC1", balances)
        self.assertIn("ISA", balances)
        self.assertEqual(balances["DC1"]["balance"], 100000)
        self.assertEqual(balances["DC1"]["type"], "dc_pot")
        self.assertEqual(balances["ISA"]["type"], "tax_free")


class TestApplyReviewBalances(unittest.TestCase):
    def test_apply(self):
        cfg = _make_cfg()
        balances = {"DC1": {"balance": 95000, "type": "dc_pot"},
                    "ISA": {"balance": 28000, "type": "tax_free"}}
        apply_review_balances_to_config(cfg, balances, "2029-01")
        self.assertEqual(cfg["dc_pots"][0]["starting_balance"], 95000)
        self.assertEqual(cfg["dc_pots"][0]["values_as_of"], "2029-01")
        self.assertEqual(cfg["tax_free_accounts"][0]["starting_balance"], 28000)


class TestBuildRecommendation(unittest.TestCase):
    def test_basic(self):
        cfg = _make_cfg()
        result = {
            "years": [{
                "net_income_achieved": 20000,
                "withdrawal_detail": {"DC1": 8000, "ISA": 2000},
            }],
            "summary": {"first_shortfall_age": None},
        }
        rec = build_recommendation_from_result(result, cfg)
        self.assertEqual(rec["total_net_income"], 20000)
        self.assertEqual(len(rec["withdrawal_plan"]), 2)
        self.assertTrue(rec["sustainable"])


class TestBuildInitialStrategyState(unittest.TestCase):
    def test_stateless_returns_none(self):
        state = build_initial_strategy_state([], "fixed_target", _make_cfg())
        self.assertIsNone(state)

    def test_arva_guardrails(self):
        drawdown = [{"source": "DC1", "net_amount": 15000}]
        state = build_initial_strategy_state(drawdown, "arva_guardrails", _make_cfg())
        self.assertIsNotNone(state)
        self.assertEqual(state["prev_withdrawal"], 15000)

    def test_vanguard(self):
        drawdown = [{"source": "DC1", "net_amount": 12000}]
        state = build_initial_strategy_state(drawdown, "vanguard_dynamic", _make_cfg())
        self.assertIsNotNone(state)
        self.assertEqual(state["current_target"], 12000)

    def test_guyton_klinger(self):
        drawdown = [{"source": "DC1", "net_amount": 10000}]
        state = build_initial_strategy_state(drawdown, "guyton_klinger", _make_cfg())
        self.assertIsNotNone(state)
        self.assertEqual(state["current_target"], 10000)
        self.assertAlmostEqual(state["prev_gross"], 11000, delta=1)

    def test_empty_drawdown_returns_none(self):
        state = build_initial_strategy_state([], "guyton_klinger", _make_cfg())
        self.assertIsNone(state)


if __name__ == "__main__":
    unittest.main()
