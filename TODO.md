# Retirement Income Planner — To-Do / Open Items
**Last updated:** 6 March 2026

## ✅ Resolved
- [x] BP Pension gross amount — **£837.69/month (£10,052.28/yr)**
- [x] State Pension IoM tax treatment — **Taxable in IoM** (taxed by IoM Government)
- [x] BP Pension indexation — **CPI-linked (index-linked confirmed)**
- [x] Date of birth — **July 1958**
- [x] Implementation approach — **Python + JSON config (Option B)** confirmed

## 🔲 User Decisions (Not Blocking V1.0 Build)
- [ ] DC pot withdrawal order — user to decide or get financial advisor input (will be configurable in JSON)
- [ ] ISA withdrawal strategy — user to decide (default: buffer/last resort)

## 🔨 Build Tasks
- [ ] Create JSON config schema with all parameters
- [ ] Create default config with user's baseline values
- [ ] Implement IoM tax engine
- [ ] Implement income indexation (State Pension + BP Pension)
- [ ] Implement DC pot growth and drawdown
- [ ] Implement ISA growth and withdrawal
- [ ] Implement gross-up solver (iterative: find gross withdrawal to meet net target)
- [ ] Implement year-by-year calculation loop
- [ ] Output: formatted terminal table
- [ ] Output: CSV export
- [ ] Output: capital trajectory chart (Matplotlib PNG)
- [ ] Output: summary metrics and warnings
- [ ] Testing with default scenario

## 🆕 V1 Feature: Pre-Retirement Phase Awareness

### Overview
Make the app aware of whether the user is in a pre-retirement or post-retirement phase
relative to today's date, and handle DC pot / ISA balances accordingly. The projection
always shows a **forward-looking view from the most recent known state**.

### 1. Engine: Pre-Retirement Growth for DC Pots and ISAs
- Add `values_as_of` field (YYYY-MM) to DC pots and tax-free accounts in config schema.
- In `run_projection()`, if `values_as_of` is set and retirement date is after that date:
  - **DC pots**: grow `starting_balance` forward by `(growth_rate - annual_fees)` for the gap period.
  - **ISAs / tax-free accounts**: grow `starting_balance` forward by `growth_rate` (no fees) for the gap period.
- Uses the same fractional-year compounding approach already used for guaranteed income.
- If `values_as_of` is blank/missing, treat `starting_balance` as the retirement-date value (backward compatible — no behaviour change for existing configs).

### 2. Engine: Post-Retirement Projection Anchor
- When `values_as_of` on any pot/account implies a post-retirement date, the projection
  start point shifts to the age corresponding to the **latest** `values_as_of` across all
  sources (pots, accounts, and guaranteed income).
- The engine only projects **forward from that anchor age** — no fictional history.
- **Amendment 1**: Pots with a `values_as_of` earlier than the anchor age are grown forward
  to the anchor using their configured growth rate, mirroring the pre-retirement compounding
  logic. This ensures consistency when pots are updated at different times.
- **Amendment 2**: Guaranteed income auto-indexes to the anchor age using existing
  `values_as_of` + indexation logic — no manual update required unless actual amounts
  differ from the indexed estimate.

### 3. UI: Phase Indicator Banner
- Dashboard and Settings show a contextual banner comparing today's date to `retirement_date`:
  - **Pre-retirement**: *"Retirement: April 2027 (13 months away). Pot balances are projected forward from their 'as of' dates to retirement."*
  - **Post-retirement**: *"Retirement started April 2027. Showing projection from age X (your latest values) to age Y."*
  - **At retirement** (within ±1 month): *"Retirement is now. Ensure all balances reflect current values."*

### 4. UI: Staleness Warning (Amendment 3)
- Compare each pot/account's `values_as_of` to today's date.
- Display warning badges on Dashboard and Settings:
  - **< 6 months**: no warning
  - **6–12 months**: 🟡 amber — *"Values last updated X months ago"*
  - **> 12 months**: 🔴 red — *"Values last updated X months ago — consider updating"*

