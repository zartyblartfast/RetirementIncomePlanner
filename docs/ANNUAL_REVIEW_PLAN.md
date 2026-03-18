# Annual Review Feature — Design & Implementation Plan

## Overview

The Annual Review feature provides a dedicated, guided workflow for post-retirement
users to update their plan annually. It replaces the current manual process of editing
pot balances in Settings, and adds tracking of actual vs planned outcomes over time.

The feature covers:
- **Bootstrap** at retirement: first-time setup of the drawdown plan
- **Annual review**: update balances, record actual drawdown, get new recommendation
- **Plan vs Actual tracking**: traffic light indicator and fan chart overlay
- **Review history**: stored snapshots viewable on the Review page

---

## 1. Page States

The Review page adapts based on the user's retirement journey:

| State | Condition | What's Shown |
|-------|-----------|-------------|
| **A: Pre-Retirement** | `current_age < retirement_age` and no reviews | Retirement date countdown, guidance message |
| **B: Bootstrap Due** | `current_age >= retirement_age` and no reviews | Welcome banner, 2-step setup wizard (balances + recommendation) |
| **C: Between Reviews** | Reviews exist, next review not yet due | Current year summary, traffic light, countdown to next review, review history |
| **D: Review Due** | Reviews exist, next review due or overdue | Alert banner, 3-step review wizard, review history |

---

## 2. Data Storage

### 2.1 Separate `reviews.json` File

Reviews are temporal events, not configuration. They live in a separate file alongside
`config_active.json`:

```
data/
  config_active.json    # Current state — settings, strategy, pot balances
  reviews.json          # Event history — annual review snapshots
```

### 2.2 `reviews.json` Schema

```json
{
  "baseline": {
    "computed_at": "2027-04-01",
    "start_age": 68,
    "strategy": "arva",
    "ages": [68, 69, 70, ...],
    "capital_percentiles": {
      "p5":  [285000, 252000, ...],
      "p10": [285000, 260000, ...],
      "p50": [285000, 279000, ...],
      "p90": [285000, 298000, ...],
      "p95": [285000, 305000, ...]
    },
    "income_percentiles": {
      "p5":  [36000, 34500, ...],
      "p10": [36000, 35200, ...],
      "p50": [36000, 36800, ...],
      "p90": [36000, 38500, ...],
      "p95": [36000, 39200, ...]
    }
  },
  "reviews": [
    {
      "review_date": "2027-04-01",
      "review_age": 68,
      "review_type": "bootstrap",
      "balances": {
        "SIPP": { "balance": 285000, "as_of": "2027-04-01" },
        "ISA":  { "balance": 45000,  "as_of": "2027-04-01" }
      },
      "actual_drawdown": null,
      "recommendation": {
        "strategy": "arva",
        "strategy_params": { "assumed_real_return_pct": 3, "target_end_age": 92 },
        "total_net_income": 36400,
        "withdrawal_plan": [
          { "source": "SIPP", "net_amount": 20100 },
          { "source": "ISA",  "net_amount": 0 }
        ],
        "sustainable": true,
        "end_age": 92
      }
    },
    {
      "review_date": "2028-04-01",
      "review_age": 69,
      "review_type": "annual",
      "balances": {
        "SIPP": { "balance": 271500, "as_of": "2028-04-01" },
        "ISA":  { "balance": 43200,  "as_of": "2028-04-01" }
      },
      "actual_drawdown": [
        { "source": "SIPP", "net_amount": 20100 },
        { "source": "ISA",  "net_amount": 2000 }
      ],
      "recommendation": {
        "strategy": "arva",
        "strategy_params": { "assumed_real_return_pct": 3, "target_end_age": 92 },
        "total_net_income": 38200,
        "withdrawal_plan": [
          { "source": "SIPP", "net_amount": 22100 },
          { "source": "ISA",  "net_amount": 0 }
        ],
        "sustainable": true,
        "end_age": 92
      }
    }
  ]
}
```

### 2.3 Settings Sync

When a review is saved:
1. Updated pot/ISA balances are written to `config_active.json` (same as Settings)
2. `values_as_of` dates are updated to match the review date
3. Settings page continues to work as the raw editor
4. No duplicate storage — `reviews.json` stores the snapshot, `config_active.json`
   stores the current state

---

## 3. Review Date Logic

- **First review date** = `retirement_date` from Settings (e.g., `2027-04`)
- **Subsequent reviews** = previous review date + 12 months
- **Tolerance**: Being a few days early or late is fine — the review date is a target,
  not a gate. The wizard is always accessible.
