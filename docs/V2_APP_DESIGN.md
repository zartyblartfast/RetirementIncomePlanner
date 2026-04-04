# Retirement Income Planner — V2 (JavaScript) Design Document

## 1. Vision

A client-side-only retirement income planner that runs entirely in the browser.
No server required — all user data stored in `localStorage` (or `IndexedDB` for
larger datasets). Deployable as a static site (GitHub Pages, Netlify, Vercel).

The V1 Python/Flask app remains the personal tool and serves as the **reference
implementation** for engine logic, test cases, and feature parity.

---

## 2. Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | React 18+ with TypeScript | Component model, ecosystem, type safety |
| Build | Vite | Fast dev server, simple config |
| Styling | TailwindCSS + shadcn/ui | Modern, responsive, accessible components |
| Icons | Lucide React | Clean, consistent icon set |
| Charts | Recharts (or Chart.js via react-chartjs-2) | Composable, React-native charting |
| Storage | localStorage (config) + IndexedDB (review history) | No server needed |
| Testing | Vitest + React Testing Library | Fast, compatible with Vite |
| Deployment | GitHub Pages or Netlify (static) | Free, zero-ops |

---

## 3. Page Structure

Three pages, down from six in V1:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Dashboard   │     │   What If   │     │   Review    │
│              │     │             │     │             │
│ Your Plan    │     │  Explore &  │     │  Annual     │
│ (all config  │────▶│  Compare    │     │  Review     │
│  + projection│     │  scenarios  │     │  Wizard +   │
│  + market    │     │             │     │  History    │
│  data)       │     │             │     │             │
└─────────────┘     └─────────────┘     └─────────────┘
```

### 3.1 Dashboard — "Your Plan"

Single page combining V1's Dashboard + Settings. Everything is here:

**Header cards row:**
- Net income / Target income / Sustainable? / Depletion age / IoM tax saving

**Collapsible config sections (inline-editable):**
- **Personal** — DOB, retirement date, end age, currency
- **Target Income** — net annual, CPI assumption
- **Guaranteed Income** — table of pensions (add/edit/remove rows)
- **DC Pots** — table of pots with balances, growth rates, fees, holdings
- **Tax-Free Accounts** — ISA etc, same structure as DC pots
- **Withdrawal Priority** — drag-to-reorder list
- **Tax Regime** — IoM/UK toggle, bands, personal allowance

Each section has an **Edit** button that expands an inline form. Changes update
the projection chart and year-by-year table **immediately** (reactive).

**Below config sections:**
- Income & Capital projection chart (same as V1 Dashboard)
- Year-by-year projection table (expandable tax/waterfall/P&L rows)
- Live Market Data intelligence card (if Market Data API configured)

**Key UX improvements over V1:**
- No separate Settings page — eliminates "where do I change X?" confusion
- Immediate visual feedback on any config change
- Collapsible sections keep the page clean when not editing

### 3.2 What If — "Explore & Compare"

Sandbox environment for scenario analysis. Four clear tabs:

#### Tab 1: Adjust
- Shows a **compact read-only summary** of the current Dashboard config
- User can **override** any value (income target, growth rates, retirement date, pot balances)
- Overrides are visually distinct (highlighted border/background)
- A **live projection chart** updates as values change
- Clear **"Reset to Dashboard"** button to discard all overrides

#### Tab 2: Compare
- **Save** the current adjusted scenario as a named snapshot
- Select 2–3 scenarios to compare side-by-side
- **Income overlay chart** — net income lines for each scenario
- **Capital overlay chart** — total capital lines for each scenario
- **Key differences table** — depletion age, total income, total tax for each

#### Tab 3: Stress Test
- Run historical backtest (104 rolling 22-year windows, 1900–2024)
- Applied to the current adjusted scenario (or Dashboard baseline)
- **Fan chart** — P10/P25/P50/P75/P90 capital trajectories
- **Percentile income table** — worst/median/best income by age
- **Depletion risk** — % of windows where capital runs out before end age
- **Scenario summary card** — median depletion age, worst-case income shortfall

#### Tab 4: Strategy Shootout
- Run all 6 strategies under historical stress on the current scenario
- Comparison table: strategy × median income × worst income × depletion age × volatility
- Recommendation badge on the "best fit" strategy
- **"Optimise" button** — launches a guided wizard (modal/drawer):

#### Optimise Wizard (modal, launched from Strategy Shootout or Adjust tab)

Replaces V1's standalone Optimise page with a streamlined 3-step modal:

```
Step 1: "What matters most?"
  → Maximise income / Preserve capital / Balance both
  → Sets the objective function for the recommendation

