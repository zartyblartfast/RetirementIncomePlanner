# Retirement Income Planner — To-Do / Open Items
**Last updated:** 2 March 2026

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

## Deferred to V1.1+
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
- Flask web UI front-end
- Advisor view
