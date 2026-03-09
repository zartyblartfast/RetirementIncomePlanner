# Flask/Python → Client-Side JavaScript Conversion Plan
**Last updated:** 6 March 2026

## Purpose

Convert the Retirement Income Planner from a Flask/Python server-side application to a
fully client-side JavaScript application. This eliminates server hosting costs, removes
all data privacy/GDPR concerns (no user data leaves the browser), and enables free
static hosting (Netlify, GitHub Pages, Vercel).

---

## Current Architecture (Flask/Python)

```
Browser  ──POST form──▶  Flask (app.py)  ──▶  retirement_engine.py
                                          ──▶  optimiser.py
         ◀──HTML page──  Jinja2 templates ◀──  JSON results
                          
Data: config_active.json, scenarios/ (server filesystem)
```

## Target Architecture (Client-Side JS)

```
Browser  ──all local──▶  retirement_engine.js
                     ──▶  optimiser.js
                     ──▶  DOM rendering (vanilla JS)
                          
Data: localStorage (browser) + JSON export/import
```

---

## Codebase Inventory

| File | Lines | Role | Conversion |
|------|-------|------|------------|
| `retirement_engine.py` | 524 | Core projection engine | Rewrite as `retirement_engine.js` |
| `optimiser.py` | 662 | 4 optimisation algorithms | Rewrite as `optimiser.js` |
| `app.py` | 380 | Flask routes, form handling | Replace with JS event handlers |
| `retirement_planner.py` | 162 | CLI interface | **Drop** — not needed for web app |
| `config_default.json` | 97 | Default config | Keep as-is — JSON is native to JS |
| `asset_model.json` | 371 | Asset class reference data | Keep as-is |
| `dashboard.html` | 617 | Dashboard + Chart.js charts | Convert Jinja2 to JS rendering |
| `settings.html` | 739 | Settings form | Convert Jinja2 to JS rendering |
| `compare.html` | 153 | Scenario comparison | Convert Jinja2 to JS rendering |
| `optimise.html` | 197 | Optimisation results | Convert Jinja2 to JS rendering |
| `base.html` | 73 | Base template (nav, layout) | Convert to shared JS layout |
| `login.html` | 34 | Login page | **Replace** with license key entry |

**Total Python to convert:** ~1,566 lines (engine + optimiser + app routes)
**Total HTML to adapt:** ~1,779 lines (templates)

---

## Conversion Details

### 1. Engine (`retirement_engine.py` → `retirement_engine.js`)

**Effort: 2–3 days**

The engine is pure arithmetic — no Python-specific libraries, no file I/O during
computation. Every construct has a direct JavaScript equivalent.

| Python | JavaScript |
|--------|-----------|
| `class RetirementEngine:` | `class RetirementEngine {` |
| `def __init__(self, cfg):` | `constructor(cfg) {` |
| `max(0, x)` | `Math.max(0, x)` |
| `round(x, 2)` | `Math.round(x * 100) / 100` or use a `round2` helper |
| `for band in bands:` | `for (const band of bands) {` |
| `dict` / `list` | `object` / `array` (identical JSON structure) |
| `x ** y` | `x ** y` or `Math.pow(x, y)` |
| `f"string {var}"` | `` `string ${var}` `` |

Key functions to convert:
- `calculate_tax()` — ~60 lines, pure band arithmetic
- `calculate_uk_tax()` — ~55 lines, same pattern
- `gross_up()` — ~25 lines, binary search
- `run_projection()` — ~250 lines, main loop with growth/withdrawal/tax
- `load_config()` — trivial in JS (`JSON.parse`)
- `resolve_growth_rate()` / `resolve_growth_provenance()` — ~40 lines, JSON lookup

**Example — tax calculation (nearly line-for-line):**

```python
# Python
def calculate_tax(self, taxable_income):
    pa = self.cfg["tax"]["personal_allowance"]
    income_after_pa = max(0, taxable_income - pa)
    tax = 0.0
    remaining = income_after_pa
    for band in self.cfg["tax"]["bands"]:
        width = band["width"]
        rate = band["rate"]
        if width is None:
            taxable_in_band = remaining
        else:
            taxable_in_band = min(remaining, width)
        tax += taxable_in_band * rate
        remaining -= taxable_in_band
        if remaining <= 0:
            break
    return round(tax, 2)
```

