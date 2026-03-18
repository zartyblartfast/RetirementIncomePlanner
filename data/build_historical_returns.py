"""
Build unified historical_returns.json from three data sources:
  1. Shiller S&P 500 CSV  — US equity (price+dividends), US bonds, US CPI
  2. BoE Millennium XLSX   — UK share prices, gilt yields, Bank Rate, UK CPI
  3. ONS mm23.csv          — Modern UK CPI (extends BoE data to present)

Output: data/historical_returns.json
  - Annual return series for each asset class proxy
  - Metadata documenting sources, coverage, and limitations
"""

import json
import math
import os
import sys

import pandas as pd
import numpy as np

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
BOE_FILE = os.path.join(DATA_DIR, "a-millennium-of-macroeconomic-data-for-the-uk.xlsx")
SP500_FILE = os.path.join(DATA_DIR, "sp500_data.csv")
ONS_FILE = os.path.join(DATA_DIR, "mm23.csv")
OUTPUT_FILE = os.path.join(DATA_DIR, "historical_returns.json")

# ── Usable start year: we need overlapping data from all key sources ──
# S&P 500 starts 1871; BoE share prices ~1700; BoE CPI ~1209; Bank Rate 1694
# For practical backtesting, start at 1900 (good coverage across all series)
START_YEAR = 1900

# ===========================================================================
#  1. Load S&P 500 data (monthly → annual)
# ===========================================================================
print("Loading S&P 500 data...")
sp = pd.read_csv(SP500_FILE)
sp["Date"] = pd.to_datetime(sp["Date"])
sp["Year"] = sp["Date"].dt.year

# Annual: use December values (or last available month per year)
sp_annual = sp.groupby("Year").last().reset_index()

# US Equity total return: price change + dividend yield
# Total return ≈ (P1 + D) / P0 - 1
us_equity_returns = {}
for i in range(1, len(sp_annual)):
    yr = int(sp_annual.iloc[i]["Year"])
    p1 = sp_annual.iloc[i]["SP500"]
    p0 = sp_annual.iloc[i - 1]["SP500"]
    div = sp_annual.iloc[i]["Dividend"]  # already annualised in Shiller data
    if p0 > 0 and div >= 0:
        total_return = (p1 + div) / p0 - 1
        us_equity_returns[yr] = round(total_return, 6)

# US CPI inflation: annual change in CPI
us_cpi = {}
for i in range(1, len(sp_annual)):
    yr = int(sp_annual.iloc[i]["Year"])
    c1 = sp_annual.iloc[i]["Consumer Price Index"]
    c0 = sp_annual.iloc[i - 1]["Consumer Price Index"]
    if c0 > 0 and c1 > 0:
        us_cpi[yr] = round(c1 / c0 - 1, 6)

# US bond proxy: approximate total return from long-term interest rate
# Bond return ≈ yield + duration_effect × (−Δyield)
# Assume ~10yr duration for long bonds
BOND_DURATION = 10
us_bond_returns = {}
for i in range(1, len(sp_annual)):
    yr = int(sp_annual.iloc[i]["Year"])
    y1 = sp_annual.iloc[i]["Long Interest Rate"] / 100  # percent → decimal
    y0 = sp_annual.iloc[i - 1]["Long Interest Rate"] / 100
    if y0 > 0 and y1 > 0:
        coupon_return = y0  # income from holding at last year's yield
        price_return = -BOND_DURATION * (y1 - y0)
        us_bond_returns[yr] = round(coupon_return + price_return, 6)

print(f"  US equity: {min(us_equity_returns)}-{max(us_equity_returns)} ({len(us_equity_returns)} years)")
print(f"  US bonds:  {min(us_bond_returns)}-{max(us_bond_returns)} ({len(us_bond_returns)} years)")
print(f"  US CPI:    {min(us_cpi)}-{max(us_cpi)} ({len(us_cpi)} years)")

