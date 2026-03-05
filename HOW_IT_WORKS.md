# Retirement Income Planner — How It Works

**A summary of the methodology and calculations used by the application**

---

## What the Tool Does

This is a **deterministic, year-by-year retirement income projection** tool. Given a set of income sources, assets, a target net income, and assumptions about growth and inflation, it calculates whether the plan is sustainable from retirement to a chosen end age.

All figures are in **nominal (cash) terms** — inflation is applied explicitly each year rather than using real returns.

---

## Inputs

| Category | Key Parameters |
|----------|---------------|
| **Personal** | Retirement age, planning horizon (end age) |
| **Target Income** | Desired annual net income (after tax), CPI inflation rate |
| **UK State Pension** | Gross annual amount, annual indexation rate (e.g. 3.5% for triple lock) |
| **DB Pension (BP)** | Gross annual amount, annual indexation rate (e.g. 3% CPI-linked) |
| **DC Pension Pots** | Starting balance, assumed growth rate, annual fund fees, tax-free portion (default 25%) |
| **ISA** | Starting balance, assumed growth rate |
| **Withdrawal Priority** | The order in which DC pots and ISA are drawn down |
| **Tax Regime** | Isle of Man: personal allowance, tax bands and rates, optional tax cap |

All parameters are user-adjustable via the web interface.

---

## Year-by-Year Projection — Step by Step

For each year from retirement age to end age, the engine performs the following steps **in order**:

### 1. Inflate the Target Income
The target net income is increased by the CPI rate each year, compounding from the base year.

### 2. Index Guaranteed Pensions
Both the State Pension and BP pension are increased by their respective indexation rates, compounding annually.

### 3. Grow Investment Pots
Each DC pension pot grows by its assumed rate **minus annual fees** (applied to the opening balance for that year). The ISA grows by its assumed rate with no fees.

### 4. Calculate Guaranteed Net Income
The gross State Pension and BP pension are summed, and Isle of Man income tax is applied to determine the net guaranteed income.

### 5. Determine the Shortfall
If guaranteed net income is less than the inflation-adjusted target, the difference is the **shortfall** — the amount that must be drawn from DC pots or the ISA.

### 6. Withdraw from Pots in Priority Order
The shortfall is filled by withdrawing from sources in the user-defined priority order:

- **DC Pot withdrawals** — 25% of each withdrawal is tax-free; the remaining 75% is added to taxable income. The engine uses a **gross-up solver** (iterative calculation) to determine the exact gross withdrawal needed to produce the required net amount after the incremental tax is accounted for.
- **ISA withdrawals** — entirely tax-free, no impact on taxable income.

If a pot is exhausted, the engine moves to the next source in the priority list.

### 7. Calculate Final Tax for the Year
Once all withdrawals are determined, the total taxable income (guaranteed pensions + taxable portion of DC withdrawals) is run through the Isle of Man tax calculator. A parallel UK tax calculation is also performed for comparison purposes.

### 8. Record Results and Warnings
The engine records the net income achieved, all balances, tax paid, and flags any warnings (e.g. pot exhaustion, high withdrawal rates, or income shortfalls).

---

## Tax Calculations

### Isle of Man (Primary)
| Component | Value |
|-----------|-------|
| Personal Allowance | £14,500 |
| Lower Rate | 10% on first £6,500 above allowance |
| Higher Rate | 20% on all income above £21,000 |
| Tax Cap | Optional — limits total tax to a set maximum (default £200,000) |

### UK (Comparison Only)
| Component | Value |
|-----------|-------|
| Personal Allowance | £12,570 |
| Basic Rate | 20% on £12,571 – £50,270 |
| Higher Rate | 40% on £50,271 – £125,140 |
| Additional Rate | 45% above £125,140 |

The dashboard displays the **lifetime tax saving** of the IoM regime versus UK rates.

---

## DC Pension Tax-Free Allowance

Each DC withdrawal is treated as **25% tax-free and 75% taxable**, consistent with the standard pension commencement lump sum rules. This ratio is applied to every withdrawal, not as a one-off lump sum.

---

## Optimiser — Four Key Questions

The optimiser runs multiple projections with varied parameters to answer:

| # | Question | Method |
|---|----------|--------|
| **Q1** | What is the best drawdown order to maximise remaining capital? | Tests all possible orderings of DC pots and ISA; ranks by capital remaining at end age |
| **Q2** | What is the maximum sustainable annual income? | Binary search — incrementally raises the target income until the plan fails, finding the ceiling |
| **Q3** | What is the maximum age the plan can sustain? | Incrementally extends the end age year by year until the plan fails |
| **Q4** | Which drawdown order minimises lifetime tax? | Tests all orderings; ranks by total tax paid over the full projection |

---

## Scenario Comparison

Users can save multiple scenarios (e.g. different target incomes, growth rates, or end ages) and compare them side by side. The comparison shows summary metrics and overlaid capital trajectory charts.

---

## Key Assumptions and Limitations

- **Deterministic model** — uses fixed annual rates for growth, inflation, and indexation. It does not model market volatility or sequence-of-returns risk.
- **No Monte Carlo simulation** — the tool shows a single projected outcome per scenario, not a probability distribution.
- **Flat growth rates** — investment growth is applied uniformly each year (no modelling of market cycles).
- **Simplified tax** — does not model National Insurance, capital gains tax, or personal allowance tapering.
- **Annual time steps** — all calculations are per tax year, not monthly.
- **No annuity modelling** — DC pots are drawn down via flexi-access; annuity purchase is not modelled.

The recommended approach is to build in a **margin of safety** by targeting a net income below the calculated maximum sustainable figure.

---

*Document generated: March 2026 — Retirement Income Planner V1.1*