```javascript
// JavaScript
calculateTax(taxableIncome) {
    const pa = this.cfg.tax.personal_allowance;
    const incomeAfterPa = Math.max(0, taxableIncome - pa);
    let tax = 0;
    let remaining = incomeAfterPa;
    for (const band of this.cfg.tax.bands) {
        const taxableInBand = band.width === null
            ? remaining
            : Math.min(remaining, band.width);
        tax += taxableInBand * band.rate;
        remaining -= taxableInBand;
        if (remaining <= 0) break;
    }
    return Math.round(tax * 100) / 100;
}
```

### 2. Optimiser (`optimiser.py` → `optimiser.js`)

**Effort: 2–3 days**

Same situation — pure iteration and binary search calling the engine. No Python-specific
features. The four algorithms convert directly:

- `find_best_drawdown_order()` — permutation testing
- `find_max_sustainable_income()` — binary search
- `find_longevity_headroom()` — binary search
- `find_tax_efficient_drawdown()` — iterative allocation testing

**Note:** `itertools.permutations` (used for drawdown order) needs a small JS helper
function (~10 lines) or use a lightweight library.

### 3. UI / Templates → Vanilla JS

**Effort: 5–8 days total**

**Framework choice: Vanilla JS + Bootstrap 5 (no React/Vue needed)**

The current templates are already Bootstrap HTML. The conversion involves:
- Removing Jinja2 syntax (`{% for %}`, `{% if %}`, `{{ var }}`)
- Replacing with JavaScript DOM manipulation or template literals
- Chart.js code is **already JavaScript** — stays as-is with minor restructuring

| Template | Jinja2 complexity | Conversion notes |
|----------|------------------|-----------------|
| `dashboard.html` | Medium — loops over years, conditionals for warnings | Chart.js code unchanged. Year table rendered by JS. |
| `settings.html` | High — dynamic form sections for pots, allocation UI | Most complex. Reuse existing JS already in the template. |
| `compare.html` | Low — table of scenario results | Straightforward |
| `optimise.html` | Low — display optimiser results | Straightforward |
| `base.html` | Minimal — nav bar, layout | Shared HTML shell |
| `login.html` | Minimal | Replace with license key entry |

**Approach:**
```
index.html          — single-page app shell with nav
js/
  engine.js         — RetirementEngine class
  optimiser.js      — Optimiser class
  app.js            — page routing, event handlers, DOM rendering
  storage.js        — localStorage read/write, export/import
  license.js        — license key validation
data/
  config_default.json
  asset_model.json
css/
  (Bootstrap CDN + any custom styles)
```

### 4. Data Storage (`config_active.json` → `localStorage`)

**Effort: 1 day**

| Operation | Flask version | JS version |
|-----------|--------------|------------|
| Load config | `open("config_active.json")` | `JSON.parse(localStorage.getItem("config"))` |
| Save config | `json.dump(cfg, file)` | `localStorage.setItem("config", JSON.stringify(cfg))` |
| Load default | `open("config_default.json")` | `fetch("data/config_default.json")` |
| Save scenario | Write to `scenarios/` dir | `localStorage.setItem("scenario_" + name, ...)` |
| Export | N/A (not implemented) | `Blob` + download link |
| Import | N/A (not implemented) | File input + `FileReader` |

**localStorage limits:** ~5–10 MB depending on browser. A single config is ~2 KB,
a scenario with full projection result is ~20 KB. This supports hundreds of saved
scenarios with no concern.

### 5. License Key Validation

**Effort: 1 day**

```javascript
// Pseudocode — actual implementation depends on payment provider
async function validateLicense(key) {
    const resp = await fetch("https://api.lemonsqueezy.com/v1/licenses/validate", {
        method: "POST",
        body: JSON.stringify({ license_key: key }),
    });
    const data = await resp.json();
    if (data.valid) {
        localStorage.setItem("license_key", key);
        localStorage.setItem("license_valid", "true");
        return true;
    }
    return false;
}
```

- Validated once on first use, stored in `localStorage`
- No ongoing phone-home — honor system after validation
- If `localStorage` is cleared, user re-enters the key (they received it by email)

### 6. Testing & Verification

**Effort: 3–5 days**

Critical step — financial calculations must match the Python version exactly.

