# Backtesting & Scenario Comparison — Implementation Plan

## Overview

This document describes the planned implementation of historical backtesting and
scenario comparison features for the Retirement Income Planner. Backtesting is
built first because comparison of backtest scenarios requires handling
distributions (percentile bands), not just single trajectories.

---

## 1. Data Sources

### 1.1 Existing: Shiller S&P 500 Dataset

- **File**: `data/sp500_data.csv`
- **Coverage**: Monthly, 1871-01 to 2026-02
- **Fields used**:
  - `SP500` + `Dividend` → US equity total return
  - `Long Interest Rate` → US bond return proxy
  - `Consumer Price Index` → US inflation
- **Gaps**: Recent rows (2025+) have zeroes for CPI, dividends, earnings

### 1.2 To Add: Bank of England "A Millennium of Macroeconomic Data"

- **Source**: https://www.bankofengland.co.uk/statistics/research-datasets
- **Format**: Excel spreadsheet (~28MB)
- **Coverage**: Annual, ~1700s to 2016
- **Fields needed**:
  - UK equity total returns
  - UK gilt total returns
  - UK RPI / CPI
  - Bank Rate (short-term interest rate)
- **Note**: Data ends at 2016. Needs extending to present via BoE database
  series or ONS CPI downloads.

### 1.3 To Add: ONS Consumer Price Index

- **Source**: https://www.ons.gov.uk/economy/inflationandpriceindices/datasets/consumerpriceindices
- **Format**: CSV / Excel
- **Coverage**: Monthly, 1988 to present
- **Purpose**: Extends UK CPI from 2016 to present, fills the BoE Millennium gap

### 1.4 Data Processing

All raw data will be converted to a unified annual return series stored as a
single processed JSON or CSV file:

```
data/historical_returns.json
```

Structure:
```json
{
  "metadata": {
    "generated": "2026-03-16",
    "sources": {
      "us_equity": "Shiller S&P 500 (price + dividends), 1871-2025",
      "uk_equity": "BoE Millennium dataset, ~1700-2016, extended via FTSE data",
      "us_bonds": "Derived from Shiller Long Interest Rate, 1871-2025",
      "uk_gilts": "BoE Millennium dataset, ~1700-2016",
      "uk_cpi": "BoE Millennium + ONS CPI, ~1700-present",
      "us_cpi": "Shiller CPI, 1871-2025",
      "cash": "BoE Bank Rate, ~1694-present"
    }
  },
  "annual_returns": {
    "1900": {
      "us_equity": 0.082,
      "uk_equity": 0.065,
      "us_bonds": 0.032,
      "uk_gilts": 0.028,
      "cash": 0.02,
      "uk_cpi": 0.025,
      "us_cpi": 0.018
    }
  }
}
```

---

## 2. Asset Class Mapping

### 2.1 The 6 Asset Classes (from `asset_model.json`)

| ID | Label | Historical Series |
|----|-------|-------------------|
| `global_equity` | Global Equity | Blend: 50% US equity + 50% UK equity |
| `diversified_growth` | Diversified Growth | Synthetic: 60% blended equity + 40% gilts |
| `investment_grade_bonds` | Bonds / Gilts | UK gilt total return (primary), US bonds (fallback) |
| `inflation_linked_bonds` | Inflation-Linked Bonds | Gilt return minus UK CPI change |
| `cash` | Cash / Money Market | BoE Bank Rate |
| `property` | Property / REITs | Synthetic: 70% equity + 30% bonds |

### 2.2 Benchmark Key → Asset Class Mapping

A new `benchmark_mappings` section in `asset_model.json` routes each fund's
`benchmark_key` to one of the 6 asset classes:

```json
"benchmark_mappings": {
  "developed_equity":     "global_equity",
  "global_smallcap":      "global_equity",
  "emerging_equity":      "global_equity",
  "uk_largecap":          "global_equity",
  "global_equity":        "global_equity",
  "interest_rate":        "cash",
  "money_market":         "cash",
  "uk_gilts":             "investment_grade_bonds",
  "corporate_bonds":      "investment_grade_bonds",
  "index_linked_gilts":   "inflation_linked_bonds",
  "property":             "property",
  "diversified_growth":   "diversified_growth",
  "balanced":             "diversified_growth"
}
```

### 2.3 Per-Pot Return Calculation (Backtest Mode)

For each year in a backtest period:

```
pot_return(year) = SUM( holding_weight * historical_return[asset_class][year] )
```

Where `asset_class = benchmark_mappings[holding.benchmark_key]`.

This replaces the static `growth_rate` used in deterministic mode.

---

## 3. Transparency

### 3.1 Methodology Panel

A dedicated help/info panel accessible from any backtest chart, showing:
- Data sources with date ranges
- Asset class → historical series mapping table
- Synthetic/proxy methodology for diversified_growth, inflation_linked_bonds,
  property
- Known limitations

### 3.2 Per-Pot Data Provenance

On the Settings page and in scenario details, each pot displays:
```
Consolidated DC Pot — Backtest Data Sources:
  Vanguard FTSE Dev World (38.5%) → Global Equity → 50/50 S&P 500 / UK equity
  Vanguard Global Small-Cap (37.7%) → Global Equity → 50/50 S&P 500 / UK equity
  L&G Emerging Markets (21.0%) → Global Equity → 50/50 S&P 500 / UK equity (proxy)
  iShares UK Equity (2.8%) → Global Equity → 50/50 S&P 500 / UK equity
  Cash (0.1%) → Cash → BoE Bank Rate

  Note: 3 of 5 holdings use a proxy (equity sub-classes mapped to blended global equity)
```