### 5. UI: DC Pot and ISA Value Entry Guidance
- Rename "Starting Balance" label to **"Current Balance"** (or similar).
- Add helper text:
  - Pre-retirement: *"Enter today's value — the engine will estimate growth to your retirement date. Update regularly for best accuracy."*
  - Post-retirement: *"Enter today's actual value — the projection will recalculate from this point forward. Update all pots and income together."*
- Display `values_as_of` date alongside each pot (same pattern as guaranteed income).
- When pre-retirement growth is applied, show the **projected retirement-date value** alongside the entered value, e.g.: *"£180,000 (as of Mar 2026) → est. £186,500 at retirement"*.
- For guaranteed income: *"Guaranteed income is automatically indexed forward. Update manually only if actual amounts differ from the indexed estimate."*

### Implementation Chunks
To manage complexity and avoid long single changes:

| Chunk | Scope | Files |
|-------|-------|-------|
| ✅ **C1** | Config schema: add `values_as_of` to DC pots and ISAs in `config_default.json` | `config_default.json` |
| ✅ **C2** | Engine: pre-retirement growth compounding for DC pots and ISAs | `retirement_engine.py` |
| ✅ **C3** | Engine: post-retirement anchor logic (determine anchor age, grow stale pots forward) | `retirement_engine.py` |
| ✅ **C4** | UI: Settings page — label changes, helper text, `values_as_of` inputs for pots | `settings.html`, `app.py` |
| ✅ **C5** | UI: Dashboard + Settings — phase banner and staleness warnings | `dashboard.html`, `settings.html`, `app.py` |
| ✅ **C6** | UI: Settings — projected retirement-date value display | `settings.html`, `app.py` |
| **C7** | Deploy all changes to VPS + verify | deploy |

### Files Affected
| File | Change |
|------|--------|
| `retirement_engine.py` | Pre-retirement growth; post-retirement anchor; grow stale pots to anchor |
| `config_default.json` | Add `values_as_of` to each DC pot and ISA entry |
| `templates/settings.html` | Label changes, helper text, `values_as_of` input, projected value display |
| `templates/dashboard.html` | Phase indicator banner, staleness warnings |
| `app.py` | Pass phase context to templates; handle `values_as_of` in form processing |

### What Does NOT Change
- Guaranteed income `values_as_of` — already working correctly, untouched.
- Post-retirement projection logic — unchanged once anchor point is established.
- Optimiser — no changes (calls the engine, which handles everything upstream).
- Backward compatibility — configs without `values_as_of` on pots work exactly as today.

---

## 🆕 V1.1 Feature: Projection History & "Show Full Timeline"

### Overview
Allow users to see their full retirement timeline including past projection snapshots,
with honest step discontinuities where actual values diverged from projections.

### 1. Snapshot Storage
- Auto-save a timestamped snapshot each time the user updates `values_as_of` on any
  pot or account. Store as JSON in a `snapshots/` directory.
- Each snapshot contains: config at that point, projection result, and timestamp.

### 2. Chart: "Show Full Timeline" Toggle
- Default view (toggle OFF): current forward projection only (V1 behaviour).
- Toggle ON: stitches together stored snapshots from retirement age to current anchor,
  followed by the current forward projection.
- Visual treatment:
  - **Solid line segments** for past projection periods (from each snapshot).
  - **Step markers** annotated with update details, e.g. *"Updated Mar 2033: actual balance £140k"*.
  - **Dashed line** for the current forward projection.
- Steps between segments are shown honestly — no smoothing. The discontinuity is
  meaningful information (reality diverged from the projection).

### 3. Design Principles
- Steps are truthful and valuable — they show where assumptions differed from reality.
- Smoothing would create fictional data and undermine credibility for professional users.
- The primary view (toggle OFF) always remains clean and forward-looking.
- History is opt-in, not forced on the user.

---

## Deferred to V1.2+
- Bitcoin / freedom reserve
- UK property module (keep/rent/sell)
- UK tax comparison engine
- Monte Carlo / stochastic returns
- Monthly granularity
- Spending bands (base/comfort/freedom)
- Scenario comparison automation
- PDF/HTML report export
- Real vs nominal toggle
- One-off expenses schedule
- Advisor view
- Pre-retirement contributions modelling
