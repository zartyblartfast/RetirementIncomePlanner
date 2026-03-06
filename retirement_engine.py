"""Retirement Income Planner — Projection Engine (Dynamic Streams)

Year-by-year deterministic projection supporting dynamic income streams.
"""
import copy
import json
import math
import os


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
    """Run a year-by-year retirement income projection."""

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
    #  Main projection
    # ------------------------------------------------------------------ #
    def run_projection(self) -> dict:
        cfg = self.cfg
        retirement_age = cfg["personal"]["retirement_age"]
        end_age = cfg["personal"]["end_age"]
        target_net = cfg["target_income"]["net_annual"]
        cpi = cfg["target_income"]["cpi_rate"]

        # Load asset model for growth rate resolution
        asset_model = load_asset_model()

        # Parse retirement date
        ret_date_str = cfg["personal"]["retirement_date"]  # e.g. "2027-04"
        ret_parts = ret_date_str.split("-")
        ret_year, ret_month = int(ret_parts[0]), int(ret_parts[1])

        # Parse date of birth for age calculations
        dob_str = cfg["personal"]["date_of_birth"]  # e.g. "1958-07"
        dob_parts = dob_str.split("-")
        dob_year, dob_month = int(dob_parts[0]), int(dob_parts[1])

        # ------------------------------------------------------------ #
        #  Helper: convert YYYY-MM string to fractional months
        # ------------------------------------------------------------ #
        def ym_to_months(y, m):
            return y * 12 + m

        def date_to_age(date_year, date_month):
            """Convert a YYYY-MM date to a fractional age."""
            months_from_birth = ym_to_months(date_year, date_month) - ym_to_months(dob_year, dob_month)
            return months_from_birth / 12.0

        def parse_ym(s):
            """Parse a YYYY-MM string into (year, month) tuple."""
            parts = s.split("-")
            return int(parts[0]), int(parts[1])

        # ------------------------------------------------------------ #
        #  C3: Determine anchor date — latest values_as_of across all
        #  sources, but never earlier than retirement date.
        # ------------------------------------------------------------ #
        all_asof_months = []

        # Guaranteed income values_as_of
        for g in cfg["guaranteed_income"]:
            if g.get("values_as_of"):
                gy, gm = parse_ym(g["values_as_of"])
                all_asof_months.append(ym_to_months(gy, gm))

        # DC pot values_as_of
        for pot in cfg["dc_pots"]:
            if pot.get("values_as_of"):
                py, pm = parse_ym(pot["values_as_of"])
                all_asof_months.append(ym_to_months(py, pm))

        # Tax-free account values_as_of
        for acc in cfg["tax_free_accounts"]:
            if acc.get("values_as_of"):
                ay, am = parse_ym(acc["values_as_of"])
                all_asof_months.append(ym_to_months(ay, am))

        ret_months = ym_to_months(ret_year, ret_month)

        if all_asof_months:
            latest_asof_months = max(all_asof_months)
        else:
            latest_asof_months = ret_months

        # Anchor is the later of retirement date or latest values_as_of
        # If all values_as_of are pre-retirement, anchor = retirement date
        # If any values_as_of is post-retirement, anchor = latest values_as_of
        anchor_months = max(ret_months, latest_asof_months)
        anchor_year = anchor_months // 12
        anchor_month = anchor_months % 12
        if anchor_month == 0:
            anchor_month = 12
            anchor_year -= 1

        # Compute anchor age (integer, rounded down)
        anchor_age_frac = date_to_age(anchor_year, anchor_month)
        anchor_age = int(anchor_age_frac)
        # Ensure anchor_age is at least retirement_age
        anchor_age = max(anchor_age, retirement_age)

        # Store phase info for UI
        is_post_retirement = anchor_months > ret_months

        # ------------------------------------------------------------ #
        #  Build guaranteed income list, auto-indexing to anchor date
        # ------------------------------------------------------------ #
        guaranteed = []
        for g in cfg["guaranteed_income"]:
            annual = g["gross_annual"]
            idx_rate = g.get("indexation_rate", 0)

            # Index from values_as_of to anchor date
            if "values_as_of" in g and g["values_as_of"] and idx_rate > 0:
                asof_y, asof_m = parse_ym(g["values_as_of"])
                gap_months = anchor_months - ym_to_months(asof_y, asof_m)
                if gap_months > 0:
                    gap_years = gap_months / 12.0
                    annual = annual * (1 + idx_rate) ** gap_years

            guaranteed.append({
                "name": g["name"],
                "current_annual": annual,
                "indexation_rate": idx_rate,
                "start_age": g.get("start_age", retirement_age),
                "end_age": g.get("end_age"),
                "taxable": g.get("taxable", True),
            })

        # ------------------------------------------------------------ #
        #  Build DC pot balances — resolve growth rates, then apply
        #  C2: pre-retirement / stale-pot growth compounding
        # ------------------------------------------------------------ #
        dc_balances = {}
        dc_meta = {}
        for pot in cfg["dc_pots"]:
            name = pot["name"]
            balance = pot["starting_balance"]
            growth = resolve_growth_rate(pot, asset_model)
            fees = pot.get("annual_fees", 0.005)

            # C2/C3: Grow balance from values_as_of to anchor date
            if pot.get("values_as_of"):
                pot_y, pot_m = parse_ym(pot["values_as_of"])
                gap_months = anchor_months - ym_to_months(pot_y, pot_m)
                if gap_months > 0:
                    gap_years = gap_months / 12.0
                    net_growth = growth - fees
                    balance = balance * (1 + net_growth) ** gap_years

            dc_balances[name] = balance
            dc_meta[name] = {
                "growth_rate": growth,
                "annual_fees": fees,
                "tax_free_portion": pot.get("tax_free_portion", 0.25),
                "provenance": resolve_growth_provenance(pot, asset_model),
            }

        # ------------------------------------------------------------ #
        #  Build tax-free account balances — resolve growth, apply C2/C3
        # ------------------------------------------------------------ #
        tf_balances = {}
        tf_meta = {}
        for acc in cfg["tax_free_accounts"]:
            name = acc["name"]
            balance = acc["starting_balance"]
            growth = resolve_growth_rate(acc, asset_model)

            # C2/C3: Grow balance from values_as_of to anchor date (no fees)
            if acc.get("values_as_of"):
                acc_y, acc_m = parse_ym(acc["values_as_of"])
                gap_months = anchor_months - ym_to_months(acc_y, acc_m)
                if gap_months > 0:
                    gap_years = gap_months / 12.0
                    balance = balance * (1 + growth) ** gap_years

            tf_balances[name] = balance
            tf_meta[name] = {
                "growth_rate": growth,
                "provenance": resolve_growth_provenance(acc, asset_model),
            }

        # Withdrawal priority
        priority = cfg.get("withdrawal_priority", [])

        years = []
        warnings = []
        current_target = target_net
        first_shortfall_age = None
        first_pot_exhausted_age = None
        total_tax = 0.0
        total_uk_tax = 0.0

        # C3: Inflate target to anchor age if anchor > retirement_age
        if anchor_age > retirement_age:
            years_to_anchor = anchor_age - retirement_age
            current_target = target_net * (1 + cpi) ** years_to_anchor

        # ------------------------------------------------------------ #
        #  Main year-by-year loop — starts from anchor_age
        # ------------------------------------------------------------ #
        for age in range(anchor_age, end_age + 1):
            # Tax year label based on calendar year
            cal_year = anchor_year + (age - anchor_age) if is_post_retirement else 2027 + (age - retirement_age)
            tax_year = f"{cal_year}/{str(cal_year + 1)[-2:]}"

            # Inflate target (skip first year at anchor)
            if age > anchor_age:
                current_target *= (1 + cpi)

            # Calculate guaranteed income for this year
            guaranteed_total_gross = 0.0
            guaranteed_taxable_gross = 0.0
            guaranteed_detail = {}
            for g in guaranteed:
                active = age >= g["start_age"] and (g["end_age"] is None or age <= g["end_age"])
                if active:
                    amt = g["current_annual"]
                    guaranteed_detail[g["name"]] = round(amt, 2)
                    guaranteed_total_gross += amt
                    if g["taxable"]:
                        guaranteed_taxable_gross += amt
                else:
                    guaranteed_detail[g["name"]] = 0.0

            # Index guaranteed incomes for next year
            for g in guaranteed:
                g["current_annual"] *= (1 + g["indexation_rate"])

            # Tax on guaranteed income alone
            tax_on_guaranteed = self.calculate_tax(guaranteed_taxable_gross)["total"]
            net_from_guaranteed = guaranteed_total_gross - tax_on_guaranteed

            # Shortfall to fill from drawdown
            shortfall = max(0, current_target - net_from_guaranteed)

            # Grow DC pots and tax-free accounts — track P&L components
            pot_pnl = {}

            for name in dc_balances:
                meta = dc_meta[name]
                opening = dc_balances[name]
                growth_amt = opening * meta["growth_rate"]
                fee_amt = opening * meta["annual_fees"]
                dc_balances[name] = opening + growth_amt - fee_amt
                pot_pnl[name] = {
                    "opening": round(opening, 2),
                    "growth": round(growth_amt, 2),
                    "fees": round(fee_amt, 2),
                    "withdrawal": 0.0,
                    "closing": 0.0,
                    "provenance": meta["provenance"],
                }

            for name in tf_balances:
                meta = tf_meta[name]
                opening = tf_balances[name]
                growth_amt = opening * meta["growth_rate"]
                tf_balances[name] = opening + growth_amt
                pot_pnl[name] = {
                    "opening": round(opening, 2),
                    "growth": round(growth_amt, 2),
                    "fees": 0.0,
                    "withdrawal": 0.0,
                    "closing": 0.0,
                    "provenance": meta["provenance"],
                }

            # Withdraw according to priority
            dc_withdrawal_gross = 0.0
            dc_tax_free_total = 0.0
            tf_withdrawal_total = 0.0
            withdrawal_detail = {}
            remaining_shortfall = shortfall

            for source_name in priority:
                if remaining_shortfall <= 0:
                    break

                if source_name in dc_balances:
                    meta = dc_meta[source_name]
                    tfp = meta["tax_free_portion"]
                    gross_needed = self.gross_up(remaining_shortfall,
                                                guaranteed_taxable_gross + (dc_withdrawal_gross - dc_tax_free_total),
                                                tfp)
                    gross_needed = min(gross_needed, dc_balances[source_name])
                    dc_balances[source_name] -= gross_needed
                    tax_free_part = gross_needed * tfp
                    dc_withdrawal_gross += gross_needed
                    dc_tax_free_total += tax_free_part
                    withdrawal_detail[source_name] = round(gross_needed, 2)
                    if source_name in pot_pnl:
                        pot_pnl[source_name]["withdrawal"] = round(gross_needed, 2)

                    taxable_part = gross_needed - tax_free_part
                    total_taxable = guaranteed_taxable_gross + (dc_withdrawal_gross - dc_tax_free_total)
                    tax = self.calculate_tax(total_taxable)["total"]
                    net_so_far = guaranteed_total_gross + dc_withdrawal_gross + tf_withdrawal_total - tax
                    remaining_shortfall = max(0, current_target - net_so_far)

                elif source_name in tf_balances:
                    withdraw = min(remaining_shortfall, tf_balances[source_name])
                    tf_balances[source_name] -= withdraw
                    tf_withdrawal_total += withdraw
                    withdrawal_detail[source_name] = round(withdraw, 2)
                    if source_name in pot_pnl:
                        pot_pnl[source_name]["withdrawal"] = round(withdraw, 2)
                    remaining_shortfall -= withdraw

            # Fill closing balances in pot P&L
            for name in dc_balances:
                if name in pot_pnl:
                    pot_pnl[name]["closing"] = round(dc_balances[name], 2)
            for name in tf_balances:
                if name in pot_pnl:
                    pot_pnl[name]["closing"] = round(tf_balances[name], 2)

            # Final tax calculation — store full breakdowns
            total_taxable_income = guaranteed_taxable_gross + (dc_withdrawal_gross - dc_tax_free_total)
            iom_tax_result = self.calculate_tax(total_taxable_income)
            uk_tax_result = self.calculate_uk_tax(total_taxable_income)
            tax_due = iom_tax_result["total"]
            uk_tax_due = uk_tax_result["total"]
            total_tax += tax_due
            total_uk_tax += uk_tax_due

            net_income = guaranteed_total_gross + dc_withdrawal_gross + tf_withdrawal_total - tax_due
            has_shortfall = net_income < current_target - 1

            if has_shortfall and first_shortfall_age is None:
                first_shortfall_age = age

            # Check pot exhaustion
            all_pots = {**dc_balances, **tf_balances}
            for pname, bal in all_pots.items():
                if bal < 1 and first_pot_exhausted_age is None:
                    first_pot_exhausted_age = age
                    warnings.append(f"{pname} exhausted at age {age}")

            # Total capital
            total_capital = sum(dc_balances.values()) + sum(tf_balances.values())

            # Build year result
            yr = {
                "age": age,
                "tax_year": tax_year,
                "target_net": round(current_target, 2),
                "guaranteed_income": guaranteed_detail,
                "guaranteed_total": round(guaranteed_total_gross, 2),
                "dc_withdrawal_gross": round(dc_withdrawal_gross, 2),
                "dc_tax_free_portion": round(dc_tax_free_total, 2),
                "tf_withdrawal": round(tf_withdrawal_total, 2),
                "withdrawal_detail": withdrawal_detail,
                "total_taxable_income": round(total_taxable_income, 2),
                "tax_due": round(tax_due, 2),
                "uk_tax_due": round(uk_tax_due, 2),
                "iom_tax_breakdown": iom_tax_result,
                "uk_tax_breakdown": uk_tax_result,
                "net_income_achieved": round(net_income, 2),
                "shortfall": has_shortfall,
                "pot_balances": {n: round(b, 2) for n, b in dc_balances.items()},
                "tf_balances": {n: round(b, 2) for n, b in tf_balances.items()},
                "total_capital": round(total_capital, 2),
                "pot_pnl": pot_pnl,
            }
            years.append(yr)

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
        }

        return {"years": years, "summary": summary, "warnings": warnings}

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
