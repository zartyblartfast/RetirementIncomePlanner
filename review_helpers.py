"""Annual Review helpers — load/save reviews.json, compute review state."""
import os
import json
from datetime import date, datetime

REVIEWS_PATH = os.path.join(os.path.dirname(__file__), "reviews.json")

# ------------------------------------------------------------------ #
#  Load / Save
# ------------------------------------------------------------------ #

def load_reviews():
    """Load reviews from disk, returning empty structure if not found."""
    if os.path.exists(REVIEWS_PATH):
        with open(REVIEWS_PATH, "r") as f:
            return json.load(f)
    return {"baseline": None, "reviews": []}


def save_reviews(data):
    """Persist reviews to disk."""
    with open(REVIEWS_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ------------------------------------------------------------------ #
#  Review state detection
# ------------------------------------------------------------------ #

def compute_review_state(cfg, reviews_data=None):
    """Determine the review page state (A/B/C/D) and related metadata.

    States:
      A = pre_retirement  (current_age < retirement_age, no reviews)
      B = bootstrap_due   (current_age >= retirement_age, no reviews)
      C = between_reviews  (reviews exist, next review not yet due)
      D = review_due       (reviews exist, next review due or overdue)

    Returns dict with keys:
      state, retirement_date, current_age, has_reviews,
      last_review, next_review_date, days_until_review, overdue_days,
      countdown_text
    """
    if reviews_data is None:
        reviews_data = load_reviews()

    today = date.today()

    # Parse retirement date
    ret_str = cfg["personal"].get("retirement_date", "2027-04")
    try:
        ret_year, ret_month = int(ret_str[:4]), int(ret_str[5:7])
        retirement_date = date(ret_year, ret_month, 1)
    except (ValueError, IndexError):
        retirement_date = date(2027, 4, 1)

    # Parse DOB to compute current age
    dob_str = cfg["personal"].get("date_of_birth", "1958-07")
    try:
        dob_year, dob_month = int(dob_str[:4]), int(dob_str[5:7])
        dob_date = date(dob_year, dob_month, 1)
    except (ValueError, IndexError):
        dob_date = date(1958, 7, 1)

    # Current age in whole years
    current_age = (today.year - dob_date.year) - (1 if (today.month, today.day) < (dob_date.month, 1) else 0)
    retirement_age = cfg["personal"].get("retirement_age", 68)

    reviews = reviews_data.get("reviews", [])
    has_reviews = len(reviews) > 0
    last_review = reviews[-1] if has_reviews else None

    # Compute next review date
    next_review_date = None
    days_until_review = None
    overdue_days = None

    if has_reviews:
        last_date_str = last_review["review_date"]
        try:
            last_dt = datetime.strptime(last_date_str, "%Y-%m-%d").date()
            next_review_date = date(last_dt.year + 1, last_dt.month, last_dt.day)
        except (ValueError, TypeError):
            next_review_date = date(today.year + 1, retirement_date.month, 1)
        delta = (next_review_date - today).days
        if delta >= 0:
            days_until_review = delta
        else:
            overdue_days = abs(delta)

    # Countdown text for pre-retirement
    countdown_text = ""
    if not has_reviews and current_age < retirement_age:
        months_to_go = (retirement_date.year - today.year) * 12 + (retirement_date.month - today.month)
        years_to_go = months_to_go // 12
        rem_months = months_to_go % 12
        if years_to_go > 0 and rem_months > 0:
            countdown_text = f"{years_to_go} year{'s' if years_to_go != 1 else ''} and {rem_months} month{'s' if rem_months != 1 else ''}"
        elif years_to_go > 0:
            countdown_text = f"{years_to_go} year{'s' if years_to_go != 1 else ''}"
        else:
            countdown_text = f"{rem_months} month{'s' if rem_months != 1 else ''}"

    # Determine state
    if not has_reviews:
        if current_age >= retirement_age:
            state = "bootstrap_due"
        else:
            state = "pre_retirement"
    else:
        if overdue_days is not None:
            state = "review_due"
        else:
            state = "between_reviews"

    return {
        "state": state,
        "retirement_date": retirement_date.isoformat(),
        "retirement_date_display": retirement_date.strftime("%d %B %Y"),
        "current_age": current_age,
        "retirement_age": retirement_age,
        "has_reviews": has_reviews,
        "review_count": len(reviews),
        "last_review": last_review,
        "next_review_date": next_review_date.isoformat() if next_review_date else None,
        "next_review_date_display": next_review_date.strftime("%d %B %Y") if next_review_date else None,
        "days_until_review": days_until_review,
        "overdue_days": overdue_days,
        "countdown_text": countdown_text,
    }


# ------------------------------------------------------------------ #
#  Helpers for building review records
# ------------------------------------------------------------------ #

def build_balances_snapshot(cfg):
    """Extract current pot/ISA balances from config into review format."""
    balances = {}
    for pot in cfg.get("dc_pots", []):
        balances[pot["name"]] = {
            "balance": pot.get("starting_balance", 0),
            "as_of": pot.get("values_as_of", ""),
            "type": "dc_pot",
        }
    for acc in cfg.get("tax_free_accounts", []):
        balances[acc["name"]] = {
            "balance": acc.get("starting_balance", 0),
            "as_of": acc.get("values_as_of", ""),
            "type": "tax_free",
        }
    return balances


def apply_review_balances_to_config(cfg, balances, review_date):
    """Write review balances back to config (Settings sync)."""
    for pot in cfg.get("dc_pots", []):
        if pot["name"] in balances:
            pot["starting_balance"] = balances[pot["name"]]["balance"]
            pot["values_as_of"] = review_date
    for acc in cfg.get("tax_free_accounts", []):
        if acc["name"] in balances:
            acc["starting_balance"] = balances[acc["name"]]["balance"]
            acc["values_as_of"] = review_date
    return cfg


def build_recommendation_from_result(result, cfg):
    """Extract recommendation data from a projection result."""
    summary = result.get("summary", {})
    strategy_id = cfg.get("drawdown_strategy", "fixed_target")
    strategy_params = cfg.get("drawdown_strategy_params", {})

    # Get Year 1 withdrawal details from the first year
    # withdrawal_detail contains NET amounts per pot (DC and ISA)
    years = result.get("years", [])
    withdrawal_plan = []
    if years:
        yr1 = years[0]
        wd_detail = yr1.get("withdrawal_detail", {})
        for pot_name in cfg.get("withdrawal_priority", []):
            if pot_name in wd_detail and wd_detail[pot_name] > 0:
                withdrawal_plan.append({
                    "source": pot_name,
                    "net_amount": round(wd_detail[pot_name], 2),
                })

    # Total net income = Year 1's net_income_achieved (includes guaranteed + pot withdrawals)
    yr1_income = years[0]["net_income_achieved"] if years else 0

    return {
        "strategy": strategy_id,
        "strategy_params": {k: v for k, v in strategy_params.items()},
        "total_net_income": round(yr1_income, 2),
        "withdrawal_plan": withdrawal_plan,
        "sustainable": summary.get("first_shortfall_age") is None,
        "end_age": cfg["personal"].get("end_age", 90),
        "first_shortfall_age": summary.get("first_shortfall_age"),
    }


def build_initial_strategy_state(actual_drawdown, strategy_id, cfg):
    """Build the initial_strategy_state dict for stateful strategies.

    This seeds the strategy's internal state from the actual prior-year
    drawdown so guardrails/clamping work correctly on the first projected year.
    """
    if not actual_drawdown:
        return None

    # Sum total net drawn from pots (not guaranteed income)
    total_pot_net = sum(item.get("net_amount", 0) for item in actual_drawdown)

    if strategy_id == "guyton_klinger":
        # GK needs current_target and prev_gross
        # Estimate gross from net using a rough tax factor
        params = cfg.get("drawdown_strategy_params", {})
        return {
            "current_target": total_pot_net,
            "starting_rate": params.get("upper_guardrail_pct", 5.5) / 100.0,
            "prev_gross": total_pot_net * 1.1,  # rough estimate
        }
    elif strategy_id == "vanguard_dynamic":
        return {
            "current_target": total_pot_net,
        }
    elif strategy_id == "arva_guardrails":
        return {
            "prev_withdrawal": total_pot_net,
        }
    # Stateless strategies don't need seeding
    return None