# ===========================================================================
#  2. Load BoE Millennium data (annual)
# ===========================================================================
print("\nLoading BoE Millennium data...")
xl = pd.ExcelFile(BOE_FILE)

# ── A31: Interest rates & asset prices ──
df_a31 = pd.read_excel(xl, sheet_name='A31. Interest rates & asset ps ', header=None, skiprows=7)
# Col 0=Year, 1=Bank Rate, 18=10yr gilt yield, 19=Consol yield, 22=Share price index

uk_share_prices = {}
uk_gilt_yields = {}
uk_bank_rate = {}
for _, row in df_a31.iterrows():
    yr = row.iloc[0]
    if not isinstance(yr, (int, float)) or math.isnan(yr):
        continue
    yr = int(yr)

    # Bank Rate (col 1)
    v = row.iloc[1]
    if isinstance(v, (int, float)) and not math.isnan(v):
        uk_bank_rate[yr] = v / 100  # percent → decimal

    # 10yr gilt yield (col 18), fallback to consol yield (col 19)
    v18 = row.iloc[18] if 18 < len(row) else None
    v19 = row.iloc[19] if 19 < len(row) else None
    gilt_yield = None
    if isinstance(v18, (int, float)) and not math.isnan(v18):
        gilt_yield = v18 / 100
    elif isinstance(v19, (int, float)) and not math.isnan(v19):
        gilt_yield = v19 / 100
    if gilt_yield is not None:
        uk_gilt_yields[yr] = gilt_yield

    # Share price index (col 22)
    v22 = row.iloc[22] if 22 < len(row) else None
    if isinstance(v22, (int, float)) and not math.isnan(v22):
        uk_share_prices[yr] = v22

# UK equity price returns (no dividends — noted as limitation)
uk_equity_price_returns = {}
sorted_years = sorted(uk_share_prices.keys())
for i in range(1, len(sorted_years)):
    yr = sorted_years[i]
    prev_yr = sorted_years[i - 1]
    if prev_yr == yr - 1:  # consecutive years
        p0 = uk_share_prices[prev_yr]
        p1 = uk_share_prices[yr]
        if p0 > 0:
            uk_equity_price_returns[yr] = round(p1 / p0 - 1, 6)

# UK gilt total return (approximate: yield + duration × −Δyield)
uk_gilt_returns = {}
sorted_gilt_years = sorted(uk_gilt_yields.keys())
for i in range(1, len(sorted_gilt_years)):
    yr = sorted_gilt_years[i]
    prev_yr = sorted_gilt_years[i - 1]
    if prev_yr == yr - 1:
        y0 = uk_gilt_yields[prev_yr]
        y1 = uk_gilt_yields[yr]
        if y0 > 0 and y1 > 0:
            coupon = y0
            price_chg = -BOND_DURATION * (y1 - y0)
            uk_gilt_returns[yr] = round(coupon + price_chg, 6)

print(f"  UK share prices: {min(uk_share_prices)}-{max(uk_share_prices)} ({len(uk_share_prices)} years)")
print(f"  UK equity price returns: {min(uk_equity_price_returns)}-{max(uk_equity_price_returns)}")
print(f"  UK gilt yields: {min(uk_gilt_yields)}-{max(uk_gilt_yields)} ({len(uk_gilt_yields)} years)")
print(f"  UK gilt returns: {min(uk_gilt_returns)}-{max(uk_gilt_returns)}")
print(f"  UK Bank Rate: {min(uk_bank_rate)}-{max(uk_bank_rate)} ({len(uk_bank_rate)} years)")

# ── A47: Wages and prices — UK CPI ──
df_a47 = pd.read_excel(xl, sheet_name='A47. Wages and prices', header=None, skiprows=6)
# Col 0=Year, 3=CPI index (2015=100), 4=CPI inflation rate

