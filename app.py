"""Retirement Income Planner — Flask Web Application (Dynamic Streams)"""
import os
import json
import copy
import hashlib
import functools
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify)
from retirement_engine import RetirementEngine, load_config, load_asset_model, resolve_growth_rate, resolve_growth_provenance
from market_data import fetch_market_data, get_all_pot_intelligence
from optimiser import Optimiser
from version import get_version_info
from validation_runner import run_all_scenarios, ALL_SCENARIOS

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "pension-planner-secret-key-2025")

# ------------------------------------------------------------------ #
#  Version info — available in all templates as {{ version_info }}
# ------------------------------------------------------------------ #
@app.context_processor
def inject_version():
    return {"version_info": get_version_info()}

# ------------------------------------------------------------------ #
#  Asset Model (read-only reference data)
# ------------------------------------------------------------------ #
ASSET_MODEL = load_asset_model()

# ------------------------------------------------------------------ #
#  Auth
# ------------------------------------------------------------------ #
USERNAME = os.environ.get("APP_USERNAME", "PensionPlanner")
SALT = os.environ.get("APP_SALT", "iom_pension_2025")
_password = os.environ.get("APP_PASSWORD", "planner123!")
PASSWORD_HASH = hashlib.sha256(f"{_password}{SALT}".encode()).hexdigest()
del _password  # Don't keep plaintext in memory