Step 2: "Your risk comfort"
  → Shows Strategy Shootout results filtered by Step 1 preference
  → User picks a comfort level: Conservative / Moderate / Aggressive
  → Or accepts the auto-recommendation

Step 3: "Recommendation"
  → Best strategy + recommended income target
  → Mini projection chart showing the outcome
  → "Apply to What If" button (updates Adjust tab overrides)
  → "Apply to Dashboard" button (saves to real config)
```

This keeps all exploration on the What If page — no separate Optimise page needed.

**Key UX improvements over V1:**
- Tabs make the workflow sequential and discoverable
- "Adjust" tab replaces the confusing "sandbox overrides" scattered across the page
- Compare tab replaces the checkbox-based overlay which was hard to discover
- Each tab is self-contained with a clear purpose
- Optimise is contextual — launched from within the exploration flow, not a separate page

### 3.3 Review — "Annual Review"

Post-retirement only. Same state machine as V1 (A/B/C/D):

| State | Condition | View |
|-------|-----------|------|
| Pre-Retirement | Before retirement date | Countdown + guidance |
| Bootstrap Due | At/past retirement, no reviews | 2-step wizard: enter balances → get recommendation |
| Between Reviews | Reviews exist, next not due | Summary card + traffic light + history table |
| Review Due | Next review due/overdue | 3-step wizard: update balances → enter actuals → new recommendation |

**Key UX improvements over V1:**
- Traffic light (green/amber/red) comparing actual vs planned income
- Review history table with expandable detail per year
- Dashboard banner when review is due (cross-page alert)

---

## 4. Data Model

All data stored in the browser. Two storage keys:

### 4.1 `rip-config` (localStorage)

Same structure as V1's `config_active.json`:

```json
{
  "personal": {
    "date_of_birth": "1958-07",
    "retirement_date": "2027-04",
    "end_age": 90,
    "currency": "GBP"
  },
  "target_income": {
    "net_annual": 30000,
    "cpi_rate": 0.03
  },
  "guaranteed_income": [...],
  "dc_pots": [...],
  "tax_free_accounts": [...],
  "withdrawal_priority": [...],
  "tax": {...},
  "drawdown_strategy": "fixed_target",
  "strategy_params": {...}
}
```

### 4.2 `rip-reviews` (localStorage or IndexedDB)

Same structure as V1's `reviews.json`:

```json
{
  "baseline": { ... },
  "reviews": [
    {
      "review_date": "2028-04-01",
      "review_type": "annual",
      "actual_balances": { ... },
      "actual_income_drawn": 38000,
      "recommendation": { ... },
      "config_snapshot": { ... }
    }
  ]
}
```

### 4.3 `rip-scenarios` (localStorage)

What If saved scenarios:

```json
{
  "scenarios": [
    {
      "id": "uuid",
      "name": "Conservative 3%",
      "created_at": "2027-05-01T10:00:00Z",
      "overrides": { ... },
      "config_snapshot": { ... }
    }
  ]
}
```

### 4.4 Import/Export

- **Export**: Download full state as a single JSON file (config + reviews + scenarios)
- **Import**: Upload JSON to restore state
- **Migration from V1**: Paste V1 `config_active.json` content to import

---

## 5. Engine Port

The projection engine must be ported from Python to TypeScript. The V1 engine
is the reference implementation with 158 test cases.

### 5.1 Modules to Port

| V1 Python Module | V2 TypeScript Module | Purpose |
|------------------|---------------------|---------|
| `retirement_engine.py` | `engine/projection.ts` | Monthly stepping projection |
| `drawdown_strategies.py` | `engine/strategies.ts` | 6 drawdown strategies |
| `backtest_engine.py` | `engine/backtest.ts` | Historical stress test (rolling windows) |
| `market_data.py` | `engine/market-data.ts` | Fetch live market data from API |
| `tax_bands.py` | `engine/tax.ts` | IoM + UK tax calculations |

### 5.2 Key Engine Behaviours to Preserve

1. **Monthly stepping** — growth, fees, withdrawals monthly; tax annual
2. **Date-driven** — `retirement_date` + DOB → retirement age (not config integer)
3. **Guaranteed income** — `start_date`/`end_date` (YYYY-MM) as source of truth
4. **Tax-free portion** — 25% of DC withdrawals are tax-free
5. **Withdrawal priority** — ordered list of pots to draw from
6. **CPI escalation** — target income and guaranteed income grow with CPI
7. **Strategy state** — ARVA/GK/etc carry state year-to-year (portfolio value, ceiling, floor)

### 5.3 Test Strategy

- Port all 158 V1 test cases to Vitest
- Engine output must match V1 within ±£1 tolerance (floating point)
- Use V1's `config_default.json` and QA scenario configs as test fixtures
- Run V1 Python engine on each fixture, capture output JSON as "expected"
- TypeScript tests compare against these expected outputs

---

## 6. Onboarding Flow

First-time user (no `rip-config` in localStorage) gets a guided wizard:

```
Step 1: Personal Details
  → DOB, retirement date, end age