uk_cpi_index_boe = {}
uk_cpi_inflation_boe = {}
for _, row in df_a47.iterrows():
    yr = row.iloc[0]
    if not isinstance(yr, (int, float)) or math.isnan(yr):
        continue
    yr = int(yr)

    v3 = row.iloc[3] if 3 < len(row) else None
    if isinstance(v3, (int, float)) and not math.isnan(v3):
        uk_cpi_index_boe[yr] = v3

    v4 = row.iloc[4] if 4 < len(row) else None
    if isinstance(v4, (int, float)) and not math.isnan(v4):
        uk_cpi_inflation_boe[yr] = round(v4 / 100, 6)  # percent → decimal

print(f"  UK CPI index (BoE): {min(uk_cpi_index_boe)}-{max(uk_cpi_index_boe)}")
print(f"  UK CPI inflation (BoE): {min(uk_cpi_inflation_boe)}-{max(uk_cpi_inflation_boe)}")

# ===========================================================================
#  3. Load ONS CPI to extend UK CPI beyond 2016
# ===========================================================================
print("\nLoading ONS CPI data...")
df_ons = pd.read_csv(ONS_FILE, low_memory=False)
d7bt_col = "CPI INDEX 00: ALL ITEMS 2015=100"

ons_cpi_monthly = {}
for r in range(len(df_ons)):
    date_str = str(df_ons.iloc[r, 0]).strip()
    cpi_val = df_ons[d7bt_col].iloc[r]
    try:
        cpi_float = float(cpi_val)
    except (ValueError, TypeError):
        continue
    # Parse date like "2020 JAN"
    parts = date_str.split()
    if len(parts) == 2:
        try:
            year = int(parts[0])
            ons_cpi_monthly[(year, parts[1])] = cpi_float
        except ValueError:
            continue

# Convert monthly to annual (December or last available month per year)
MONTH_ORDER = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
               "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

ons_cpi_annual = {}
years_in_ons = sorted(set(k[0] for k in ons_cpi_monthly))
for yr in years_in_ons:
    # Take December if available, else last available month
    for month in reversed(MONTH_ORDER):
        if (yr, month) in ons_cpi_monthly:
            ons_cpi_annual[yr] = ons_cpi_monthly[(yr, month)]
            break

# Compute ONS-based inflation for years beyond BoE coverage
uk_cpi_inflation_ons = {}
sorted_ons_years = sorted(ons_cpi_annual.keys())
for i in range(1, len(sorted_ons_years)):
    yr = sorted_ons_years[i]
    prev_yr = sorted_ons_years[i - 1]
    if prev_yr == yr - 1:
        c0 = ons_cpi_annual[prev_yr]
        c1 = ons_cpi_annual[yr]
        if c0 > 0:
            uk_cpi_inflation_ons[yr] = round(c1 / c0 - 1, 6)

print(f"  ONS CPI annual: {min(ons_cpi_annual)}-{max(ons_cpi_annual)} ({len(ons_cpi_annual)} years)")
print(f"  ONS CPI inflation: {min(uk_cpi_inflation_ons)}-{max(uk_cpi_inflation_ons)}")

# ===========================================================================
#  4. Merge into unified annual series
# ===========================================================================
print("\nBuilding unified annual return series...")

# Determine year range
all_years = set()
for d in [us_equity_returns, uk_equity_price_returns, uk_gilt_returns,
          uk_bank_rate, uk_cpi_inflation_boe, uk_cpi_inflation_ons, us_cpi]:
    all_years.update(d.keys())
year_range = sorted(yr for yr in all_years if yr >= START_YEAR)

# Merge UK CPI: BoE up to 2016, ONS from 2017+
uk_cpi_merged = {}
for yr in year_range:
    if yr in uk_cpi_inflation_boe:
        uk_cpi_merged[yr] = uk_cpi_inflation_boe[yr]
    elif yr in uk_cpi_inflation_ons:
        uk_cpi_merged[yr] = uk_cpi_inflation_ons[yr]