def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        pw_hash = hashlib.sha256(f"{password}{SALT}".encode()).hexdigest()
        if username.lower() == USERNAME.lower() and pw_hash == PASSWORD_HASH:
            session["logged_in"] = True
            session.permanent = True
            return redirect(url_for("dashboard"))
        flash("Invalid credentials. Please try again.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ------------------------------------------------------------------ #
#  Config helpers
# ------------------------------------------------------------------ #
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config_default.json")
ACTIVE_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config_active.json")
SCENARIO_DIR = os.path.join(os.path.dirname(__file__), "scenarios")
os.makedirs(SCENARIO_DIR, exist_ok=True)

def get_config():
    """Return active config from disk, falling back to default."""
    if os.path.exists(ACTIVE_CONFIG_PATH):
        cfg = load_config(ACTIVE_CONFIG_PATH)
    else:
        cfg = load_config(CONFIG_PATH)
    return cfg

def save_session_config(cfg):
    """Persist config to disk so all pages see the same data."""
    import json as _json
    with open(ACTIVE_CONFIG_PATH, "w") as _f:
        _json.dump(cfg, _f, indent=2, default=str)
    session.modified = True

def apply_form_to_config(cfg, form):
    """Apply dashboard quick-edit form values to config."""
    try:
        cfg["target_income"]["net_annual"] = float(form.get("target_income", 30000))
        cfg["target_income"]["cpi_rate"] = float(form.get("cpi_rate", 0.03))
        cfg["personal"]["end_age"] = int(form.get("end_age", 90))
        cfg["tax"]["tax_cap_enabled"] = form.get("tax_cap_enabled") == "on"
        # Withdrawal priority from hidden field
        wp = form.get("withdrawal_priority", "")
        if wp:
            cfg["withdrawal_priority"] = [x.strip() for x in wp.split(",") if x.strip()]
    except (ValueError, KeyError):
        pass
    return cfg


def build_allocation_from_form(form, prefix):
    """Build allocation dict from form data.

    Args:
        form: Flask request.form
        prefix: 'dc' or 'tf' — used to find form field names

    Returns:
        tuple: (allocation_dict, resolved_growth_rate)
    """
    mode = form.get(f"{prefix}_alloc_mode", "manual")

    allocation = {
        "mode": mode,
        "template_id": "",
        "custom_weights": {},
        "manual_override": False,
    }

    if mode == "template":
        allocation["template_id"] = form.get(f"{prefix}_template_id", "")
    elif mode == "custom":
        weights = {}
        for ac in ASSET_MODEL["asset_classes"]:
            w = form.get(f"{prefix}_weight_{ac['id']}", "0")
            try:
                w_val = float(w) / 100.0  # form sends percentages, store as decimals
            except (ValueError, TypeError):
                w_val = 0.0
            if w_val > 0:
                weights[ac["id"]] = round(w_val, 6)
        allocation["custom_weights"] = weights
    elif mode == "manual":
        allocation["manual_override"] = True

    # Compute resolved growth rate
    dummy_pot = {"growth_rate": float(form.get(f"{prefix}_growth", 0.04)), "allocation": allocation}
    resolved = resolve_growth_rate(dummy_pot, ASSET_MODEL)

    return allocation, resolved


# ------------------------------------------------------------------ #
#  Dashboard

# ------------------------------------------------------------------ #
#  Phase detection & staleness warnings (C5)
# ------------------------------------------------------------------ #
def compute_phase_info(cfg):
    """Determine retirement phase and flag stale pot balances."""
    from datetime import date, datetime
    import math

    today = date.today()
    ret_str = cfg["personal"].get("retirement_date", "2027-04")
    try:
        ret_year, ret_month = int(ret_str[:4]), int(ret_str[5:7])
        retirement_date = date(ret_year, ret_month, 1)
    except (ValueError, IndexError):
        retirement_date = date(2027, 4, 1)

    # Phase detection
    if today.year == retirement_date.year and today.month == retirement_date.month:
        phase = "at_retirement"
        phase_label = "At Retirement"
        phase_icon = "🎉"  # party popper
        phase_class = "success"
        phase_msg = "This is your retirement month! Your plan is now live."
    elif today < retirement_date:
        phase = "pre_retirement"
        phase_label = "Pre-Retirement"
        phase_icon = "⏳"  # hourglass
        phase_class = "info"
        months_to_go = (retirement_date.year - today.year) * 12 + (retirement_date.month - today.month)
        years_to_go = months_to_go // 12
        rem_months = months_to_go % 12
        if years_to_go > 0 and rem_months > 0:
            countdown = f"{years_to_go} year{'s' if years_to_go != 1 else ''} and {rem_months} month{'s' if rem_months != 1 else ''}"
        elif years_to_go > 0:
            countdown = f"{years_to_go} year{'s' if years_to_go != 1 else ''}"
        else:
            countdown = f"{rem_months} month{'s' if rem_months != 1 else ''}"
        phase_msg = f"You are in the accumulation phase. Retirement begins in {countdown} ({ret_str})."
    else:
        phase = "post_retirement"
        phase_label = "Post-Retirement"
        phase_icon = "🏖️"  # beach
        phase_class = "secondary"
        months_since = (today.year - retirement_date.year) * 12 + (today.month - retirement_date.month)
        years_since = months_since // 12
        phase_msg = f"You have been retired for {years_since} year{'s' if years_since != 1 else ''}."

    # Staleness detection (flag pots with values_as_of > 6 months old)
    STALE_THRESHOLD_MONTHS = 6
    stale_items = []
    for pot in cfg.get("dc_pots", []):
        vao = pot.get("values_as_of", "")
        if vao:
            try:
                vao_y, vao_m = int(vao[:4]), int(vao[5:7])
                vao_date = date(vao_y, vao_m, 1)
                months_old = (today.year - vao_date.year) * 12 + (today.month - vao_date.month)
                if months_old > STALE_THRESHOLD_MONTHS:
                    stale_items.append({"name": pot["name"], "type": "DC Pot", "as_of": vao, "months_old": months_old})
            except (ValueError, IndexError):
                pass
    for acc in cfg.get("tax_free_accounts", []):
        vao = acc.get("values_as_of", "")
        if vao:
            try:
                vao_y, vao_m = int(vao[:4]), int(vao[5:7])
                vao_date = date(vao_y, vao_m, 1)
                months_old = (today.year - vao_date.year) * 12 + (today.month - vao_date.month)
                if months_old > STALE_THRESHOLD_MONTHS:
                    stale_items.append({"name": acc["name"], "type": "Tax-Free Account", "as_of": vao, "months_old": months_old})
            except (ValueError, IndexError):
                pass

    return {
        "phase": phase,
        "phase_label": phase_label,
        "phase_icon": phase_icon,
        "phase_class": phase_class,
        "phase_msg": phase_msg,
        "stale_items": stale_items,
        "has_stale": len(stale_items) > 0,
    }


# ------------------------------------------------------------------ #
@app.route("/", methods=["GET", "POST"])
@login_required
def dashboard():
    cfg = get_config()
    if request.method == "POST":
        cfg = apply_form_to_config(cfg, request.form)
        save_session_config(cfg)

    engine = RetirementEngine(cfg)
    result = engine.run_projection()

    # Extended projection to age 105 for capital trajectory chart
    import copy as _copy
    ext_cfg = _copy.deepcopy(cfg)
    ext_cfg["personal"]["end_age"] = 120
    ext_engine = RetirementEngine(ext_cfg)
    ext_result = ext_engine.run_projection()
    plan_end_age = cfg["personal"]["end_age"]
    # Find depletion age: first year where TOTAL capital is effectively zero.
    # This drives the "Capital Depleted" chart marker.
    # Note: depletion_events in the engine track individual pot exhaustion,
    # which is different — do NOT use them for the total-capital marker.
    # The engine uses last-residual-drawdown logic to sweep near-empty pots,
    # so total_capital should reach zero cleanly without a long tail.
    DEPLETION_EPSILON = 1.0
    depletion_age = None
    for yr in ext_result["years"]:
        if yr["total_capital"] <= DEPLETION_EPSILON:
            depletion_age = yr["age"]
            break
    # Trim extended years: always show depletion visually if it occurs
    if depletion_age:
        chart_end = max(plan_end_age + 5, depletion_age + 2)
    else:
        chart_end = plan_end_age + 5
    depletion_beyond_chart = False
    ext_years_trimmed = [y for y in ext_result["years"] if y["age"] <= chart_end]


    phase_info = compute_phase_info(cfg)

    # H3: Fetch live market data and compute per-pot intelligence
    market_raw = fetch_market_data()
    market_intel = get_all_pot_intelligence(cfg, market_raw) if market_raw else None

    return render_template("dashboard.html", config=cfg, result=result,
                           ext_years=ext_years_trimmed,
                           plan_end_age=plan_end_age,
                           depletion_age=depletion_age,
                           depletion_beyond_chart=depletion_beyond_chart,
                           phase_info=phase_info,
                           market_intel=market_intel,)

# ------------------------------------------------------------------ #
#  Settings — dynamic income stream management
# ------------------------------------------------------------------ #
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    cfg = get_config()
    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "save_personal":
            cfg["personal"]["date_of_birth"] = request.form.get("date_of_birth", cfg["personal"]["date_of_birth"])
            cfg["personal"]["retirement_date"] = request.form.get("retirement_date", cfg["personal"]["retirement_date"])
            try:
                cfg["personal"]["retirement_age"] = int(request.form.get("retirement_age", 68))
                cfg["personal"]["end_age"] = int(request.form.get("end_age", 90))
            except ValueError:
                pass
            flash("Personal details updated.", "success")

        elif action == "save_target":
            try:
                cfg["target_income"]["net_annual"] = float(request.form.get("net_annual", 30000))
                cfg["target_income"]["cpi_rate"] = float(request.form.get("cpi_rate", 0.03))
            except ValueError:
                pass
            flash("Target income updated.", "success")

        elif action == "save_tax":
            cfg["tax"]["regime"] = request.form.get("regime", "Isle of Man")
            try:
                cfg["tax"]["personal_allowance"] = float(request.form.get("personal_allowance", 14500))
            except ValueError:
                pass
            cfg["tax"]["tax_cap_enabled"] = request.form.get("tax_cap_enabled") == "on"
            flash("Tax settings updated.", "success")

        elif action == "add_guaranteed":
            new_stream = {
                "name": request.form.get("g_name", "New Pension"),
                "gross_annual": float(request.form.get("g_gross_annual", 0)),
                "indexation_rate": float(request.form.get("g_indexation_rate", 0)),
                "start_age": int(request.form.get("g_start_age", 68)),
                "end_age": None,
                "taxable": request.form.get("g_taxable") == "on",
                "values_as_of": request.form.get("g_values_as_of", "").strip() or None,
            }
            end_age_str = request.form.get("g_end_age", "").strip()
            if end_age_str:
                new_stream["end_age"] = int(end_age_str)
            cfg["guaranteed_income"].append(new_stream)
            flash(f"Added guaranteed income: {new_stream['name']}", "success")

        elif action == "delete_guaranteed":
            idx = int(request.form.get("index", -1))
            if 0 <= idx < len(cfg["guaranteed_income"]):
                removed = cfg["guaranteed_income"].pop(idx)
                flash(f"Removed: {removed['name']}", "warning")

        elif action == "save_guaranteed":
            idx = int(request.form.get("index", -1))
            if 0 <= idx < len(cfg["guaranteed_income"]):
                g = cfg["guaranteed_income"][idx]
                g["name"] = request.form.get("g_name", g["name"])
                g["gross_annual"] = float(request.form.get("g_gross_annual", g["gross_annual"]))
                g["indexation_rate"] = float(request.form.get("g_indexation_rate", g["indexation_rate"]))
                g["start_age"] = int(request.form.get("g_start_age", g["start_age"]))
                end_age_str = request.form.get("g_end_age", "").strip()
                g["end_age"] = int(end_age_str) if end_age_str else None
                g["taxable"] = request.form.get("g_taxable") == "on"
                g["values_as_of"] = request.form.get("g_values_as_of", "").strip() or None
                flash(f"Updated: {g['name']}", "success")

        elif action == "add_dc":
            alloc, resolved_rate = build_allocation_from_form(request.form, "dc")
            new_pot = {
                "name": request.form.get("dc_name", "New DC Pot"),
                "starting_balance": float(request.form.get("dc_balance", 0)),
                "values_as_of": request.form.get("dc_values_as_of", "").strip() or None,
                "growth_rate": resolved_rate,
                "annual_fees": float(request.form.get("dc_fees", 0.005)),
                "tax_free_portion": float(request.form.get("dc_tfp", 0.25)),
                "allocation": alloc,
            }
            cfg["dc_pots"].append(new_pot)
            if new_pot["name"] not in cfg["withdrawal_priority"]:
                cfg["withdrawal_priority"].append(new_pot["name"])
            flash(f"Added DC pot: {new_pot['name']}", "success")

        elif action == "delete_dc":
            idx = int(request.form.get("index", -1))
            if 0 <= idx < len(cfg["dc_pots"]):
                removed = cfg["dc_pots"].pop(idx)
                if removed["name"] in cfg["withdrawal_priority"]:
                    cfg["withdrawal_priority"].remove(removed["name"])
                flash(f"Removed: {removed['name']}", "warning")

        elif action == "save_dc":
            idx = int(request.form.get("index", -1))
            if 0 <= idx < len(cfg["dc_pots"]):
                old_name = cfg["dc_pots"][idx]["name"]
                p = cfg["dc_pots"][idx]
                p["name"] = request.form.get("dc_name", p["name"])
                p["starting_balance"] = float(request.form.get("dc_balance", p["starting_balance"]))
                p["values_as_of"] = request.form.get("dc_values_as_of", "").strip() or p.get("values_as_of")
                p["annual_fees"] = float(request.form.get("dc_fees", p["annual_fees"]))
                p["tax_free_portion"] = float(request.form.get("dc_tfp", p["tax_free_portion"]))

                # Handle allocation
                alloc, resolved_rate = build_allocation_from_form(request.form, "dc")
                p["allocation"] = alloc
                p["growth_rate"] = resolved_rate

                # Update withdrawal priority if name changed
                if old_name != p["name"] and old_name in cfg["withdrawal_priority"]:
                    idx_wp = cfg["withdrawal_priority"].index(old_name)
                    cfg["withdrawal_priority"][idx_wp] = p["name"]
                flash(f"Updated: {p['name']}", "success")

        elif action == "add_tf":
            alloc, resolved_rate = build_allocation_from_form(request.form, "tf")
            new_acc = {
                "name": request.form.get("tf_name", "New Account"),
                "starting_balance": float(request.form.get("tf_balance", 0)),
                "values_as_of": request.form.get("tf_values_as_of", "").strip() or None,
                "growth_rate": resolved_rate,
                "allocation": alloc,
            }
            cfg["tax_free_accounts"].append(new_acc)
            if new_acc["name"] not in cfg["withdrawal_priority"]:
                cfg["withdrawal_priority"].append(new_acc["name"])
            flash(f"Added tax-free account: {new_acc['name']}", "success")

        elif action == "delete_tf":
            idx = int(request.form.get("index", -1))
            if 0 <= idx < len(cfg["tax_free_accounts"]):
                removed = cfg["tax_free_accounts"].pop(idx)
                if removed["name"] in cfg["withdrawal_priority"]:
                    cfg["withdrawal_priority"].remove(removed["name"])
                flash(f"Removed: {removed['name']}", "warning")

        elif action == "save_tf":
            idx = int(request.form.get("index", -1))
            if 0 <= idx < len(cfg["tax_free_accounts"]):
                old_name = cfg["tax_free_accounts"][idx]["name"]
                a = cfg["tax_free_accounts"][idx]
                a["name"] = request.form.get("tf_name", a["name"])
                a["starting_balance"] = float(request.form.get("tf_balance", a["starting_balance"]))
                a["values_as_of"] = request.form.get("tf_values_as_of", "").strip() or a.get("values_as_of")

                # Handle allocation
                alloc, resolved_rate = build_allocation_from_form(request.form, "tf")
                a["allocation"] = alloc
                a["growth_rate"] = resolved_rate

                if old_name != a["name"] and old_name in cfg["withdrawal_priority"]:
                    idx_wp = cfg["withdrawal_priority"].index(old_name)
                    cfg["withdrawal_priority"][idx_wp] = a["name"]
                flash(f"Updated: {a['name']}", "success")

        elif action == "save_priority":
            wp = request.form.get("withdrawal_priority", "")
            if wp:
                cfg["withdrawal_priority"] = [x.strip() for x in wp.split(",") if x.strip()]
            flash("Withdrawal priority updated.", "success")

        elif action == "reset_defaults":
            cfg = load_config(CONFIG_PATH)
            if os.path.exists(ACTIVE_CONFIG_PATH):
                os.remove(ACTIVE_CONFIG_PATH)
            flash("Configuration reset to defaults.", "info")

        save_session_config(cfg)
        return redirect(url_for("settings"))

    # Compute growth rate provenance for each pot
    dc_provenance = []
    for pot in cfg.get("dc_pots", []):
        dc_provenance.append(resolve_growth_provenance(pot, ASSET_MODEL))
    tf_provenance = []
    for acc in cfg.get("tax_free_accounts", []):
        tf_provenance.append(resolve_growth_provenance(acc, ASSET_MODEL))

    phase_info = compute_phase_info(cfg)

    # C6: Compute projected retirement-date values for DC pots and ISAs
    dc_projected = []
    tf_projected = []
    if phase_info.get("phase") == "pre_retirement":
        from datetime import date
        ret_str = cfg["personal"].get("retirement_date", "2027-04")
        try:
            ret_y, ret_m = int(ret_str[:4]), int(ret_str[5:7])
        except (ValueError, IndexError):
            ret_y, ret_m = 2027, 4
        ret_months = ret_y * 12 + ret_m

        for pot in cfg.get("dc_pots", []):
            if pot.get("values_as_of"):
                try:
                    py, pm = int(pot["values_as_of"][:4]), int(pot["values_as_of"][5:7])
                    gap_months = ret_months - (py * 12 + pm)
                    if gap_months > 0:
                        gap_years = gap_months / 12.0
                        growth = resolve_growth_rate(pot, ASSET_MODEL)
                        fees = pot.get("annual_fees", 0.005)
                        net_growth = growth - fees
                        projected = pot["starting_balance"] * (1 + net_growth) ** gap_years
                        dc_projected.append(round(projected))
                    else:
                        dc_projected.append(None)
                except (ValueError, IndexError):
                    dc_projected.append(None)
            else:
                dc_projected.append(None)

        for acc in cfg.get("tax_free_accounts", []):
            if acc.get("values_as_of"):
                try:
                    ay, am = int(acc["values_as_of"][:4]), int(acc["values_as_of"][5:7])
                    gap_months = ret_months - (ay * 12 + am)
                    if gap_months > 0:
                        gap_years = gap_months / 12.0
                        growth = resolve_growth_rate(acc, ASSET_MODEL)
                        projected = acc["starting_balance"] * (1 + growth) ** gap_years
                        tf_projected.append(round(projected))
                    else:
                        tf_projected.append(None)
                except (ValueError, IndexError):
                    tf_projected.append(None)
            else:
                tf_projected.append(None)

    # H4: Fetch live market data for compact rate badges
    market_raw = fetch_market_data()
    market_intel = get_all_pot_intelligence(cfg, market_raw) if market_raw else None

    return render_template("settings.html", config=cfg, asset_model=ASSET_MODEL,
                           dc_provenance=dc_provenance, tf_provenance=tf_provenance,
                           phase_info=phase_info,
                           dc_projected=dc_projected, tf_projected=tf_projected,
                           market_intel=market_intel)

# ------------------------------------------------------------------ #
#  Scenarios
# ------------------------------------------------------------------ #
@app.route("/compare", methods=["GET", "POST"])
@login_required
def compare():
    if request.method == "POST":
        cfg = get_config()
        name = request.form.get("scenario_name", "Unnamed")
        # Run extended projection (up to 120) so the compare chart can
        # show capital trajectories beyond the plan end age.
        import copy as _copy
        ext_cfg = _copy.deepcopy(cfg)
        plan_end_age = cfg["personal"]["end_age"]
        ext_cfg["personal"]["end_age"] = min(120, max(plan_end_age, 120))
        engine = RetirementEngine(ext_cfg)
        ext_result = engine.run_projection()
        # Trim: find depletion, then cap at depletion+2 or plan_end+5, max 120
        DEPLETION_EPSILON = 1.0
        dep_age = None
        for yr in ext_result["years"]:
            if yr["total_capital"] <= DEPLETION_EPSILON:
                dep_age = yr["age"]
                break
        if dep_age:
            chart_end = min(120, max(plan_end_age, dep_age))
        else:
            chart_end = min(120, plan_end_age + 5)
        ext_result["years"] = [y for y in ext_result["years"] if y["age"] <= chart_end]
        # Also run the normal projection for the summary stats
        result = RetirementEngine(cfg).run_projection()
        scenario = {"name": name, "config": cfg, "result": result,
                    "ext_result": ext_result}
        path = os.path.join(SCENARIO_DIR, f"{name.replace(' ', '_')}.json")
        with open(path, "w") as f:
            json.dump(scenario, f, indent=2, default=str)
        flash(f"Scenario '{name}' saved.", "success")
        return redirect(url_for("compare"))

    scenarios = []
    for fname in sorted(os.listdir(SCENARIO_DIR)):
        if fname.endswith(".json"):
            try:
                with open(os.path.join(SCENARIO_DIR, fname)) as f:
                    sc = json.load(f)
                # Skip old-format files missing required keys
                if "config" not in sc or "result" not in sc:
                    continue
                if "name" not in sc:
                    sc["name"] = fname.replace(".json", "")
                sc["is_current"] = False
                sc["is_unsaved"] = False
                scenarios.append(sc)
            except (json.JSONDecodeError, KeyError):
                continue

    # Always inject the current config as a "Current" scenario.
    # If a saved scenario matches the current config fingerprint,
    # mark it as current instead of adding a duplicate.
    cfg = get_config()
    def _config_fingerprint(c):
        """Hash key config fields to detect matching scenarios."""
        import hashlib as _hl
        parts = [
            str(c.get("target_income", {}).get("net_annual", "")),
            str(c.get("target_income", {}).get("cpi_rate", "")),
            str(c.get("personal", {}).get("end_age", "")),
            str(c.get("withdrawal_priority", [])),
        ]
        for pot in c.get("dc_pots", []):
            parts.append(f"{pot['name']}:{pot['starting_balance']}")
        for acc in c.get("tax_free_accounts", []):
            parts.append(f"{acc['name']}:{acc['starting_balance']}")
        return _hl.md5("|".join(parts).encode()).hexdigest()

    current_fp = _config_fingerprint(cfg)
    matched = False
    for sc in scenarios:
        if _config_fingerprint(sc.get("config", {})) == current_fp:
            sc["is_current"] = True
            matched = True

    if not matched:
        import copy as _copy
        # Run extended projection for chart
        ext_cfg = _copy.deepcopy(cfg)
        plan_end_age = cfg["personal"]["end_age"]
        ext_cfg["personal"]["end_age"] = min(120, max(plan_end_age, 120))
        ext_result = RetirementEngine(ext_cfg).run_projection()
        DEPLETION_EPSILON = 1.0
        dep_age = None
        for yr in ext_result["years"]:
            if yr["total_capital"] <= DEPLETION_EPSILON:
                dep_age = yr["age"]
                break
        if dep_age:
            chart_end = min(120, max(plan_end_age, dep_age))
        else:
            chart_end = min(120, plan_end_age + 5)
        ext_result["years"] = [y for y in ext_result["years"] if y["age"] <= chart_end]
        # Normal projection for summary
        result = RetirementEngine(cfg).run_projection()
        current_sc = {
            "name": "Current",
            "config": cfg,
            "result": result,
            "ext_result": ext_result,
            "is_current": True,
            "is_unsaved": True,
        }
        scenarios.insert(0, current_sc)

    return render_template("compare.html", scenarios=scenarios, current_config=cfg)

@app.route("/delete_scenario/<name>")
@login_required
def delete_scenario(name):
    path = os.path.join(SCENARIO_DIR, f"{name.replace(' ', '_')}.json")
    if os.path.exists(path):
        os.remove(path)
        flash(f"Scenario '{name}' deleted.", "warning")
    return redirect(url_for("compare"))

# ------------------------------------------------------------------ #
#  What If Sandbox — ephemeral projection (never mutates session config)
# ------------------------------------------------------------------ #
@app.route("/whatif_project", methods=["POST"])
@login_required
def whatif_project():
    """Run a projection with sandbox overrides and return JSON chart data.

    Accepts JSON body with optional keys:
        target_income (float), cpi_rate (float), retirement_age (int)
    Returns JSON with years[] and summary for the sandbox projection.
    """
    import copy as _copy
    data = request.get_json(silent=True) or {}
    cfg = _copy.deepcopy(get_config())

    # Apply sandbox overrides
    if "target_income" in data:
        cfg["target_income"]["net_annual"] = float(data["target_income"])
    if "cpi_rate" in data:
        cfg["target_income"]["cpi_rate"] = float(data["cpi_rate"])
    if "retirement_age" in data:
        cfg["personal"]["retirement_age"] = int(data["retirement_age"])

    # Run extended projection for chart
    plan_end_age = cfg["personal"]["end_age"]
    ext_cfg = _copy.deepcopy(cfg)
    ext_cfg["personal"]["end_age"] = min(120, max(plan_end_age, 120))
    ext_result = RetirementEngine(ext_cfg).run_projection()

    DEPLETION_EPSILON = 1.0
    dep_age = None
    for yr in ext_result["years"]:
        if yr["total_capital"] <= DEPLETION_EPSILON:
            dep_age = yr["age"]
            break
    if dep_age:
        chart_end = min(120, max(plan_end_age, dep_age))
    else:
        chart_end = min(120, plan_end_age + 5)
    ext_result["years"] = [y for y in ext_result["years"] if y["age"] <= chart_end]

    # Normal projection for summary
    result = RetirementEngine(cfg).run_projection()

    return jsonify({
        "years": ext_result["years"],
        "summary": result["summary"],
    })

# ------------------------------------------------------------------ #
#  Optimiser
# ------------------------------------------------------------------ #
@app.route("/optimise")
@login_required
def optimise():
    cfg = get_config()
    opt = Optimiser(cfg)
    results = opt.run_all()
    return render_template("optimise.html", config=cfg, results=results)

@app.route("/apply_priority", methods=["POST"])
@login_required
def apply_priority():
    order = request.form.get("priority_order", "")
    if order:
        cfg = get_config()
        cfg["withdrawal_priority"] = [x.strip() for x in order.split(",") if x.strip()]
        save_session_config(cfg)
        flash("Withdrawal priority updated to recommended order.", "success")
    return redirect(url_for("optimise"))

# ------------------------------------------------------------------ #
#  API endpoint for charts
# ------------------------------------------------------------------ #
@app.route("/api/projection")
@login_required
def api_projection():
    cfg = get_config()
    engine = RetirementEngine(cfg)
    result = engine.run_projection()
    return jsonify(result)

# ------------------------------------------------------------------ #
#  Validation
# ------------------------------------------------------------------ #
@app.route("/validation", methods=["GET", "POST"])
@login_required
def validation():
    from datetime import datetime
    results = None
    generated_at = None
    if request.method == "POST":
        results = run_all_scenarios()
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    return render_template("validation.html",
                           results=results,
                           generated_at=generated_at,
                           scenario_count=len(ALL_SCENARIOS))

# ------------------------------------------------------------------ #
#  How It Works
# ------------------------------------------------------------------ #
@app.route("/how-it-works")
def how_it_works():
    return app.send_static_file("../HOW_IT_WORKS.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
