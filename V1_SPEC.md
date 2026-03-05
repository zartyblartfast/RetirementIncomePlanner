# Retirement Income Planner — V1.0 Specification (Agreed)
**Date:** 2 March 2026  
**Status:** AGREED — ready to build

---

## 1. Purpose
Model year-by-year retirement finances from **April 2027 (age 68)** to a configurable end-age, answering:
- Can I sustain my target net income?
- How much do I need to draw from my DC pots each year?
- When do pots run out (if ever)?
- What tax do I pay each year under IoM regime?

## 2. Personal & Timeline
| Parameter | Value | Notes |
|-----------|-------|-------|
| Date of birth | July 1958 | |
| Current age | 67 | |
| Retirement date | April 2027 | Start of modelling |
| Age at retirement | 68 | |
| End age | 90 | Configurable (e.g. 85, 90, 95) |
| Tax regime | Isle of Man | Only IoM in V1.0 |
| Time step | Annual (tax-year) | April to April |
| Currency | GBP | |
| Mode | Nominal | Inflation applied explicitly |

## 3. Target Income
| Parameter | Default | Notes |
|-----------|---------|-------|
| Target net income | £30,000/year | After tax |
| Inflation rate (CPI) | 3% | Applied to target each year |
| One-off expenses | None in V1.0 | Architecture allows adding later |

## 4. Income Streams

### 4a. UK State Pension (Already drawing since age 66)
| Parameter | Value | Notes |
|-----------|-------|-------|
| Status | Active | Started at age 66 (July 2024) |
| Current gross amount | £1,140/month (£13,680/yr) | As of March 2026 |
| Indexation | Configurable % (default 3.5%) | Triple-lock proxy |
| Tax status | **Taxable in IoM** | UK State Pension remains taxable when resident in IoM; taxed by IoM Government not HMRC |

### 4b. BP Pension (Already drawing — DB scheme, index-linked)
| Parameter | Value | Notes |
|-----------|-------|-------|
| Status | Active | High-quality DB scheme |
| Current gross amount | **£837.69/month (£10,052.28/yr)** | Confirmed by user |
| Current net amount | £502/month (£6,024/yr) | After UK higher-rate tax |
| Indexation | **CPI-linked** | Confirmed index-linked |
| Tax status | Fully taxable | |

### 4c. Consolidated Private Pension (Not yet drawing)
| Parameter | Default | Notes |
|-----------|---------|-------|
| Type | DC pot (drawdown) | |
| Starting balance (at retirement) | £180,000 | Configurable |
| Annual growth rate | 4% | Configurable |
| Annual fees | 0.5% | Configurable |
| Tax-free portion per withdrawal | 25% | Configurable |
| Withdrawal priority | User-defined | |
| Minimum balance floor | £0 | Configurable |

### 4d. Employer Pension (Not yet drawing)
| Parameter | Default | Notes |
|-----------|---------|-------|
| Type | DC pot (drawdown) | |
| Starting balance (at retirement) | £95,000 | Configurable |
| Annual growth rate | 4% | Configurable |
| Annual fees | 0.5% | Configurable |
| Tax-free portion per withdrawal | 25% | Configurable |
| Withdrawal priority | User-defined | |
| Minimum balance floor | £0 | Configurable |

### 4e. ISA (Not yet drawing)
| Parameter | Default | Notes |
|-----------|---------|-------|
| Starting balance (at retirement) | £20,000 | |
| Annual growth rate | 3.5% | Configurable |
| Tax status | Tax-free | |
| Withdrawal strategy | User-defined | Options: buffer / supplement / manual |
| Withdrawal priority | User-defined | |

## 5. Withdrawal Strategy
User configures priority order for drawable sources (DC pots + ISA).
Optional percentage cap per source per year.
Default: draw DC pots first (in user-defined order), ISA last as buffer.

## 6. Tax Engine — Isle of Man
| Parameter | Default (2025/26) | Notes |
|-----------|-------------------|-------|
| Personal allowance | £14,500 | Editable |
| Lower rate band | £6,500 | Editable |
| Lower rate | 10% | Editable |
| Higher rate | 20% | Editable |
| Tax cap (optional) | Off | Toggle + amount |

**Taxable income** = State Pension (gross) + BP Pension (gross) + 75% of DC withdrawals  
**Tax-free income** = 25% of DC withdrawals + ISA withdrawals

All income is pooled and taxed under IoM bands. Personal allowance applied to total taxable income.

## 7. Core Calculation Loop
For each year from retirement to end-age:
1. Inflate target net income by CPI
2. Index guaranteed incomes (State Pension by triple-lock proxy, BP Pension by CPI)
3. Grow DC pots and ISA by (growth − fees)
4. Sum guaranteed gross income
5. Calculate tax on guaranteed income alone to determine guaranteed net income
6. Shortfall = target net − guaranteed net income
7. If shortfall > 0:
   a. Gross-up shortfall accounting for 25% tax-free DC portion + IoM marginal tax rate
   b. Withdraw from sources in priority order
   c. If all sources exhausted → flag shortfall
8. Recalculate total tax for the year (guaranteed + DC withdrawals)
9. Record achieved net income and closing balances

## 8. Outputs

### Year-by-year table (terminal + CSV export)
Columns: Age | Tax Year | Target Net | State Pension (gross) | BP Pension (gross) | DC Withdrawal (gross) | DC Tax-Free Portion | ISA Withdrawal | Total Taxable Income | Tax Due | Net Income Achieved | DC Pot 1 Balance | DC Pot 2 Balance | ISA Balance | Total Capital

### Capital trajectory chart (PNG via Matplotlib)

### Summary metrics
- Sustainability verdict (✅ / ⚠️)
- Age at which first pot exhausted
- Age at which income target can no longer be met (if applicable)
- Total tax paid over retirement
- Average effective tax rate
- Remaining total capital at end-age

### Warnings
- ⚠️ Target income unmet from age X
- ⚠️ Withdrawal rate exceeds 6% of pot value
- ⚠️ Any pot balance reaches zero

## 9. Implementation
- **Python script + JSON config file**
- Run: `python retirement_planner.py config.json`
- Multiple scenario configs supported (save as different .json files)
- Path to V1.1: Flask web UI wrapping same engine

## 10. Quick Sanity Check (Approximate)
At retirement (April 2027), approximate guaranteed gross income:
- State Pension: ~£14,160/yr (after ~1 year indexation at 3.5%)
- BP Pension: ~£10,354/yr (after ~1 year CPI indexation at 3%)
- Total guaranteed gross: ~£24,514/yr
- IoM tax on £24,514: PA £14,500 → taxable £10,014 → tax ~£1,351
- Guaranteed net: ~£23,163/yr
- Shortfall to £30,000 target: ~£6,837 net needed from DC pots
- Gross DC withdrawal needed (accounting for 25% tax-free + 20% on 75%): ~£8,200/yr
- Withdrawal rate on £275k total DC: ~3% ✅ (well within safe range)

This suggests the plan is likely sustainable to age 90 with reasonable growth assumptions.