# Build the main output structure
annual_returns = {}
stats = {
    "us_equity": {"count": 0, "min_yr": None, "max_yr": None},
    "uk_equity_price": {"count": 0, "min_yr": None, "max_yr": None},
    "us_bonds": {"count": 0, "min_yr": None, "max_yr": None},
    "uk_gilts": {"count": 0, "min_yr": None, "max_yr": None},
    "cash": {"count": 0, "min_yr": None, "max_yr": None},
    "uk_cpi": {"count": 0, "min_yr": None, "max_yr": None},
    "us_cpi": {"count": 0, "min_yr": None, "max_yr": None},
}

for yr in year_range:
    entry = {}

    # US equity total return (price + dividends)
    if yr in us_equity_returns:
        entry["us_equity"] = us_equity_returns[yr]

    # UK equity price return (no dividends)
    if yr in uk_equity_price_returns:
        entry["uk_equity_price"] = uk_equity_price_returns[yr]

    # US bonds (from long interest rate)
    if yr in us_bond_returns:
        entry["us_bonds"] = us_bond_returns[yr]

    # UK gilts (from gilt yield changes)
    if yr in uk_gilt_returns:
        entry["uk_gilts"] = uk_gilt_returns[yr]

    # Cash (Bank Rate)
    if yr in uk_bank_rate:
        entry["cash"] = uk_bank_rate[yr]

    # UK CPI inflation (merged BoE + ONS)
    if yr in uk_cpi_merged:
        entry["uk_cpi"] = uk_cpi_merged[yr]

    # US CPI inflation
    if yr in us_cpi:
        entry["us_cpi"] = us_cpi[yr]

    if entry:
        annual_returns[str(yr)] = entry

    # Track stats
    for key in entry:
        mapped_key = key
        if mapped_key in stats:
            stats[mapped_key]["count"] += 1
            if stats[mapped_key]["min_yr"] is None:
                stats[mapped_key]["min_yr"] = yr
            stats[mapped_key]["max_yr"] = yr