- **Overdue detection**: If today > next review date, show overdue banner with day count
- **Bootstrap trigger**: User-initiated (navigates to Review page). App shows a prompt
  on Dashboard when `current_age >= retirement_age` and no reviews exist.

---

## 4. Wizard Steps

### 4.1 Bootstrap (State B) — 2 Steps

**Step 1: Confirm Balances**
- Pre-fills from current Settings values
- Single review date field applied to all pots (with per-pot override checkbox)
- Shows pot names from config (`dc_pots[].name`, `tax_free_accounts[].name`)

**Step 2: Year 1 Recommendation**
- Runs projection from current_age with confirmed balances
- Runs stress test to generate baseline fan chart data
- Shows: strategy, recommended income, withdrawal sources, sustainability
- "Save & Complete Setup" button writes to both files

### 4.2 Annual Review (State D) — 3 Steps

**Step 1: Last Year's Actual Drawdown**
- Pre-fills from last review's recommendation
- User corrects to actual amounts per source
- "+ Add another source" for mid-year pot depletion edge case
- Shows total actual vs total recommended for quick comparison

**Step 2: Update Balances**
- Same as bootstrap Step 1, but also shows previous balance for reference
- Review date defaults to last review date + 12 months

**Step 3: Year Ahead Recommendation**
- Runs projection from current_age with new balances
- For stateful strategies: seeds `prior_year_drawdown` from Step 1 actuals
- Shows: recommended income, withdrawal sources, sustainability, vs-last-year delta
- "Run Stress Test" button available
- "Save Review & Update Balances" writes to both files

---

## 5. Engine Changes

### 5.1 Projection Start from Current Age

The engine already supports this via the `anchor_abs` mechanism (lines 480-500 of
`retirement_engine.py`). If `values_as_of` dates are post-retirement, the anchor
advances automatically. The Annual Review just needs to ensure the updated
`values_as_of` dates are written to config before running the projection.

No engine change needed for this — it already works.

### 5.2 Prior-Year Drawdown for Stateful Strategies

Stateful strategies (GK, Vanguard, ARVA+Guardrails) use a `state` dict that tracks
`prev_withdrawal` or `prev_gross` from the prior year. Currently, `state` starts as
`None` (first year) and the strategy computes from scratch.

For Annual Review, we need to seed the strategy state from the actual drawdown:

- Add optional `initial_strategy_state` parameter to `run_projection()`
- If provided, pass it as the initial `strategy_state` instead of `None`
- The Review wizard constructs this from the actual drawdown data in Step 1

Strategy state seeding:

| Strategy | State Key | Seeded From |
|----------|-----------|-------------|
| `guyton_klinger` | `current_target`, `prev_gross` | Actual net drawn, estimated gross |
| `vanguard_dynamic` | `current_target` | Actual net drawn |
| `arva_guardrails` | `prev_withdrawal` | Actual pot-net drawn |
| `arva` | (none needed) | Stateless — recalculates each year |
| `fixed_target` | (none needed) | Stateless |
| `fixed_percentage` | (none needed) | Stateless |

---

## 6. Traffic Light Indicator

### 6.1 Percentile Position

At each review, compare actual total capital against the baseline fan chart percentiles
at the corresponding age:

| Indicator | Condition | Label |
|-----------|-----------|-------|
| Green | Actual >= Median (P50) | **On Track** — capital is at or above the median expectation |
| Amber | Worst 10% (P10) <= Actual < Median (P50) | **Monitor** — below median but within normal historical range |
| Red | Actual < Worst 10% (P10) | **Review Plan** — capital is below the worst 10% of historical outcomes |

### 6.2 Display

User-friendly labels with technical terms bracketed for financial advisors:

```
On Track (62nd percentile)
Capital at age 70: £258,300
Above the median expectation (P50) from your baseline stress test.
```

```
Monitor (28th percentile)
Capital at age 72: £198,000
Below the median (P50) but within the normal historical range (above P10).
Consider reviewing your strategy at your next annual review.
```

```
Review Plan (7th percentile)
Capital at age 74: £142,000
Below the worst 10% of historical outcomes (P10).
Your capital is depleting faster than expected. Consider adjusting your
drawdown strategy or target income.
```

### 6.3 Interpolation

To compute the exact percentile position, linearly interpolate between the stored
percentile values (P5, P10, P50, P90, P95) at the review age.

---

## 7. Plan vs Actual Chart

### 7.1 When Available

- Not shown at bootstrap (no actual data yet)
- Available from second review onwards (one actual data point)
- Most useful from third review onwards (trend visible)

### 7.2 Chart Design