### 3.3 Chart Annotations

Each backtest chart includes a footer:
> "Based on [X] historical [Y]-year periods. See Methodology for data sources."

### 3.4 Scenario Badges

Saved scenarios display a badge indicating data mode:
- "Static" (deterministic growth)
- "Backtest Median"
- "Backtest P25 (pessimistic)"
- "Backtest P75 (optimistic)"
- "Backtest Worst Case"

---

## 4. Backtest Engine Design

### 4.1 Rolling Window Approach

Given a retirement plan spanning N years (e.g. age 68 to 90 = 22 years),
the backtest engine runs the projection across every possible N-year window
in the historical data:

- Window 1: 1900–1921
- Window 2: 1901–1922
- ...
- Window M: (latest_year - N) to latest_year

Each window produces a complete year-by-year projection using the actual
historical returns for that period instead of a fixed growth rate.

### 4.2 Inflation Handling

In backtest mode, the CPI/inflation rate per year is also taken from historical
data (UK CPI). This replaces the static `cpi_rate` in the config. This means
guaranteed income indexation, tax thresholds, and drawdown adjustments all
use historically accurate inflation for each window.

### 4.3 Output: Distribution of Outcomes

From M windows, extract:
- **Median** (P50): The "typical" outcome
- **Pessimistic** (P25): Worse than 75% of historical periods
- **Optimistic** (P75): Better than 75% of historical periods
- **Worst case**: The single worst historical period
- **Best case**: The single best historical period
- **Sustainability rate**: % of windows where capital lasted to plan end

### 4.4 Integration with Existing Engine

The existing `RetirementEngine.run_projection()` uses a fixed growth rate per
pot per year. For backtest mode:

1. Override `growth_rate` per pot per year with the historical weighted return
2. Override `cpi_rate` per year with historical UK CPI
3. Run `run_projection()` as normal — all drawdown strategies, tax logic, etc.
   work unchanged

This means **zero changes to the core engine logic** — backtesting is a wrapper
that calls the existing engine repeatedly with different growth/CPI inputs.

---

## 5. UI Integration

### 5.1 Dashboard

- **Toggle switch**: "Static Growth" / "Historical Backtest"
- **Static mode**: Current behaviour (single projection line)
- **Backtest mode**: Shows percentile fan chart (P25–P75 shaded band, median
  line, worst-case dashed line)
- **Transparency footer** on each chart

### 5.2 What If Sandbox

- Same toggle in the sandbox controls
- Backtest mode runs all windows and shows the fan chart
- Scenario save includes `data_mode` in metadata

### 5.3 Scenario Cards

- Badge showing data mode
- Tooltip with data provenance summary

---

## 6. Scenario Comparison

Built AFTER backtesting is complete, because comparison needs to handle both
single trajectories (static) and distributions (backtest).

### 6.1 Design Principle

**Always compare like-for-like**: static vs static, backtest vs backtest.
If the user selects a mix, output is grouped into separate sections. No
cross-mode comparisons, no warnings needed.

### 6.2 User-Driven Comparison

- Checkbox on each scenario card
- "Compare Selected" button (appears when 2+ selected)
- Output: summary table, overlay charts, year-by-year delta

### 6.3 Quick Compare Packs (One-Click)

- **Strategy Shootout**: Current config through all 6 drawdown strategies
- **Income Sensitivity**: Current strategy at target ±£2k, ±£4k
- **Retirement Age Impact**: Current config at -3, -1, 0, +2, +5 years

These inherit the active data mode (static or backtest).

### 6.4 Custom Compare

User picks: base scenario + single variable axis + values.

### 6.5 Comparison Output

- Summary table (side-by-side key metrics)
- Year-by-year delta table
- Overlay charts (capital trajectory + income trajectory)
- Key insight callouts
- For backtest scenarios: compare median trajectories, with P25/P75 bands

---

## 7. Implementation Chunks

### Phase A: Data & Engine (Backtesting)

| Chunk | Description | Priority |
|-------|-------------|----------|
| A1 | Download BoE Millennium data + ONS CPI. Build data processing script to produce `historical_returns.json`. Add `benchmark_mappings` to `asset_model.json`. | High |
| A2 | Build `backtest_engine.py` — rolling window runner that calls `RetirementEngine` per window with historical returns per pot. | High |
| A3 | Percentile extraction + transparency metadata generation. | High |
| A4 | Dashboard integration — toggle + fan chart + transparency panel. | High |
| A5 | What If integration — same toggle + fan chart in sandbox. | High |

### Phase B: Scenario Comparison

| Chunk | Description | Priority |
|-------|-------------|----------|
| B1 | Checkbox on scenario cards + Compare button + backend comparison endpoint. | High |
| B2 | Quick Compare packs (Strategy Shootout, Income Sensitivity, Retirement Age). | High |
| B3 | Comparison output UI (summary table, delta table, overlay charts). | High |
| B4 | Delta/overlay charts for compared scenarios. | Medium |
| B5 | Custom Compare UI (base + axis + values). | Medium |

---

## 8. Future Enhancements

- Add more granular historical series (Russell 2000 for small-cap, MSCI EM
  for emerging markets) to split `global_equity` into sub-classes
- Monte Carlo simulation as an alternative to historical backtesting
- Portfolio glidepath modelling (allocation changes over time toward retirement)
- International data sources for non-UK/US users
