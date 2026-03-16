"""Quick integration test for the backtest engine."""
import json
import time
from backtest_engine import (
    load_historical_returns, run_backtest, extract_percentiles,
    compute_pot_annual_return, build_schedules, load_asset_model
)
from retirement_engine import load_asset_model as load_am


def test_historical_data_loads():
    """Verify historical_returns.json loads and has expected structure."""
    data = load_historical_returns()
    assert "metadata" in data
    assert "annual_returns" in data
    years = data["annual_returns"]
    assert len(years) > 100  # at least 100 years
    # Check a known year
    assert "2008" in years
    y2008 = years["2008"]
    assert "us_equity" in y2008
    assert y2008["us_equity"] < -0.30  # GFC crash
    print(f"  PASS: {len(years)} years loaded, 2008 US equity = {y2008['us_equity']:.3f}")


def test_pot_return_computation():
    """Verify per-pot return from holdings."""
    data = load_historical_returns()
    asset_model = load_am()
    hdm = asset_model.get("historical_data_mapping", {})

    # Use real config
    with open("config_active.json") as f:
        cfg = json.load(f)

    pot = cfg["dc_pots"][0]
    print(f"  Testing pot: {pot['name']}")
    print(f"  Holdings: {len(pot.get('holdings', []))}")

    # Check return for 2008 (GFC)
    ret_2008 = compute_pot_annual_return(
        pot, "2008", data["annual_returns"], asset_model, hdm)
    print(f"  2008 pot return: {ret_2008:.4f}" if ret_2008 else "  2008: None")

    # Check return for 2020
    ret_2020 = compute_pot_annual_return(
        pot, "2020", data["annual_returns"], asset_model, hdm)
    print(f"  2020 pot return: {ret_2020:.4f}" if ret_2020 else "  2020: None (expected - BoE ends 2016)")

    # Check a good year
    ret_1997 = compute_pot_annual_return(
        pot, "1997", data["annual_returns"], asset_model, hdm)
    print(f"  1997 pot return: {ret_1997:.4f}" if ret_1997 else "  1997: None")

    assert ret_2008 is not None
    assert ret_2008 < 0  # Should be negative in GFC
    print("  PASS")


def test_schedule_building():
    """Verify schedule building for a historical window."""
    data = load_historical_returns()
    asset_model = load_am()
    hdm = asset_model.get("historical_data_mapping", {})

    with open("config_active.json") as f:
        cfg = json.load(f)

    ret_age = cfg["personal"]["retirement_age"]
    n_years = cfg["personal"]["end_age"] - ret_age

    schedules = build_schedules(cfg, 2000, n_years,
                                data["annual_returns"], asset_model, hdm)

    print(f"  Window: {schedules['window_label']}")
    print(f"  CPI schedule entries: {len(schedules['cpi_rate_schedule'])}")

    for pot_name, sched in schedules["_dc_growth_schedules"].items():
        print(f"  DC '{pot_name}': {len(sched)} years of growth data")
        # Print first few
        ages = sorted(sched.keys())[:3]
        for a in ages:
            print(f"    age {a}: {sched[a]:+.4f}")

    assert len(schedules["cpi_rate_schedule"]) > 0
    print("  PASS")


def test_full_backtest_small():
    """Run a small backtest (3 windows) to verify end-to-end."""
    with open("config_active.json") as f:
        cfg = json.load(f)

    print(f"  Config: retirement_age={cfg['personal']['retirement_age']}, "
          f"end_age={cfg['personal']['end_age']}")

    start = time.time()
    result = run_backtest(cfg, max_windows=3)
    elapsed = time.time() - start

    meta = result["metadata"]
    print(f"  Windows: {meta['n_windows']}, "
          f"n_years: {meta['n_years']}, "
          f"range: {meta['start_range']}-{meta['end_range']}")
    print(f"  Time: {elapsed:.2f}s ({elapsed/meta['n_windows']:.2f}s per window)")

    # Check each window has results
    for w in result["windows"]:
        years = w["result"]["years"]
        final_cap = years[-1]["total_capital"] if years else 0
        sustainable = w["result"]["summary"]["sustainable"]
        print(f"  {w['window_label']}: final_capital=£{final_cap:,.0f}, "
              f"sustainable={sustainable}")

    assert meta["n_windows"] == 3
    print("  PASS")


def test_percentile_extraction():
    """Run backtest and extract percentiles."""
    with open("config_active.json") as f:
        cfg = json.load(f)

    start = time.time()
    result = run_backtest(cfg, max_windows=10)
    elapsed_bt = time.time() - start

    start = time.time()
    pcts = extract_percentiles(result)
    elapsed_pct = time.time() - start

    print(f"  Backtest: {elapsed_bt:.2f}s, Percentiles: {elapsed_pct:.3f}s")
    sus = pcts["sustainability"]
    print(f"  Sustainability rate: {sus['rate']*100:.1f}% ({sus['count']}/{sus['total']})")
    print(f"  Worst window: {pcts['worst_window']['label']} "
          f"(final=£{pcts['worst_window']['final_capital']:,.0f}, "
          f"depletion_age={pcts['worst_window']['depletion_age']})")
    print(f"  Best window: {pcts['best_window']['label']} "
          f"(final=£{pcts['best_window']['final_capital']:,.0f})")

    # Income stability
    inc = pcts["income_stability"]
    print(f"  Median income ratio: {inc['median_income_ratio']*100:.1f}% of target")
    print(f"  Worst income ratio:  {inc['worst_income_ratio']*100:.1f}% of target")

    # Worst-period timeline (first 5 years)
    timeline = pcts["worst_window"]["timeline"]
    print(f"  Worst-period timeline ({pcts['worst_window']['label']}):")
    for t in timeline[:5]:
        mkt = f"{t['market_return']:+.1f}%" if t['market_return'] is not None else 'N/A'
        sf = ' ⚠ SHORTFALL' if t['shortfall'] else ''
        print(f"    Age {t['age']} ({t['calendar_year']}): "
              f"Market {mkt}  Capital £{t['total_capital']:,.0f}  "
              f"Income £{t['net_income']:,.0f}/{t['target_income']:,.0f} "
              f"({t['income_ratio']*100:.0f}%){sf}")

    # Percentile fan chart data
    p50 = pcts["percentile_trajectories"]["p50"]
    print(f"  Median capital trajectory (every 5 years):")
    for pt in p50:
        if pt["age"] % 5 == 0 or pt["age"] == pcts["ages"][-1]:
            print(f"    Age {pt['age']}: £{pt['total_capital']:,.0f}  "
                  f"income=£{pt['net_income']:,.0f}")

    assert pcts["n_windows"] == 10
    print("  PASS")


if __name__ == "__main__":
    tests = [
        ("Historical data loads", test_historical_data_loads),
        ("Pot return computation", test_pot_return_computation),
        ("Schedule building", test_schedule_building),
        ("Full backtest (3 windows)", test_full_backtest_small),
        ("Percentile extraction (10 windows)", test_percentile_extraction),
    ]
    for name, fn in tests:
        print(f"\n{'='*60}")
        print(f"TEST: {name}")
        print(f"{'='*60}")
        try:
            fn()
        except Exception as e:
            print(f"  FAIL: {e}")
            import traceback
            traceback.print_exc()