Step 2: Your Pensions
  → Add guaranteed income sources (State Pension, DB pensions)
  → Name, annual amount, start date, indexation rate

Step 3: Your Pots
  → Add DC pots and ISAs
  → Name, balance, growth rate, fees

Step 4: Target Income
  → Desired net annual income in retirement
  → CPI assumption

Step 5: Your First Projection
  → Show the projection chart
  → "Your money lasts until age X" / "Shortfall at age Y"
  → CTA: "Explore What If scenarios" or "Go to Dashboard"
```

After onboarding, the user lands on the Dashboard with all sections populated.

---

## 7. Market Data Integration

Optional feature — works without it, enhanced with it.

- If a Market Data API URL is configured (env var or settings toggle), the app
  fetches live benchmark returns, CPI, SONIA
- Dashboard shows the Live Market Data card (same as V1)
- If API is unreachable, the app silently falls back to planning assumptions
- Health check available at a diagnostic URL

For the public JS app, the Market Data API URL could be:
- User-provided (they host their own instance)
- A default public endpoint (if we choose to provide one)
- Omitted entirely (app works fine without it)

---

## 8. Non-Goals for V2 MVP

Features deliberately excluded from the first release:

- **Authentication/login** — no server, no accounts; single-user browser storage
- ~~Optimise page~~ — integrated as a guided wizard modal within What If (see §3.2)
- **Validation page** — developer tool, not needed in the public app
- **Email reminders** — requires a server; out of scope for client-only app
- **Multi-user / sharing** — single browser instance; export/import covers collaboration
- **How It Works page** — replace with contextual tooltips and an About modal

---

## 9. Migration Path

```
V1 (Python/Flask, personal)          V2 (TypeScript/React, public)
─────────────────────────────        ─────────────────────────────
config_active.json          ──────▶  localStorage rip-config
reviews.json                ──────▶  localStorage rip-reviews
scenarios/*.json            ──────▶  localStorage rip-scenarios
retirement_engine.py        ──────▶  engine/projection.ts
drawdown_strategies.py      ──────▶  engine/strategies.ts
backtest_engine.py          ──────▶  engine/backtest.ts
158 pytest tests            ──────▶  158 vitest tests
```

Users of V1 can export their config and import into V2.

---

## 10. Implementation Phases

### Phase 1: Engine + Core UI
- [ ] New repo: `RetirementIncomePlannerV2`
- [ ] Project scaffold: Vite + React + TypeScript + TailwindCSS + shadcn/ui
- [ ] Port engine modules to TypeScript with matching test suite
- [ ] Dashboard page: config display + inline editing + projection chart + year-by-year table
- [ ] Onboarding wizard
- [ ] localStorage persistence (config save/load)
- [ ] Import/Export JSON

### Phase 2: What If
- [ ] Tab 1: Adjust (sandbox overrides + live projection)
- [ ] Tab 2: Compare (save/load scenarios, overlay charts)
- [ ] Tab 3: Stress Test (backtest engine + fan chart + percentile table)
- [ ] Tab 4: Strategy Shootout

### Phase 3: Review
- [ ] Review page state machine (A/B/C/D)
- [ ] Bootstrap wizard
- [ ] Annual review wizard
- [ ] Review history table
- [ ] Traffic light indicator
- [ ] Dashboard alert for review due

### Phase 4: Polish
- [ ] Market Data API integration (optional)
- [ ] Responsive mobile layout
- [ ] Accessibility audit
- [ ] Performance optimisation (Web Workers for backtest)
- [ ] PWA support (offline capable)