**Approach:**
1. Create a test harness that runs both engines on the same config
2. Compare every output field year-by-year
3. Acceptable tolerance: ≤ £0.01 per field (sub-penny rounding differences)
4. Test all four optimiser algorithms
5. Test edge cases: zero balances, single pot, no guaranteed income, etc.

```javascript
// test_parity.js — run in Node.js
const pythonResult = require("./test_data/python_output.json");
const engine = new RetirementEngine(config);
const jsResult = engine.runProjection();

for (let i = 0; i < pythonResult.years.length; i++) {
    const py = pythonResult.years[i];
    const js = jsResult.years[i];
    assert(Math.abs(py.net_income - js.net_income) < 0.01,
        `Year ${i}: net_income mismatch`);
    // ... repeat for all fields
}
```

---

## Features: Full Parity

| Feature | Status after conversion |
|---------|----------------------|
| Year-by-year projection | ✅ Identical logic |
| IoM tax calculation | ✅ Identical logic |
| UK tax comparison | ✅ Identical logic |
| Gross-up solver | ✅ Identical logic |
| DC pot growth & drawdown | ✅ Identical logic |
| ISA growth & withdrawal | ✅ Identical logic |
| Withdrawal priority ordering | ✅ Identical logic |
| 4 optimisation algorithms | ✅ Identical logic |
| Capital trajectory chart | ✅ Already Chart.js — no change |
| Income breakdown chart | ✅ Already Chart.js — no change |
| Scenario save/load/compare | ✅ localStorage replaces file system |
| CSV export | ✅ Browser Blob download |
| Config export/import (JSON) | ✅ **New** — better than current |
| Offline capability | ✅ **New** — works without internet after first load |
| Multi-user (same device) | ✅ **New** — separate browser profiles |

**Features dropped:**
- CLI interface (`retirement_planner.py`) — not needed for web app
- Server-side login — replaced by license key

**Features gained:**
- JSON config export/import (backup/restore)
- Full offline capability
- Zero server dependency
- True data privacy (nothing leaves the browser)

---

## Floating-Point Parity Note

Both Python and JavaScript use IEEE 754 64-bit doubles. Results will match in the vast
majority of cases. Potential sub-penny differences can arise from:
- Operation ordering (associativity of addition)
- `round()` behaviour at exact 0.5 boundaries (Python uses banker's rounding;
  JS `Math.round` always rounds 0.5 up)

**Mitigation:** Use a consistent `round2(x)` helper in JS:
```javascript
function round2(x) {
    return Math.round((x + Number.EPSILON) * 100) / 100;
}
```

This is sufficient for financial planning where sub-penny accuracy is not required.

---

## Effort Summary

| Task | Days |
|------|------|
| Engine conversion + unit tests | 2–3 |
| Optimiser conversion + unit tests | 2–3 |
| UI conversion (all pages) | 5–8 |
| localStorage + export/import | 1 |
| License key validation | 1 |
| Cross-engine parity testing | 3–5 |
| **Total** | **~17–24 working days** |

---

## Recommended Sequence

1. **Complete V1 features in Python/Flask first** — phase awareness, UI improvements,
   and any remaining QA fixes. Don't disrupt current progress.
2. **Convert engine + optimiser to JS** — write parity tests comparing Python vs JS
   output for the same config inputs. This is the highest-risk step.
3. **Build static HTML + JS UI** — reuse current Bootstrap HTML structure, replace
   Jinja2 with JS rendering. Charts stay as-is.
4. **Add localStorage + export/import** — replace server file I/O.
5. **Add license key validation** — integrate with payment provider.
6. **Deploy to free static host** — Netlify or GitHub Pages. Zero ongoing cost.
7. **Retire Flask app** — keep Python version as reference/test oracle.

---

## Hosting After Conversion

| Host | Cost | Notes |
|------|------|-------|
| **Netlify** (free tier) | £0/mo | 100 GB bandwidth/mo, custom domain, HTTPS |
| **GitHub Pages** | £0/mo | Unlimited bandwidth, custom domain, HTTPS |
| **Vercel** (free tier) | £0/mo | 100 GB bandwidth/mo, custom domain, HTTPS |

At any reasonable user volume, hosting is permanently free. The only cost is the
domain name (~£10/year).
