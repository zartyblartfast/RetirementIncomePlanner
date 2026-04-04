# Engine Robustness Plan

## Problem Statement

The retirement projection engine has experienced recurring bugs where:
1. **Derived state goes stale** — `target_end_age` (ARVA) and `target_income.net_annual` (Fixed Target, Vanguard, GK) are stored in multiple places. When one copy updates but another doesn't, the engine produces wrong results.
2. **Extended projections silently corrupt config** — Setting `personal.end_age = 120` for chart display causes ARVA to plan depletion by age 120 instead of the user's plan end age. Ad-hoc patches at 4+ sites are fragile.
3. **UI strategy switching sends stale defaults** — Hidden params like `target_end_age` default to 90 (strategy definition) instead of the user's `end_age`. Patched for ARVA only.
4. **No structural validation** — Incorrect config reaches the engine undetected. Wrong results are only caught by visual inspection.

These bugs directly affect financial planning outcomes. Incorrect projections can lead to under- or over-spending in retirement, with real consequences for people's lives.

---

## Strategy Audit

### All Drawdown Strategies and Known Vulnerabilities

| Strategy | Params | Derived State Risk | Extended Projection Risk | Stateful Risk |
|---|---|---|---|---|
| Fixed Target | `net_annual` | `net_annual` synced to `target_income.net_annual` | Low (absolute target) | None |
| Fixed Percentage | `withdrawal_pct` | None | Low (% of portfolio) | None |
| Vanguard Dynamic | `initial_target`, `ceiling_pct`, `floor_pct` | `initial_target` synced to `target_income.net_annual` | Medium (stateful past plan end) | Previous year income |
| Guyton-Klinger | `initial_target`, `ceiling_pct`, `floor_pct`, `capital_preservation_rule` | `initial_target` synced to `target_income.net_annual` | Medium (stateful past plan end) | Previous year income |
| ARVA | `assumed_real_return_pct`, `target_end_age` | `target_end_age` derived from `end_age` | **High** (PMT uses remaining years) | None |
| ARVA + Guardrails | ARVA params + `max_annual_increase_pct`, `max_annual_decrease_pct` | `target_end_age` derived from `end_age` | **High** (PMT uses remaining years) | Previous year withdrawal |

### Bug Classes

1. **Derived state stored as params** — affects Fixed Target, Vanguard, GK (`net_annual` sync), ARVA (`target_end_age`)
2. **Extended projection mutating `personal.end_age`** — affects ALL strategies, critical for ARVA
3. **UI strategy switch sending stale defaults** — affects ALL strategies
4. **Stateful strategy continuity after config change** — affects Vanguard, GK, ARVA+Guardrails
5. **Mode mismatch (`net` vs `pot_net`)** — implicit, no validation; ARVA returns `pot_net`, others return `net`

---

## Implementation Steps

### Step 1: Engine Contract — Separate Plan Horizon from Simulation Horizon

