"""Retirement Income Planner — Flask Web Application (Dynamic Streams)"""
import os
import json
import copy
import hashlib
import functools
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify)
from retirement_engine import RetirementEngine, load_config, load_asset_model, resolve_growth_rate
from optimiser import Optimiser

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "pension-planner-secret-key-2025")

# ------------------------------------------------------------------ #
#  Asset Model (read-only reference data)
# ------------------------------------------------------------------ #
ASSET_MODEL = load_asset_model()

# ------------------------------------------------------------------ #
#  Auth
# ------------------------------------------------------------------ #
USERNAME = "PensionPlanner"
SALT = "iom_pension_2025"
PASSWORD_HASH = hashlib.sha256(f"planner123!{SALT}".encode()).hexdigest()

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
    ext_cfg["personal"]["end_age"] = 105
    ext_engine = RetirementEngine(ext_cfg)
    ext_result = ext_engine.run_projection()
    plan_end_age = cfg["personal"]["end_age"]
    # Find depletion age: first age where total_capital <= 0 in extended run
    depletion_age = None
    for yr in ext_result["years"]:
        if yr["total_capital"] <= 0:
            depletion_age = yr["age"]
            break
    # Trim extended years to depletion_age + 2 (or plan_end_age + 2 if no depletion)
    chart_end = (depletion_age + 2) if depletion_age else (plan_end_age + 2)
    ext_years_trimmed = [y for y in ext_result["years"] if y["age"] <= chart_end]

    # ---- Fan chart: optimistic & pessimistic projections ----
    # Optimistic: growth +1.5%, CPI -0.5%
    opt_cfg = _copy.deepcopy(cfg)
    opt_cfg["personal"]["end_age"] = 105
    for pot in opt_cfg["dc_pots"]:
        pot["growth_rate"] = pot["growth_rate"] + 0.015
    for acc in opt_cfg["tax_free_accounts"]:
        acc["growth_rate"] = acc["growth_rate"] + 0.015
    opt_cfg["target_income"]["cpi_rate"] = max(0, opt_cfg["target_income"]["cpi_rate"] - 0.005)
    opt_engine = RetirementEngine(opt_cfg)
    opt_result = opt_engine.run_projection()
    fan_optimistic = [
        {"age": y["age"], "total_capital": y["total_capital"]}
        for y in opt_result["years"] if y["age"] <= chart_end
    ]

    # Pessimistic: growth -1.5%, CPI +0.5%
    pes_cfg = _copy.deepcopy(cfg)
    pes_cfg["personal"]["end_age"] = 105
    for pot in pes_cfg["dc_pots"]:
        pot["growth_rate"] = max(0, pot["growth_rate"] - 0.015)
    for acc in pes_cfg["tax_free_accounts"]:
        acc["growth_rate"] = max(0, acc["growth_rate"] - 0.015)
    pes_cfg["target_income"]["cpi_rate"] = pes_cfg["target_income"]["cpi_rate"] + 0.005
    pes_engine = RetirementEngine(pes_cfg)
    pes_result = pes_engine.run_projection()
    fan_pessimistic = [
        {"age": y["age"], "total_capital": y["total_capital"]}
        for y in pes_result["years"] if y["age"] <= chart_end
    ]

    return render_template("dashboard.html", config=cfg, result=result,
                           ext_years=ext_years_trimmed,
                           plan_end_age=plan_end_age,
                           depletion_age=depletion_age,
                           fan_optimistic=fan_optimistic,
                           fan_pessimistic=fan_pessimistic)

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

    return render_template("settings.html", config=cfg, asset_model=ASSET_MODEL)

# ------------------------------------------------------------------ #
#  Scenarios
# ------------------------------------------------------------------ #
@app.route("/compare", methods=["GET", "POST"])
@login_required
def compare():
    if request.method == "POST":
        cfg = get_config()
        name = request.form.get("scenario_name", "Unnamed")
        engine = RetirementEngine(cfg)
        result = engine.run_projection()
        scenario = {"name": name, "config": cfg, "result": result}
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
                scenarios.append(sc)
            except (json.JSONDecodeError, KeyError):
                continue
    return render_template("compare.html", scenarios=scenarios)

@app.route("/delete_scenario/<name>")
@login_required
def delete_scenario(name):
    path = os.path.join(SCENARIO_DIR, f"{name.replace(' ', '_')}.json")
    if os.path.exists(path):
        os.remove(path)
        flash(f"Scenario '{name}' deleted.", "warning")
    return redirect(url_for("compare"))

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
#  How It Works
# ------------------------------------------------------------------ #
@app.route("/how-it-works")
def how_it_works():
    return app.send_static_file("../HOW_IT_WORKS.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
