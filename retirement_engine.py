"""Retirement Income Planner — Projection Engine (Monthly Stepping)

Month-by-month deterministic projection supporting dynamic income streams.
Tax is computed annually; growth, fees, and withdrawals step monthly.
"""
import copy
import json
import math
import os


# ------------------------------------------------------------------ #
#  Monthly conversion helpers
# ------------------------------------------------------------------ #
def annual_to_monthly_rate(annual_rate):
    """Convert an annual rate to a monthly compound-equivalent rate."""
    if annual_rate == 0:
        return 0.0
    return (1 + annual_rate) ** (1 / 12) - 1


# ------------------------------------------------------------------ #
#  Asset Model helpers
# ------------------------------------------------------------------ #
ASSET_MODEL_PATH = os.path.join(os.path.dirname(__file__), "asset_model.json")


def load_asset_model():
    """Load the 6-asset model reference data."""
    with open(ASSET_MODEL_PATH) as f:
        return json.load(f)


def resolve_growth_rate(pot_config, asset_model):
    """Compute blended geometric growth rate from allocation, or return manual rate.

    If manual_override is True, always use the explicit growth_rate from config.
    Otherwise, derive the rate from the selected template or custom weights.
    """
    alloc = pot_config.get("allocation", {})
    mode = alloc.get("mode", "manual")
    manual_override = alloc.get("manual_override", False)

    if mode == "manual" or not alloc or manual_override:
        return pot_config.get("growth_rate", 0.04)

    # Build asset class lookup
    ac_lookup = {ac["id"]: ac for ac in asset_model["asset_classes"]}

    if mode == "template":
        template_id = alloc.get("template_id", "")
        templates = {t["id"]: t for t in asset_model["portfolio_templates"]}
        template = templates.get(template_id)
        if not template:
            return pot_config.get("growth_rate", 0.04)
        weights = {w["asset_class_id"]: w["weight"] for w in template["weights"]}
    elif mode == "custom":
        weights = alloc.get("custom_weights", {})
    else:
        return pot_config.get("growth_rate", 0.04)

    # Compute weighted geometric return
    blended = sum(
        weights.get(ac_id, 0) * ac_lookup[ac_id]["geometric_return"]
        for ac_id in weights
        if ac_id in ac_lookup
    )
    return blended if blended > 0 else pot_config.get("growth_rate", 0.04)



def resolve_growth_provenance(pot_config, asset_model):
    """Return a provenance dict describing WHERE the growth rate comes from.

    Returns:
        dict with keys:
            'source'  – short label  (e.g. "Template", "Manual", "Custom")
            'detail'  – longer text  (e.g. "Balanced 80/20 (Equity/Bonds) → 5.12%")
            'rate'    – the resolved numeric rate
    """
    alloc = pot_config.get("allocation", {})
    mode = alloc.get("mode", "manual")
    manual_override = alloc.get("manual_override", False)
    fallback_rate = pot_config.get("growth_rate", 0.04)

    if mode == "manual" or not alloc or manual_override:
        return {
            "source": "Manual",
            "detail": f"User-defined rate: {fallback_rate*100:.2f}%",
            "rate": fallback_rate,
        }

    ac_lookup = {ac["id"]: ac for ac in asset_model["asset_classes"]}

    if mode == "template":
        template_id = alloc.get("template_id", "")
        templates = {t["id"]: t for t in asset_model["portfolio_templates"]}
        template = templates.get(template_id)
        if not template:
            return {
                "source": "Manual",
                "detail": f"Template '{template_id}' not found; fallback rate: {fallback_rate*100:.2f}%",
                "rate": fallback_rate,
            }
        # Compute blended rate for detail string
        weights = {w["asset_class_id"]: w["weight"] for w in template["weights"]}
        blended = sum(
            weights.get(ac_id, 0) * ac_lookup[ac_id]["geometric_return"]
            for ac_id in weights if ac_id in ac_lookup
        )
        rate = blended if blended > 0 else fallback_rate
        # Build weight breakdown
        parts = []
        for w in template["weights"]:
            ac = ac_lookup.get(w["asset_class_id"])
            if ac and w["weight"] > 0:
                parts.append(f"{ac["label"]} {w["weight"]*100:.0f}%")
        mix_str = ", ".join(parts)
        return {
            "source": "Template",
            "detail": f"{template["label"]} (risk {template.get("risk_score","?")}): {mix_str} → {rate*100:.2f}%",
            "rate": rate,
        }

    elif mode == "custom":
        weights = alloc.get("custom_weights", {})
        blended = sum(
            weights.get(ac_id, 0) * ac_lookup[ac_id]["geometric_return"]
            for ac_id in weights if ac_id in ac_lookup
        )
        rate = blended if blended > 0 else fallback_rate
        parts = []
        for ac_id, w in weights.items():
            ac = ac_lookup.get(ac_id)
            if ac and w > 0:
                parts.append(f"{ac["label"]} {w*100:.0f}%")
        mix_str = ", ".join(parts)
        return {
            "source": "Custom",
            "detail": f"Custom allocation: {mix_str} → {rate*100:.2f}%",
            "rate": rate,
        }

    return {
        "source": "Manual",
        "detail": f"Fallback rate: {fallback_rate*100:.2f}%",
        "rate": fallback_rate,
    }