# ===========================================================================
#  5. Write output
# ===========================================================================
output = {
    "metadata": {
        "generated": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "start_year": START_YEAR,
        "description": "Unified annual historical return series for retirement backtesting",
        "series": {
            "us_equity": {
                "description": "S&P 500 total return (price change + dividends)",
                "source": "Robert Shiller S&P 500 dataset",
                "coverage": f"{stats['us_equity']['min_yr']}-{stats['us_equity']['max_yr']}",
                "includes_dividends": True,
                "notes": "Monthly data annualised using December values"
            },
            "uk_equity_price": {
                "description": "UK share price return (capital gains only, NO dividends)",
                "source": "Bank of England Millennium dataset, sheet A31 col 22",
                "coverage": f"{stats['uk_equity_price']['min_yr']}-{stats['uk_equity_price']['max_yr']}",
                "includes_dividends": False,
                "notes": "Spliced annual index. Dividend yield not available in source data. "
                         "Historically UK dividend yield was ~3-5%. Total return would be higher."
            },
            "us_bonds": {
                "description": "US long-term bond total return (approximate)",
                "source": "Derived from Shiller Long Interest Rate",
                "coverage": f"{stats['us_bonds']['min_yr']}-{stats['us_bonds']['max_yr']}",
                "notes": "Approximated as: yield + 10yr_duration × (−Δyield)"
            },
            "uk_gilts": {
                "description": "UK gilt total return (approximate)",
                "source": "Derived from BoE Millennium gilt yields (A31 cols 18/19)",
                "coverage": f"{stats['uk_gilts']['min_yr']}-{stats['uk_gilts']['max_yr']}",
                "notes": "Approximated as: yield + 10yr_duration × (−Δyield). "
                         "Uses 10yr gilt yield where available, consol yield as fallback."
            },
            "cash": {
                "description": "UK Bank Rate (cash return proxy)",
                "source": "Bank of England Millennium dataset, sheet A31 col 1",
                "coverage": f"{stats['cash']['min_yr']}-{stats['cash']['max_yr']}",
                "notes": "Bank Rate used as proxy for short-term cash/money market returns"
            },
            "uk_cpi": {
                "description": "UK CPI annual inflation rate",
                "source": "BoE Millennium (A47 col 4) to 2016, ONS D7BT from 2017",
                "coverage": f"{stats['uk_cpi']['min_yr']}-{stats['uk_cpi']['max_yr']}",
                "notes": "BoE series is 'preferred CPI measure'. ONS extends to present."
            },
            "us_cpi": {
                "description": "US CPI annual inflation rate",
                "source": "Robert Shiller S&P 500 dataset (Consumer Price Index column)",
                "coverage": f"{stats['us_cpi']['min_yr']}-{stats['us_cpi']['max_yr']}",
                "notes": "Annual change in monthly CPI level"
            }
        },
        "asset_class_mapping": {
            "global_equity": {
                "method": "Weighted blend: 70% us_equity + 30% uk_equity_price",
                "notes": "UK component understates total return due to missing dividends. "
                         "US component (S&P 500) includes dividends. "
                         "US weighting higher because it includes total return."
            },
            "diversified_growth": {
                "method": "Synthetic: 60% global_equity + 40% uk_gilts",
                "notes": "Approximates a balanced multi-asset fund"
            },
            "investment_grade_bonds": {
                "method": "uk_gilts (primary), us_bonds (fallback)",
                "notes": "UK gilt returns used where available"
            },
            "inflation_linked_bonds": {
                "method": "uk_gilts - uk_cpi",
                "notes": "Crude approximation: nominal gilt return minus inflation"
            },
            "cash": {
                "method": "UK Bank Rate (direct)",
                "notes": "Actual cash returns may differ from policy rate"
            },
            "property": {
                "method": "Synthetic: 70% global_equity + 30% uk_gilts",
                "notes": "Proxy for REIT-like returns. No direct UK property data in source."
            }
        },
        "limitations": [
            "UK equity returns are PRICE ONLY (no dividends). Historical UK dividend yield was ~3-5%, "
            "so actual total returns were higher than shown.",
            "Bond returns are approximated from yield changes using 10-year duration assumption. "
            "Actual bond returns depend on the specific maturity held.",
            "BoE Millennium data ends at 2016. 2017+ uses S&P 500 data only for equity/bonds.",
            "Property returns are synthetic (no direct historical UK property data in sources used).",
            "All series assume annual rebalancing and ignore transaction costs.",
            "Historical returns are not indicative of future performance."
        ]
    },
    "annual_returns": annual_returns
}

with open(OUTPUT_FILE, "w") as f:
    json.dump(output, f, indent=2)

# ===========================================================================
#  Summary
# ===========================================================================
print(f"\nOutput written to: {OUTPUT_FILE}")
print(f"Years: {START_YEAR} to {max(int(k) for k in annual_returns)}")
print(f"Total year entries: {len(annual_returns)}")
print("\nSeries coverage:")
for key, s in stats.items():
    print(f"  {key:20s}: {s['count']:4d} years  ({s['min_yr']}-{s['max_yr']})")

# Quick sanity check: print a few sample years
print("\nSample data:")
for sample_yr in ["1929", "1973", "2000", "2008", "2020"]:
    if sample_yr in annual_returns:
        d = annual_returns[sample_yr]
        print(f"  {sample_yr}: US_eq={d.get('us_equity','N/A'):+.3f}  "
              f"UK_eq_p={d.get('uk_equity_price','N/A')}  "
              f"UK_gilts={d.get('uk_gilts','N/A')}  "
              f"Cash={d.get('cash','N/A')}  "
              f"UK_CPI={d.get('uk_cpi','N/A')}")