Fan chart (existing code reusable) with an overlaid bold line of actual data points:

- **Background**: 4 colour-coded bands from baseline percentiles
  - Exceptional (P90-P95) — lightest
  - Above Average (P50-P90)
  - Below Average (P10-P50)
  - Worst Case (P5-P10) — darkest/warning
- **Overlay**: Bold line with markers at each review age, showing actual capital
- **X-axis**: Age (from baseline start_age to end_age)
- **Y-axis**: Capital (£)

Separate charts for capital and income trajectories.

### 7.3 User-Friendly Band Labels

| Band | Label | Technical |
|------|-------|-----------|
| P90-P95 | Exceptional | (90th-95th percentile) |
| P50-P90 | Above Average | (50th-90th percentile) |
| P10-P50 | Below Average | (10th-50th percentile) |
| P5-P10 | Worst Case | (5th-10th percentile) |

---

## 8. Dashboard Integration

A small alert card on the Dashboard:

- **Bootstrap due**: "Your retirement date has passed. Set up your drawdown plan → [Go to Review]"
- **Review due**: "Your annual income review is due (X days overdue). [Go to Review]"
- **Between reviews (green)**: "On Track — next review due 1 Apr 2029 (142 days)"
- **Between reviews (amber)**: "Monitor — next review due 1 Apr 2029 (142 days)"
- **Between reviews (red)**: "Review Plan — consider an early review. [Go to Review]"

---

## 9. Implementation Chunks

### Chunk R1: Data Layer & Review Page Shell
**Scope**: `reviews.json` schema, Flask endpoints, page routing, 4-state rendering
- Create `reviews.json` loading/saving helpers
- Add `/review` Flask route and `review.html` template
- Add "Review" to nav bar
- Render correct state (A/B/C/D) based on retirement date and review history
- Countdown/overdue banner logic
- No wizard functionality yet — just the page shell and state detection

### Chunk R2: Bootstrap Wizard (State B)
**Scope**: Step 1 (confirm balances) + Step 2 (recommendation)
- Build 2-step accordion wizard UI
- Step 1: Pre-fill from config, review date input, per-pot balance inputs
- Step 2: Call projection endpoint, display recommendation
- "Save & Complete Setup" writes to `reviews.json` and syncs `config_active.json`
- Run stress test at bootstrap and store baseline fan chart data

### Chunk R3: Annual Review Wizard (State D)
**Scope**: Step 1 (actual drawdown) + Step 2 (balances) + Step 3 (recommendation)
- Build 3-step accordion wizard UI
- Step 1: Pre-fill from prior recommendation, actual drawdown input, multi-source support
- Step 2: Balance update with previous values shown
- Step 3: Run projection with prior-year drawdown seeding, display recommendation
- "Save Review" writes to both files

### Chunk R4: Engine — Prior-Year Drawdown Seeding
**Scope**: `run_projection()` accepts optional `initial_strategy_state`
- Add parameter to `run_projection()`
- Pass through to strategy dispatch for Year 1
- Review wizard constructs appropriate state dict per strategy type
- Tests for seeded vs unseeded projection consistency

### Chunk R5: Traffic Light & Review History
**Scope**: Percentile position calculation, traffic light display, history table
- Compute actual capital position against baseline percentiles
- Interpolate for exact percentile
- Render traffic light indicator in State C
- Render review history table with all past reviews
- Dashboard alert integration

### Chunk R6: Plan vs Actual Chart
**Scope**: Fan chart overlay with actual trajectory
- Reuse existing fan chart rendering code
- Add actual data points from review history as overlay dataset
- Capital and income charts
- User-friendly band labels with bracketed technical terms
- Only shown when 2+ reviews exist

### Chunk R7: Email Reminders (Phase 2, deferred)
**Scope**: SMTP setup, scheduled emails, user email config
- Store email in config
- Cron job to check review dates
- Email template for upcoming/overdue reviews
- Deferred — not part of initial build

---

## 10. Testing Strategy

### Unit Tests
- `test_review.py`: Review data loading/saving, date logic, percentile interpolation
- `test_engine.py`: Add tests for `initial_strategy_state` parameter
- Existing test suite must continue to pass (136 + 55 validation)

### Manual Testing
- Walk through all 4 states with different date configurations
- Bootstrap flow end-to-end
- Annual review flow end-to-end
- Verify Settings sync after review save
- Traffic light accuracy against known percentile data

---

## 11. Dependencies

- No new Python packages required
- No new JS libraries — Chart.js already available
- Fan chart rendering code from stress test feature is reusable
- Flask routing patterns consistent with existing pages