class RetirementEngine:
    """Run a monthly-stepping retirement income projection with annual tax."""

    def __init__(self, config: dict):
        self.cfg = copy.deepcopy(config)
        self._validate_config()

    # ------------------------------------------------------------------ #
    #  Validation
    # ------------------------------------------------------------------ #
    def _validate_config(self):
        required = ["personal", "target_income", "guaranteed_income",
                    "dc_pots", "tax_free_accounts", "withdrawal_priority", "tax"]
        for key in required:
            if key not in self.cfg:
                raise ValueError(f"Missing config key: {key}")

    # ------------------------------------------------------------------ #
    #  IoM Tax
    # ------------------------------------------------------------------ #
    def calculate_tax(self, taxable_income: float) -> dict:
        """Calculate IoM tax and return a full breakdown dict.

        Returns:
            dict with keys: total, taxable_income, personal_allowance,
                  income_after_pa, bands, marginal_rate, tax_cap_applied
        """
        tax_cfg = self.cfg["tax"]
        pa = tax_cfg["personal_allowance"]
        income_after_pa = max(0, taxable_income - pa)
        tax = 0.0
        remaining = income_after_pa
        band_details = []
        marginal_rate = 0.0
        for band in tax_cfg["bands"]:
            width = band["width"]
            rate = band["rate"]
            if width is None:
                taxable_in_band = remaining
                band_tax = remaining * rate
                tax += band_tax
                band_details.append({
                    'name': f'{int(rate * 100)}%',
                    'rate': rate,
                    'width': 'remainder',
                    'taxable_in_band': round(taxable_in_band, 2),
                    'tax': round(band_tax, 2),
                })
                if taxable_in_band > 0:
                    marginal_rate = rate
                remaining = 0
            else:
                taxable_in_band = min(remaining, width)
                band_tax = taxable_in_band * rate
                tax += band_tax
                band_details.append({
                    'name': f'{int(rate * 100)}%',
                    'rate': rate,
                    'width': width,
                    'taxable_in_band': round(taxable_in_band, 2),
                    'tax': round(band_tax, 2),
                })
                if taxable_in_band > 0:
                    marginal_rate = rate
                remaining -= taxable_in_band
            if remaining <= 0:
                break

        tax_cap_applied = False
        if tax_cfg.get("tax_cap_enabled") and tax > tax_cfg.get("tax_cap_amount", 200000):
            tax = tax_cfg["tax_cap_amount"]
            tax_cap_applied = True

        return {
            'total': round(tax, 2),
            'taxable_income': round(taxable_income, 2),
            'personal_allowance': pa,
            'income_after_pa': round(income_after_pa, 2),
            'bands': band_details,
            'marginal_rate': marginal_rate,
            'tax_cap_applied': tax_cap_applied,
        }

    # ------------------------------------------------------------------ #
    #  UK Tax (for comparison)
    # ------------------------------------------------------------------ #
    def calculate_uk_tax(self, taxable_income: float) -> dict:
        """Calculate UK tax and return a full breakdown dict.

        Returns:
            dict with keys: total, taxable_income, personal_allowance,
                  income_after_pa, bands, marginal_rate, tax_cap_applied
        """
        pa = 12570
        income_after_pa = max(0, taxable_income - pa)
        bands = [
            (37700, 0.20, 'Basic 20%'),
            (74870, 0.40, 'Higher 40%'),
            (None, 0.45, 'Additional 45%'),
        ]
        tax = 0.0
        remaining = income_after_pa
        band_details = []
        marginal_rate = 0.0
        for width, rate, name in bands:
            if width is None:
                taxable_in_band = remaining
                band_tax = remaining * rate
                tax += band_tax
                band_details.append({
                    'name': name,
                    'rate': rate,
                    'width': 'remainder',
                    'taxable_in_band': round(taxable_in_band, 2),
                    'tax': round(band_tax, 2),
                })
                if taxable_in_band > 0:
                    marginal_rate = rate
                remaining = 0
            else:
                taxable_in_band = min(remaining, width)
                band_tax = taxable_in_band * rate
                tax += band_tax
                band_details.append({
                    'name': name,
                    'rate': rate,
                    'width': width,
                    'taxable_in_band': round(taxable_in_band, 2),
                    'tax': round(band_tax, 2),
                })
                if taxable_in_band > 0:
                    marginal_rate = rate
                remaining -= taxable_in_band
            if remaining <= 0:
                break

        return {
            'total': round(tax, 2),
            'taxable_income': round(taxable_income, 2),
            'personal_allowance': pa,
            'income_after_pa': round(income_after_pa, 2),
            'bands': band_details,
            'marginal_rate': marginal_rate,
            'tax_cap_applied': False,
        }

    # ------------------------------------------------------------------ #
    #  Gross-up solver
    # ------------------------------------------------------------------ #
    def gross_up(self, net_needed: float, guaranteed_taxable: float,
                 tax_free_portion: float) -> float:
        """Find DC gross withdrawal to achieve net_needed using marginal tax.

        The marginal approach correctly calculates the additional tax caused
        by the DC withdrawal on top of existing taxable income, rather than
        pro-rating total tax (which is wrong for progressive tax bands).
        """
        if net_needed <= 0:
            return 0.0
        tax_on_existing = self.calculate_tax(guaranteed_taxable)['total']
        lo, hi = net_needed, net_needed * 3
        for _ in range(80):
            mid = (lo + hi) / 2
            taxable_part = mid * (1 - tax_free_portion)
            total_taxable = guaranteed_taxable + taxable_part
            total_tax = self.calculate_tax(total_taxable)['total']
            marginal_tax = total_tax - tax_on_existing
            net_from_dc = mid - marginal_tax
            if abs(net_from_dc - net_needed) < 0.50:
                return round(mid, 2)
            if net_from_dc < net_needed:
                lo = mid
            else:
                hi = mid
        return round((lo + hi) / 2, 2)

    # ------------------------------------------------------------------ #
    #  Monthly gross-up helper
    # ------------------------------------------------------------------ #
    def _monthly_gross_up(self, net_needed, taxable_ytd, tax_free_portion):
        """Gross-up a monthly DC withdrawal using YTD taxable income context.

        Uses the running tax-year taxable total to find the correct marginal
        rate, then computes the gross withdrawal needed to yield net_needed
        after marginal tax on the taxable portion.
        """
        if net_needed <= 0:
            return 0.0
        tax_on_existing = self.calculate_tax(taxable_ytd)['total']
        lo, hi = net_needed, net_needed * 3
        for _ in range(60):
            mid = (lo + hi) / 2
            taxable_part = mid * (1 - tax_free_portion)
            total_tax = self.calculate_tax(taxable_ytd + taxable_part)['total']
            marginal_tax = total_tax - tax_on_existing
            net_from_dc = mid - marginal_tax
            if abs(net_from_dc - net_needed) < 0.50:
                return round(mid, 2)
            if net_from_dc < net_needed:
                lo = mid
            else:
                hi = mid
        return round((lo + hi) / 2, 2)

    # ------------------------------------------------------------------ #
    #  Annual summary aggregation
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_year_row(agg, dc_balances, tf_balances, dc_meta, tf_meta,
                        iom_tax_result, uk_tax_result):
        """Build a single annual summary row from monthly aggregates."""
        tax_due = iom_tax_result["total"]
        uk_tax_due = uk_tax_result["total"]
        net_income = (agg["guaranteed_gross"] + agg["dc_gross"]
                      + agg["tf_total"] - tax_due)
        total_taxable = agg["guaranteed_taxable"] + (agg["dc_gross"] - agg["dc_tf"])
        total_capital = sum(dc_balances.values()) + sum(tf_balances.values())

        # Build pot P&L
        pot_pnl = {}
        for name in dc_balances:
            pot_pnl[name] = {
                "opening": round(agg["pnl"][name]["opening"], 2),
                "growth": round(agg["pnl"][name]["growth"], 2),
                "fees": round(agg["pnl"][name]["fees"], 2),
                "withdrawal": round(agg["pnl"][name]["withdrawal"], 2),
                "closing": round(dc_balances[name], 2),
                "provenance": dc_meta[name]["provenance"],
            }
        for name in tf_balances:
            pot_pnl[name] = {
                "opening": round(agg["pnl"][name]["opening"], 2),
                "growth": round(agg["pnl"][name]["growth"], 2),
                "fees": 0.0,
                "withdrawal": round(agg["pnl"][name]["withdrawal"], 2),
                "closing": round(tf_balances[name], 2),
                "provenance": tf_meta[name]["provenance"],
            }
        wd = {n: round(v, 2) for n, v in agg["withdrawal_detail"].items()}

        return {
            "age": agg["age"],
            "tax_year": agg["tax_year"],
            "target_net": round(agg["target_annual"], 2),
            "guaranteed_income": agg["guaranteed_detail"],
            "guaranteed_total": round(agg["guaranteed_gross"], 2),
            "dc_withdrawal_gross": round(agg["dc_gross"], 2),
            "dc_tax_free_portion": round(agg["dc_tf"], 2),
            "tf_withdrawal": round(agg["tf_total"], 2),
            "withdrawal_detail": wd,
            "total_taxable_income": round(total_taxable, 2),
            "tax_due": round(tax_due, 2),
            "uk_tax_due": round(uk_tax_due, 2),
            "iom_tax_breakdown": iom_tax_result,
            "uk_tax_breakdown": uk_tax_result,
            "net_income_achieved": round(net_income, 2),
            "shortfall": net_income < agg["target_annual"] - 1,
            "pot_balances": {n: round(b, 2) for n, b in dc_balances.items()},
            "tf_balances": {n: round(b, 2) for n, b in tf_balances.items()},
            "total_capital": round(total_capital, 2),
            "pot_pnl": pot_pnl,
        }

    # ------------------------------------------------------------------ #
    #  Main projection  (truly monthly planning)
    # ------------------------------------------------------------------ #
    def run_projection(self, include_monthly: bool = False) -> dict:
        cfg = self.cfg
        retirement_age = cfg["personal"]["retirement_age"]
        end_age = cfg["personal"]["end_age"]
        target_net_annual = cfg["target_income"]["net_annual"]
        cpi = cfg["target_income"]["cpi_rate"]
        monthly_cpi = annual_to_monthly_rate(cpi)

        # Load asset model for growth rate resolution
        asset_model = load_asset_model()

        # ------------------------------------------------------------ #
        #  Date helpers
        # ------------------------------------------------------------ #
        def ym_to_abs(y, m):
            """Convert (year, month) to absolute month count."""
            return y * 12 + (m - 1)

        def abs_to_ym(a):
            """Convert absolute month count back to (year, month 1-12)."""
            y, m = divmod(a, 12)
            return y, m + 1

        def parse_ym(s):
            parts = s.split("-")
            return int(parts[0]), int(parts[1])

        def age_at_abs(abs_month):
            """Fractional age at a given absolute month."""
            return (abs_month - dob_abs) / 12.0

        # Parse key dates
        dob_y, dob_m = parse_ym(cfg["personal"]["date_of_birth"])
        dob_abs = ym_to_abs(dob_y, dob_m)

        ret_y, ret_m = parse_ym(cfg["personal"]["retirement_date"])
        ret_abs = ym_to_abs(ret_y, ret_m)

        # ------------------------------------------------------------ #
        #  Anchor date — latest values_as_of, but never before retirement
        # ------------------------------------------------------------ #
        all_asof_abs = []
        for g in cfg["guaranteed_income"]:
            if g.get("values_as_of"):
                gy, gm = parse_ym(g["values_as_of"])
                all_asof_abs.append(ym_to_abs(gy, gm))
        for pot in cfg["dc_pots"]:
            if pot.get("values_as_of"):
                py, pm = parse_ym(pot["values_as_of"])
                all_asof_abs.append(ym_to_abs(py, pm))
        for acc in cfg["tax_free_accounts"]:
            if acc.get("values_as_of"):
                ay, am = parse_ym(acc["values_as_of"])
                all_asof_abs.append(ym_to_abs(ay, am))

        latest_asof = max(all_asof_abs) if all_asof_abs else ret_abs
        anchor_abs = max(ret_abs, latest_asof)
        anchor_age = int(age_at_abs(anchor_abs))
        anchor_age = max(anchor_age, retirement_age)

        is_post_retirement = anchor_abs > ret_abs

        # End absolute month — cover full 12-month year for each age
        # anchor_age to end_age inclusive = (end_age - anchor_age + 1) years
        end_abs = anchor_abs + (end_age - anchor_age + 1) * 12 - 1

        # ------------------------------------------------------------ #
        #  Build guaranteed income — index to anchor, compute start/end
        #  as absolute months for month-level activation
        # ------------------------------------------------------------ #
        guaranteed = []
        for g in cfg["guaranteed_income"]:
            annual = g["gross_annual"]
            idx_rate = g.get("indexation_rate", 0)
            monthly_idx = annual_to_monthly_rate(idx_rate) if idx_rate > 0 else 0.0

            # Index from values_as_of to anchor
            if g.get("values_as_of") and idx_rate > 0:
                asof_y, asof_m = parse_ym(g["values_as_of"])
                gap = anchor_abs - ym_to_abs(asof_y, asof_m)
                if gap > 0:
                    annual = annual * (1 + idx_rate) ** (gap / 12.0)

            # Convert start_age / end_age to absolute months
            start_age = g.get("start_age", retirement_age)
            g_end_age = g.get("end_age")
            start_abs = dob_abs + int(round(start_age * 12))
            end_abs_g = dob_abs + int(round(g_end_age * 12)) if g_end_age is not None else None

            guaranteed.append({
                "name": g["name"],
                "monthly": annual / 12.0,
                "monthly_idx": monthly_idx,
                "start_abs": start_abs,
                "end_abs": end_abs_g,
                "taxable": g.get("taxable", True),
            })

        # ------------------------------------------------------------ #
        #  Build DC pot balances with pre-anchor growth
        # ------------------------------------------------------------ #
        dc_balances = {}
        dc_meta = {}
        for pot in cfg["dc_pots"]:
            name = pot["name"]
            balance = pot["starting_balance"]
            growth = resolve_growth_rate(pot, asset_model)
            fees = pot.get("annual_fees", 0.005)

            if pot.get("values_as_of"):
                py, pm = parse_ym(pot["values_as_of"])
                gap = anchor_abs - ym_to_abs(py, pm)
                if gap > 0:
                    mg = annual_to_monthly_rate(growth)
                    mf = annual_to_monthly_rate(fees)
                    for _ in range(gap):
                        balance = balance * (1 + mg) - balance * mf

            dc_balances[name] = balance
            dc_meta[name] = {
                "growth_rate": growth,
                "annual_fees": fees,
                "tax_free_portion": pot.get("tax_free_portion", 0.25),
                "provenance": resolve_growth_provenance(pot, asset_model),
            }

        # ------------------------------------------------------------ #
        #  Build tax-free account balances with pre-anchor growth
        # ------------------------------------------------------------ #
        tf_balances = {}
        tf_meta = {}
        for acc in cfg["tax_free_accounts"]:
            name = acc["name"]
            balance = acc["starting_balance"]
            growth = resolve_growth_rate(acc, asset_model)

            if acc.get("values_as_of"):
                ay, am = parse_ym(acc["values_as_of"])
                gap = anchor_abs - ym_to_abs(ay, am)
                if gap > 0:
                    mg = annual_to_monthly_rate(growth)
                    for _ in range(gap):
                        balance *= (1 + mg)

            tf_balances[name] = balance
            tf_meta[name] = {
                "growth_rate": growth,
                "provenance": resolve_growth_provenance(acc, asset_model),
            }

        priority = cfg.get("withdrawal_priority", [])

        # Pre-compute monthly rates
        dc_monthly = {}
        for name, meta in dc_meta.items():
            dc_monthly[name] = {
                "growth": annual_to_monthly_rate(meta["growth_rate"]),
                "fees": annual_to_monthly_rate(meta["annual_fees"]),
            }
        tf_monthly = {}
        for name, meta in tf_meta.items():
            tf_monthly[name] = {
                "growth": annual_to_monthly_rate(meta["growth_rate"]),
            }

        # ------------------------------------------------------------ #
        #  State variables
        # ------------------------------------------------------------ #
        years = []
        warnings = []
        first_shortfall_age = None
        first_pot_exhausted_age = None
        total_tax = 0.0
        total_uk_tax = 0.0
        depletion_events = []
        depleted_pots = set()

        # Monthly target net income (inflated from anchor)
        monthly_target = target_net_annual / 12.0
        if anchor_age > retirement_age:
            inflate_months = anchor_abs - ret_abs
            for _ in range(inflate_months):
                monthly_target *= (1 + monthly_cpi)

        # ------------------------------------------------------------ #
        #  Annual aggregation state
        # ------------------------------------------------------------ #
        def _new_agg(age_label, tax_year_label, target_annual):
            pnl_init = {}
            for n in dc_balances:
                pnl_init[n] = {"opening": dc_balances[n],
                               "growth": 0.0, "fees": 0.0, "withdrawal": 0.0}
            for n in tf_balances:
                pnl_init[n] = {"opening": tf_balances[n],
                               "growth": 0.0, "fees": 0.0, "withdrawal": 0.0}
            return {
                "age": age_label,
                "tax_year": tax_year_label,
                "target_annual": target_annual,
                "guaranteed_gross": 0.0,
                "guaranteed_taxable": 0.0,
                "guaranteed_detail": {},
                "dc_gross": 0.0,
                "dc_tf": 0.0,
                "tf_total": 0.0,
                "withdrawal_detail": {},
                "pnl": pnl_init,
                "months_counted": 0,
            }

        # Tax-year YTD taxable income (for tax context)
        taxable_ytd = 0.0

        # Optional monthly debug rows
        monthly_rows = [] if include_monthly else None

        # ------------------------------------------------------------ #
        #  MAIN MONTHLY LOOP
        #  Annual withdrawal plan at year boundaries; monthly execution.
        # ------------------------------------------------------------ #
        current_agg = None
        current_year_age = None
        monthly_dc_target = 0.0
        monthly_tf_target = 0.0

        for abs_m in range(anchor_abs, end_abs + 1):
            cal_y, cal_m = abs_to_ym(abs_m)
            year_age = anchor_age + (abs_m - anchor_abs) // 12

            # ---- Year boundary: finalise previous, plan next ---- #
            if year_age != current_year_age:
                if current_agg is not None:
                    # Build annual row
                    total_taxable_yr = (current_agg["guaranteed_taxable"]
                                        + (current_agg["dc_gross"] - current_agg["dc_tf"]))
                    iom_tax = self.calculate_tax(total_taxable_yr)
                    uk_tax = self.calculate_uk_tax(total_taxable_yr)
                    yr_row = self._build_year_row(
                        current_agg, dc_balances, tf_balances,
                        dc_meta, tf_meta, iom_tax, uk_tax)
                    years.append(yr_row)
                    total_tax += iom_tax["total"]
                    total_uk_tax += uk_tax["total"]
                    if yr_row["shortfall"] and first_shortfall_age is None:
                        first_shortfall_age = yr_row["age"]

                # ---- New year setup ---- #
                taxable_ytd = 0.0
                current_year_age = year_age

                year_offset = year_age - anchor_age
                cy = cal_y if is_post_retirement else ret_y + year_offset
                tax_year_label = f"{cy}/{str(cy + 1)[-2:]}"
                target_annual = monthly_target * 12.0
                current_agg = _new_agg(year_age, tax_year_label, target_annual)

                # ---- Annual withdrawal plan (gross-up with annual context) ---- #
                est_guar_gross = 0.0
                est_guar_taxable = 0.0
                for gi in guaranteed:
                    active = (abs_m >= gi["start_abs"] and
                              (gi["end_abs"] is None or abs_m <= gi["end_abs"]))
                    if active:
                        est_guar_gross += gi["monthly"] * 12
                        if gi["taxable"]:
                            est_guar_taxable += gi["monthly"] * 12

                tax_on_guar = self.calculate_tax(est_guar_taxable)["total"]
                net_from_guar = est_guar_gross - tax_on_guar
                annual_shortfall = max(0, target_annual - net_from_guar)

                planned_dc_gross = 0.0
                planned_dc_tf = 0.0
                planned_tf = 0.0
                remaining_plan = annual_shortfall

                for source_name in priority:
                    if remaining_plan <= 0:
                        break
                    if source_name in dc_balances:
                        tfp = dc_meta[source_name]["tax_free_portion"]
                        gross_needed = self.gross_up(
                            remaining_plan,
                            est_guar_taxable + (planned_dc_gross - planned_dc_tf),
                            tfp)
                        gross_needed = min(gross_needed, max(0, dc_balances[source_name]))
                        planned_dc_gross += gross_needed
                        planned_dc_tf += gross_needed * tfp
                        total_taxable_est = est_guar_taxable + (planned_dc_gross - planned_dc_tf)
                        tax_est = self.calculate_tax(total_taxable_est)["total"]
                        net_so_far = est_guar_gross + planned_dc_gross + planned_tf - tax_est
                        remaining_plan = max(0, target_annual - net_so_far)
                    elif source_name in tf_balances:
                        withdraw = min(remaining_plan, max(0, tf_balances[source_name]))
                        planned_tf += withdraw
                        remaining_plan -= withdraw

                monthly_dc_target = planned_dc_gross / 12.0
                monthly_tf_target = planned_tf / 12.0

            # ---- Step 1: Monthly growth and fees ---- #
            for name in list(dc_balances):
                bal = dc_balances[name]
                if bal > 0:
                    g = bal * dc_monthly[name]["growth"]
                    f = bal * dc_monthly[name]["fees"]
                    dc_balances[name] = bal + g - f
                    current_agg["pnl"][name]["growth"] += g
                    current_agg["pnl"][name]["fees"] += f

            for name in list(tf_balances):
                bal = tf_balances[name]
                if bal > 0:
                    g = bal * tf_monthly[name]["growth"]
                    tf_balances[name] = bal + g
                    current_agg["pnl"][name]["growth"] += g

            # ---- Step 2: Monthly guaranteed income ---- #
            for gi in guaranteed:
                active = (abs_m >= gi["start_abs"] and
                          (gi["end_abs"] is None or abs_m <= gi["end_abs"]))
                if active:
                    amt = gi["monthly"]
                    current_agg["guaranteed_gross"] += amt
                    if gi["taxable"]:
                        current_agg["guaranteed_taxable"] += amt
                        taxable_ytd += amt
                    prev = current_agg["guaranteed_detail"].get(gi["name"], 0.0)
                    current_agg["guaranteed_detail"][gi["name"]] = prev + amt
                else:
                    if gi["name"] not in current_agg["guaranteed_detail"]:
                        current_agg["guaranteed_detail"][gi["name"]] = 0.0

                # Monthly indexation (always, even if inactive)
                if gi["monthly_idx"] > 0:
                    gi["monthly"] *= (1 + gi["monthly_idx"])

            # ---- Step 3: Execute planned monthly withdrawals ---- #
            remaining_dc = monthly_dc_target
            remaining_tf = monthly_tf_target

            for source_name in priority:
                if source_name in dc_balances and remaining_dc > 0:
                    available = max(0, dc_balances[source_name])
                    actual = min(remaining_dc, available)
                    if actual > 0:
                        dc_balances[source_name] -= actual
                        # Last-residual drawdown: if what's left can't
                        # cover a full month's income, sweep the rest.
                        residual = dc_balances[source_name]
                        if 0 < residual < monthly_target:
                            actual += residual
                            dc_balances[source_name] = 0.0
                        elif residual < 0.01:
                            dc_balances[source_name] = 0.0
                        tfp = dc_meta[source_name]["tax_free_portion"]
                        current_agg["dc_gross"] += actual
                        current_agg["dc_tf"] += actual * tfp
                        taxable_ytd += actual * (1 - tfp)
                        current_agg["withdrawal_detail"][source_name] = (
                            current_agg["withdrawal_detail"].get(source_name, 0) + actual)
                        current_agg["pnl"][source_name]["withdrawal"] += actual
                        remaining_dc -= actual

                elif source_name in tf_balances and remaining_tf > 0:
                    available = max(0, tf_balances[source_name])
                    actual = min(remaining_tf, available)
                    if actual > 0:
                        tf_balances[source_name] -= actual
                        # Last-residual drawdown: if what's left can't
                        # cover a full month's income, sweep the rest.
                        residual = tf_balances[source_name]
                        if 0 < residual < monthly_target:
                            actual += residual
                            tf_balances[source_name] = 0.0
                        elif residual < 0.01:
                            tf_balances[source_name] = 0.0
                        current_agg["tf_total"] += actual
                        current_agg["withdrawal_detail"][source_name] = (
                            current_agg["withdrawal_detail"].get(source_name, 0) + actual)
                        current_agg["pnl"][source_name]["withdrawal"] += actual
                        remaining_tf -= actual

            # ---- Step 4: Depletion detection ---- #
            for pname in list(dc_balances):
                if dc_balances[pname] <= 0 and pname not in depleted_pots:
                    depleted_pots.add(pname)
                    month_in_year = (abs_m - anchor_abs) % 12 + 1
                    depletion_events.append({
                        "pot": pname, "age": year_age,
                        "month": month_in_year,
                    })
                    if first_pot_exhausted_age is None:
                        first_pot_exhausted_age = year_age
                    warnings.append(
                        f"{pname} exhausted at age {year_age} month {month_in_year}")
            for pname in list(tf_balances):
                if tf_balances[pname] <= 0 and pname not in depleted_pots:
                    depleted_pots.add(pname)
                    month_in_year = (abs_m - anchor_abs) % 12 + 1
                    depletion_events.append({
                        "pot": pname, "age": year_age,
                        "month": month_in_year,
                    })
                    if first_pot_exhausted_age is None:
                        first_pot_exhausted_age = year_age
                    warnings.append(
                        f"{pname} exhausted at age {year_age} month {month_in_year}")

            # ---- Step 5: Monthly CPI on target ---- #
            monthly_target *= (1 + monthly_cpi)
            current_agg["months_counted"] += 1

            # ---- Step 6: Collect monthly debug row ---- #
            if monthly_rows is not None:
                month_in_year = (abs_m - anchor_abs) % 12 + 1
                monthly_rows.append({
                    "year": cal_y,
                    "month": cal_m,
                    "age": year_age,
                    "month_in_year": month_in_year,
                    "target_monthly": round(monthly_target / (1 + monthly_cpi), 2),
                    "guaranteed_this_month": round(
                        sum(gi["monthly"] for gi in guaranteed
                            if abs_m >= gi["start_abs"]
                            and (gi["end_abs"] is None or abs_m <= gi["end_abs"])), 2),
                    "dc_drawdown_this_month": round(
                        monthly_dc_target - remaining_dc, 2),
                    "tf_drawdown_this_month": round(
                        monthly_tf_target - remaining_tf, 2),
                    "dc_balances": {n: round(b, 2) for n, b in dc_balances.items()},
                    "tf_balances": {n: round(b, 2) for n, b in tf_balances.items()},
                    "total_capital": round(
                        sum(dc_balances.values()) + sum(tf_balances.values()), 2),
                    "depleted_this_month": [
                        e["pot"] for e in depletion_events
                        if e["age"] == year_age and e["month"] == month_in_year],
                })

        # ---- Finalise last year ---- #
        if current_agg is not None and current_agg["months_counted"] > 0:
            total_taxable_final = (current_agg["guaranteed_taxable"]
                                   + (current_agg["dc_gross"] - current_agg["dc_tf"]))
            iom_tax = self.calculate_tax(total_taxable_final)
            uk_tax = self.calculate_uk_tax(total_taxable_final)
            yr_row = self._build_year_row(
                current_agg, dc_balances, tf_balances,
                dc_meta, tf_meta, iom_tax, uk_tax)
            years.append(yr_row)
            total_tax += iom_tax["total"]
            total_uk_tax += uk_tax["total"]
            if yr_row["shortfall"] and first_shortfall_age is None:
                first_shortfall_age = yr_row["age"]

        # Round guaranteed detail in all year rows
        for yr in years:
            yr["guaranteed_income"] = {
                k: round(v, 2) for k, v in yr["guaranteed_income"].items()
            }

        # Summary
        num_years = len(years)
        summary = {
            "sustainable": first_shortfall_age is None,
            "first_shortfall_age": first_shortfall_age,
            "end_age": end_age,
            "anchor_age": anchor_age,
            "is_post_retirement": is_post_retirement,
            "num_years": num_years,
            "remaining_capital": round(sum(dc_balances.values()) + sum(tf_balances.values()), 2),
            "remaining_pots": {n: round(b, 2) for n, b in dc_balances.items()},
            "remaining_tf": {n: round(b, 2) for n, b in tf_balances.items()},
            "total_tax_paid": round(total_tax, 2),
            "total_uk_tax_paid": round(total_uk_tax, 2),
            "uk_tax_saving": round(total_uk_tax - total_tax, 2),
            "avg_effective_tax_rate": round(
                (total_tax / sum(y["total_taxable_income"] for y in years) * 100)
                if sum(y["total_taxable_income"] for y in years) > 0 else 0, 1),
            "first_pot_exhausted_age": first_pot_exhausted_age,
            "depletion_events": depletion_events,
        }

        result = {"years": years, "summary": summary, "warnings": warnings}
        if monthly_rows is not None:
            result["monthly_rows"] = monthly_rows
        return result

def load_config(path: str = "config_default.json") -> dict:
    with open(path) as f:
        return json.load(f)


if __name__ == "__main__":
    cfg = load_config()
    engine = RetirementEngine(cfg)
    result = engine.run_projection()
    s = result["summary"]
    print(f"Sustainable: {s['sustainable']}")
    print(f"Remaining capital at age {s['end_age']}: \u00a3{s['remaining_capital']:,.0f}")
    print(f"Total IoM tax: \u00a3{s['total_tax_paid']:,.0f}")
    print(f"Total UK tax:  \u00a3{s['total_uk_tax_paid']:,.0f}")
    print(f"Tax saving:    \u00a3{s['uk_tax_saving']:,.0f}")
    for w in result["warnings"]:
        print(f"  \u26a0 {w}")