**Goal**: Ensure `personal.end_age` (the user's plan end) is NEVER mutated. Introduce `projection_end_age` as a separate field for extended projections.

**Changes**:

#### V1 (`retirement_engine.py`)
- At the start of `run_projection()`, snapshot:
  ```python
  plan_end_age = cfg["personal"]["end_age"]
  projection_end_age = cfg.get("projection_end_age", plan_end_age)
  ```
- Main simulation loop runs to `projection_end_age`
- All strategy compute calls receive `plan_end_age` (not `projection_end_age`)
- Standardize compute function signature:
  ```python
  def compute(params, state, portfolio_value, cpi_rate, current_age, plan_end_age):
      return ({"mode": str, "annual_amount": float}, new_state)
  ```
- Update `compute_annual_target()` dispatcher to pass `plan_end_age`

#### V2 (`projection.ts`, `strategies.ts`)
- Same separation at the start of `runProjection()`
- Same standardized `ComputeFn` signature with `planEndAge` parameter

**Test**: Existing 139 tests must still pass. No numerical changes expected — this step only changes how values flow, not what they are.

---

### Step 2: `make_extended_config` Helper

**Goal**: Replace all ad-hoc extended projection config creation with a single, tested function.

**Changes**:

#### V1 (`retirement_engine.py` or new `config_helpers.py`)
```python
def make_extended_config(cfg, horizon=120):
    """Create config for extended projection. 
    
    Only sets projection_end_age. NEVER modifies personal.end_age
    or strategy params.
    """
    import copy
    ext = copy.deepcopy(cfg)
    ext["projection_end_age"] = horizon
    return ext
```

#### V1 (`app.py`)
- Replace all 4 sites that do:
  ```python
  ext_cfg = _copy.deepcopy(cfg)
  ext_cfg["personal"]["end_age"] = 120
  # Preserve ARVA target_end_age...
  ```
  With:
  ```python
  ext_cfg = make_extended_config(cfg, horizon=120)
  ```

#### V2
- Equivalent TypeScript helper, used wherever extended projections are created

**Test**: Extended projection output must be identical to current (after Step 1). Add specific test: `extended_projection_preserves_plan_end_age`.

---

### Step 3: Remove Derived State

**Goal**: Each piece of data has exactly ONE source of truth.

#### 3a: Remove `target_end_age` from ARVA params

- Remove `target_end_age` from ARVA and ARVA+Guardrails strategy definitions (param list)
- ARVA compute functions receive `plan_end_age` from engine (added in Step 1)
- Remove all `target_end_age` syncing code:
  - V1: `normalize_config()`, `save_strategy` handler, 4 extended projection sites (already replaced in Step 2)
  - V2: `normalizeConfig()`, `ConfigPanel` onChange handler

#### 3b: Remove `target_income.net_annual` dual sync

- `target_income.net_annual` becomes **read-only for display** — derived from `drawdown_strategy_params` at render time
- Remove sync code from `normalize_config()` (V1) and `normalizeConfig()` (V2)
- Add a pure function:
  ```python
  def get_display_target(cfg) -> float:
      """Return the target income for display purposes."""
      sid = cfg["drawdown_strategy"]
      params = cfg["drawdown_strategy_params"]
      if sid == "fixed_target":
          return params.get("net_annual", 30000)
      elif sid in ("vanguard_dynamic", "guyton_klinger"):
          return params.get("initial_target", 30000)
      else:
          return cfg["target_income"]["net_annual"]  # ARVA: user's stated target
  ```

**Test**: All 139 existing tests pass. Add test that configs with missing `target_income.net_annual` still produce correct projections.

---

### Step 4: Validation Layer

**Goal**: Catch invalid config and invalid strategy output before they produce wrong numbers.

#### 4a: Config Validation (engine entry)

```python
def validate_config(cfg) -> list[str]:
    """Return list of errors. Empty = valid."""
    errors = []
    sid = cfg.get("drawdown_strategy")
    
    # Strategy must be known
    if sid not in KNOWN_STRATEGIES:
        errors.append(f"Unknown strategy: {sid}")
    
    # Params must exist
    if not cfg.get("drawdown_strategy_params"):
        errors.append("Missing drawdown_strategy_params")
    
    # Plan end must be > retirement age
    end_age = cfg.get("personal", {}).get("end_age")
    ret_age = cfg.get("personal", {}).get("retirement_age")
    if end_age and ret_age and end_age <= ret_age:
        errors.append(f"end_age ({end_age}) must be > retirement_age ({ret_age})")
    
    # Projection must cover plan
    proj_end = cfg.get("projection_end_age", end_age)
    if proj_end and end_age and proj_end < end_age:
        errors.append(f"projection_end_age ({proj_end}) < end_age ({end_age})")
    
    # DC pots and TF accounts must have non-negative balances
    for pot in cfg.get("dc_pots", []):
        if pot.get("starting_balance", 0) < 0:
            errors.append(f"Negative balance: {pot['name']}")
    for acc in cfg.get("tax_free_accounts", []):
        if acc.get("starting_balance", 0) < 0:
            errors.append(f"Negative balance: {acc['name']}")
    
    return errors
```

Called at the start of `run_projection()` / `runProjection()`. In tests: raise on errors. In production: log warnings.

#### 4b: Strategy Output Validation (per-year)

After each strategy compute call:
```python
assert result["mode"] in ("net", "pot_net", "gross"), f"Invalid mode: {result['mode']}"
assert result["annual_amount"] >= 0, f"Negative withdrawal: {result['annual_amount']}"
```

#### 4c: Summary Consistency Assertion

After building the projection summary:
```python
assert summary["sustainable"] == (summary["first_shortfall_age"] is None), \
    f"sustainable={summary['sustainable']} but first_shortfall_age={summary['first_shortfall_age']}"
```

**Test**: Add tests with intentionally invalid configs to verify validation catches them.

---

### Step 5: Golden Snapshot Tests

**Goal**: Pin the exact numerical output of every strategy so that any future code change that shifts a number triggers a visible test failure.

#### Test Matrix (minimum 24 tests)

For each of the 6 strategies:
1. **Normal projection** — pins year-by-year: age, target_net, net_income_achieved, total_capital, shortfall flag
2. **Extended projection parity** — asserts years within plan end are identical between normal and extended
3. **Strategy switch** — switches from another strategy, asserts params are clean and output is correct
4. **Edge case** — pot depletion mid-year, zero growth, single pot, delayed guaranteed income

#### Fixture configs

- `GOLDEN_FIXED_TARGET` — sustainable, 2 DC pots + ISA, target £36k
- `GOLDEN_FIXED_PCT` — sustainable, single DC pot
- `GOLDEN_VANGUARD` — sustainable, with ceiling/floor binding
- `GOLDEN_GK` — sustainable, with capital preservation rule triggering
- `GOLDEN_ARVA` — sustainable, plans to deplete by end_age
- `GOLDEN_ARVA_GUARDRAILS` — sustainable, guardrails binding in some years
- `GOLDEN_ARVA_SHORTFALL` — shortfall scenario (low balance, high target)

Each fixture stores the full config AND the expected output (year-by-year arrays). Tests compare engine output to stored expectations with zero tolerance on integers, ±0.01 on decimals.

**Test storage**: `tests/golden/` directory with JSON fixtures.

---

### Step 6: Apply to V2

Repeat Steps 1–5 for the V2 TypeScript codebase:
- `projection.ts`: plan_end_age vs projection_end_age separation
- `strategies.ts`: standardized ComputeFn signature, remove target_end_age, remove always-sync
- `ConfigPanel.tsx`: remove target_end_age seeding (no longer needed)
- New `validateConfig.ts` utility
- New `__tests__/golden/` directory with TypeScript snapshot tests

#### V1 ↔ V2 Cross-Parity Test

Create a test harness (can be in either language) that:
1. Reads each golden fixture config
2. Runs it through V1 (Python) and V2 (TypeScript) engines
3. Compares year-by-year output within ±£1 tolerance
4. Fails if any strategy produces different results between versions

---

## Success Criteria

After all 6 steps:
- [ ] `personal.end_age` is NEVER mutated anywhere in the codebase
- [ ] `target_end_age` does not exist as a stored param
- [ ] `target_income.net_annual` is not synced — derived at display time
- [ ] All extended projections use `make_extended_config()`
- [ ] `validate_config()` runs at every engine entry point
- [ ] Strategy output is validated after every compute call
- [ ] Summary consistency is asserted
- [ ] 24+ golden snapshot tests cover all 6 strategies
- [ ] V1 and V2 produce identical output for all golden configs
- [ ] 139+ existing V1 tests pass
- [ ] V2 test suite passes

---

## Risk Mitigation

- **Each step is independently deployable** — no step requires all others
- **Existing tests must pass after each step** — no "we'll fix tests later"
- **Golden snapshots are committed** — any future change that shifts numbers is immediately visible
- **V1 ↔ V2 parity is enforced** — divergence is caught automatically

---

## Estimated Scope

| Step | V1 Files Changed | V2 Files Changed | New Tests |
|---|---|---|---|
| 1. Engine contract | `retirement_engine.py`, `drawdown_strategies.py` | `projection.ts`, `strategies.ts` | 0 (existing pass) |
| 2. Extended config helper | `app.py`, new `config_helpers.py` | new `configHelpers.ts` | 1 |
| 3. Remove derived state | `drawdown_strategies.py`, `app.py` | `strategies.ts`, `ConfigPanel.tsx` | 2 |
| 4. Validation layer | `retirement_engine.py` | `projection.ts` | 4 |
| 5. Golden snapshots | new `tests/golden/` | new `__tests__/golden/` | 24+ |
| 6. V1↔V2 parity | — | — | 6+ |
