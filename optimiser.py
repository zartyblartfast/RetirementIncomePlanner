#!/usr/bin/env python3
"""
Optimiser Module V2.0
=====================
Four optimisation functions for the Retirement Income Planner.
Supports dynamic income streams: guaranteed pensions, DC pots, and tax-free accounts.

Q1: Best Drawdown Order       - maximise remaining capital
Q2: Maximum Sustainable Income - find spending ceiling
Q3: Longevity Headroom        - max age for target income
Q4: Tax-Efficient Drawdown    - minimise lifetime tax

Usage:
    from optimiser import find_best_drawdown_order, ...
    result = find_best_drawdown_order(config)
"""

import copy
import itertools
from retirement_engine import RetirementEngine


def _get_all_drawable_sources(config: dict) -> list:
    """Get all drawable source names from dc_pots and tax_free_accounts."""
    sources = []
    for pot in config.get('dc_pots', []):
        sources.append(pot['name'])
    for acct in config.get('tax_free_accounts', []):
        sources.append(acct['name'])
    return sources


# =====================================================================
# Q1: Best Drawdown Order
# =====================================================================
def find_best_drawdown_order(base_config: dict) -> dict:
    """
    Test all permutations of withdrawal priority order.
    Rank by remaining total capital at end age.

    Returns:
        {
            'ranked': [sorted list of {strategy_name, priority, remaining_capital, ...}],
            'best': {best strategy},
            'question': str,
        }
    """
    all_sources = _get_all_drawable_sources(base_config)

    strategies = []

    # Test all permutations of the withdrawal order
    for perm in itertools.permutations(all_sources):
        perm_list = list(perm)
        label = ' \u2192 '.join(perm_list)

        cfg = copy.deepcopy(base_config)
        cfg['withdrawal_priority'] = perm_list

        engine = RetirementEngine(cfg)
        result = engine.run_projection()

        strategies.append({
            'name': label,
            'strategy_name': label,
            'priority': perm_list,
            'remaining_capital': result['summary']['remaining_capital'],
            'total_tax': result['summary']['total_tax_paid'],
            'sustainable': result['summary']['sustainable'],
            'first_shortfall_age': result['summary']['first_shortfall_age'],
            'result': result,
        })

    # Sort by remaining capital (highest first), sustainable first
    strategies.sort(key=lambda s: (
        0 if s['sustainable'] else 1,
        -s['remaining_capital']
    ))

    result_dict = {
        'ranked': strategies,
        'best': strategies[0] if strategies else None,
        'question': 'What is the best drawdown order to maximise remaining capital?',
    }
    result_dict['narrative'] = _generate_q1_narrative(result_dict, base_config)
    return result_dict


# =====================================================================
# Q2: Maximum Sustainable Income
# =====================================================================
def find_max_sustainable_income(base_config: dict) -> dict:
    """
    Binary search on target_net_income to find the highest value where
    the plan is still sustainable (no shortfall in any year).

    Tolerance: 100

    Returns:
        {
            'max_income': float,
            'current_income': float,
            'headroom_amount': float,
            'headroom_pct': float,
            'projection': result dict at max income,
            'current_projection': result dict at current income,
            'question': str,
        }
    """
    current_income = base_config['target_income']['net_annual']
    tolerance = 100.0

    # Run current projection for comparison
    engine_current = RetirementEngine(copy.deepcopy(base_config))
    current_result = engine_current.run_projection()

    def is_sustainable(income: float) -> bool:
        cfg = copy.deepcopy(base_config)
        cfg['target_income']['net_annual'] = income
        engine = RetirementEngine(cfg)
        result = engine.run_projection()
        return result['summary']['sustainable']

    # Find upper bound
    lo = 0.0
    hi = current_income * 3.0

    while is_sustainable(hi):
        hi *= 1.5
        if hi > current_income * 20:
            break

    # Binary search
    for _ in range(50):
        mid = (lo + hi) / 2.0
        if hi - lo < tolerance:
            break
        if is_sustainable(mid):
            lo = mid
        else:
            hi = mid

    max_income = round(lo, 0)

    # Run projection at max income
    cfg_max = copy.deepcopy(base_config)
    cfg_max['target_income']['net_annual'] = max_income
    engine_max = RetirementEngine(cfg_max)
    max_result = engine_max.run_projection()

    headroom = max_income - current_income
    headroom_pct = (headroom / current_income * 100) if current_income > 0 else 0

    result_dict = {
        'max_income': max_income,
        'current_income': current_income,
        'headroom_amount': round(headroom, 0),
        'headroom_pct': round(headroom_pct, 1),
        'projection': max_result,
        'current_projection': current_result,
        'question': 'What is the maximum sustainable annual net income?',
    }
    result_dict['narrative'] = _generate_q2_narrative(result_dict, base_config)
    return result_dict


# =====================================================================
# Q3: Longevity Headroom
# =====================================================================
def find_max_sustainable_age(base_config: dict) -> dict:
    """
    Increment end_age from current setting upward (year by year) to find
    the latest age where the plan is still sustainable.

    Returns:
        {
            'max_age': int,
            'current_end_age': int,
            'extra_years': int,
            'projection': result dict at max age,
            'current_projection': result dict at current end age,
            'question': str,
        }
    """
    current_end_age = base_config['personal']['end_age']

    # Run current projection
    engine_current = RetirementEngine(copy.deepcopy(base_config))
    current_result = engine_current.run_projection()

    # If current plan isn't sustainable, search downward
    if not current_result['summary']['sustainable']:
        max_age = current_end_age
        for age in range(current_end_age - 1, base_config['personal']['retirement_age'], -1):
            cfg = copy.deepcopy(base_config)
            cfg['personal']['end_age'] = age
            engine = RetirementEngine(cfg)
            result = engine.run_projection()
            if result['summary']['sustainable']:
                max_age = age
                break
        else:
            max_age = base_config['personal']['retirement_age']

        cfg_max = copy.deepcopy(base_config)
        cfg_max['personal']['end_age'] = max_age
        engine_max = RetirementEngine(cfg_max)
        max_result = engine_max.run_projection()

        result_dict = {
            'max_age': max_age,
            'current_end_age': current_end_age,
            'extra_years': max_age - current_end_age,
            'projection': max_result,
            'current_projection': current_result,
            'question': 'What is the maximum age the plan can sustain the target income?',
        }
        result_dict['narrative'] = _generate_q3_narrative(result_dict, base_config)
        return result_dict

    # Search upward
    max_age = current_end_age
    last_sustainable_result = current_result

    for age in range(current_end_age + 1, 120):
        cfg = copy.deepcopy(base_config)
        cfg['personal']['end_age'] = age
        engine = RetirementEngine(cfg)
        result = engine.run_projection()

        if result['summary']['sustainable']:
            max_age = age
            last_sustainable_result = result
        else:
            break

    result_dict = {
        'max_age': max_age,
        'current_end_age': current_end_age,
        'extra_years': max_age - current_end_age,
        'projection': last_sustainable_result,
        'current_projection': current_result,
        'question': 'What is the maximum age the plan can sustain the target income?',
    }
    result_dict['narrative'] = _generate_q3_narrative(result_dict, base_config)
    return result_dict


# =====================================================================
# Q4: Tax-Efficient Drawdown
# =====================================================================
def find_tax_efficient_strategy(base_config: dict) -> dict:
    """
    Compare drawdown strategies optimised for tax efficiency.
    Tests all permutations and named strategies, ranked by total lifetime tax.

    Returns:
        {
            'ranked': [sorted list by total tax],
            'best': lowest-tax strategy,
            'current_tax': total tax under current config,
            'question': str,
        }
    """
    all_sources = _get_all_drawable_sources(base_config)
    dc_names = [pot['name'] for pot in base_config.get('dc_pots', [])]
    tf_names = [acct['name'] for acct in base_config.get('tax_free_accounts', [])]

    # Run current config for comparison
    engine_current = RetirementEngine(copy.deepcopy(base_config))
    current_result = engine_current.run_projection()
    current_tax = current_result['summary']['total_tax_paid']

    strategies = []

    # Test all permutations using actual pot/account names
    for perm in itertools.permutations(all_sources):
        perm_list = list(perm)
        name = " → ".join(perm_list)
        order = perm_list

        cfg = copy.deepcopy(base_config)
        cfg['withdrawal_priority'] = order

        engine = RetirementEngine(cfg)
        result = engine.run_projection()

        strategies.append({
            'name': name,
            'strategy_name': name,
            'priority': order,
            'total_tax': result['summary']['total_tax_paid'],
            'avg_tax_rate': result['summary']['avg_effective_tax_rate'],
            'remaining_capital': result['summary']['remaining_capital'],
            'sustainable': result['summary']['sustainable'],
            'tax_saving_vs_current': round(current_tax - result['summary']['total_tax_paid'], 2),
            'tax_saving': round(current_tax - result['summary']['total_tax_paid'], 2),
            'result': result,
        })

    # Sort by total tax (lowest first), sustainable strategies preferred
    strategies.sort(key=lambda s: (
        0 if s['sustainable'] else 1,
        s['total_tax']
    ))

    result_dict = {
        'ranked': strategies,
        'best': strategies[0] if strategies else None,
        'current_tax': current_tax,
        'question': 'Which drawdown strategy minimises lifetime tax?',
    }
    result_dict['narrative'] = _generate_q4_narrative(result_dict, base_config)
    return result_dict




# =====================================================================
# Narrative Helpers
# =====================================================================
def _analyse_strategy_details(result: dict, config: dict) -> dict:
    """Extract key facts from a strategy's year-by-year projection."""
    years = result.get('years', [])
    if not years:
        return {}

    personal_allowance = config['tax']['personal_allowance']

    # Pot depletion ages
    pot_depletion = {}
    for yr in years:
        all_bals = {**yr.get('pot_balances', {}), **yr.get('tf_balances', {})}
        for pname, bal in all_bals.items():
            if bal < 1 and pname not in pot_depletion:
                pot_depletion[pname] = yr['age']

    # Tax-free DC income in first 5 years and total
    early_tax_free = sum(yr.get('dc_tax_free_portion', 0) for yr in years[:5])
    total_tax_free_dc = sum(yr.get('dc_tax_free_portion', 0) for yr in years)

    # Tax in early vs late halves
    mid = len(years) // 2
    early_tax = sum(yr['tax_due'] for yr in years[:mid])
    late_tax = sum(yr['tax_due'] for yr in years[mid:])

    # First pot drawn (source with withdrawals in year 1)
    first_drawn = None
    if years[0].get('withdrawal_detail'):
        for source, amt in years[0]['withdrawal_detail'].items():
            if amt > 0:
                first_drawn = source
                break

    # Year guaranteed income exceeds personal allowance
    guaranteed_exceeds_pa_age = None
    for yr in years:
        if yr['guaranteed_total'] > personal_allowance and guaranteed_exceeds_pa_age is None:
            guaranteed_exceeds_pa_age = yr['age']

    # Find the IoM lower-rate band ceiling
    bands = config['tax'].get('bands', [])
    lower_band_ceiling = personal_allowance
    for band in bands:
        if band.get('width') is not None:
            lower_band_ceiling += band['width']
            break

    # Year guaranteed income alone pushes into higher rate
    guaranteed_exceeds_lower_age = None
    for yr in years:
        if yr['guaranteed_total'] > lower_band_ceiling and guaranteed_exceeds_lower_age is None:
            guaranteed_exceeds_lower_age = yr['age']

    # Guaranteed income in first and last year
    guaranteed_first = years[0]['guaranteed_total']
    guaranteed_final = years[-1]['guaranteed_total']
    target_final = years[-1]['target_net']
    guaranteed_coverage_pct = (guaranteed_final / target_final * 100) if target_final > 0 else 0

    return {
        'pot_depletion': pot_depletion,
        'early_tax_free': round(early_tax_free, 0),
        'total_tax_free_dc': round(total_tax_free_dc, 0),
        'early_tax': round(early_tax, 0),
        'late_tax': round(late_tax, 0),
        'first_drawn': first_drawn,
        'guaranteed_exceeds_pa_age': guaranteed_exceeds_pa_age,
        'guaranteed_exceeds_lower_age': guaranteed_exceeds_lower_age,
        'lower_band_ceiling': lower_band_ceiling,
        'guaranteed_first': round(guaranteed_first, 0),
        'guaranteed_final': round(guaranteed_final, 0),
        'target_final': round(target_final, 0),
        'guaranteed_coverage_pct': round(guaranteed_coverage_pct, 1),
    }


def _compare_two_strategies(best_result: dict, runner_result: dict, config: dict) -> dict:
    """Compare two strategy projections and identify key differences."""
    best_years = best_result.get('years', [])
    runner_years = runner_result.get('years', [])
    if not best_years or not runner_years:
        return {}

    tax_diffs = []
    for b_yr, r_yr in zip(best_years, runner_years):
        diff = r_yr['tax_due'] - b_yr['tax_due']
        tax_diffs.append({'age': b_yr['age'], 'diff': diff})

    years_best_saves = [d for d in tax_diffs if d['diff'] > 50]
    total_tax_saving = sum(d['diff'] for d in tax_diffs)

    capital_diffs = []
    for b_yr, r_yr in zip(best_years, runner_years):
        diff = b_yr['total_capital'] - r_yr['total_capital']
        capital_diffs.append({'age': b_yr['age'], 'diff': diff})

    max_capital_gap = max(capital_diffs, key=lambda d: abs(d['diff']))

    return {
        'years_best_saves_tax': len(years_best_saves),
        'total_tax_saving': round(total_tax_saving, 0),
        'max_capital_gap_age': max_capital_gap['age'],
        'max_capital_gap_amount': round(max_capital_gap['diff'], 0),
    }


def _build_why_bullets(best: dict, runner: dict, config: dict) -> list:
    """Build key-fact bullets explaining WHY the best strategy outperforms."""
    bullets = []
    best_details = _analyse_strategy_details(best['result'], config)
    if not best_details:
        return bullets

    runner_details = _analyse_strategy_details(runner['result'], config) if runner else {}
    comparison = _compare_two_strategies(best['result'], runner['result'], config) if runner else {}

    # Bullet 1: Tax-free timing
    first_drawn = best_details.get('first_drawn')
    if first_drawn:
        first_pot_balance = None
        for pot in config.get('dc_pots', []):
            if pot['name'] == first_drawn:
                first_pot_balance = pot['starting_balance']
                break
        if first_pot_balance:
            tax_free_amount = first_pot_balance * 0.25
            bullets.append(
                "Drawing {} (\u00a3{:,.0f}) first unlocks \u00a3{:,.0f} of tax-free income "
                "(25% entitlement), reducing the taxable portion of each withdrawal.".format(
                    first_drawn, first_pot_balance, tax_free_amount))

    # Bullet 2: Tax band interaction
    lower_ceiling = best_details.get('lower_band_ceiling', 0)
    guar_first = best_details.get('guaranteed_first', 0)
    guar_final = best_details.get('guaranteed_final', 0)
    exceeds_lower_age = best_details.get('guaranteed_exceeds_lower_age')
    if exceeds_lower_age and guar_first < lower_ceiling:
        bullets.append(
            "In the early years, your guaranteed income "
            "(\u00a3{:,.0f}) sits within the lower tax bands, "
            "so DC withdrawals start at 10%. By age {}, "
            "guaranteed income alone exceeds the \u00a3{:,.0f} "
            "lower-rate ceiling, pushing all DC withdrawals into the 20% band. "
            "Drawing more from DC pots in these earlier, lower-tax years is more efficient.".format(
                guar_first, exceeds_lower_age, lower_ceiling))
    elif guar_first >= lower_ceiling:
        bullets.append(
            "Your guaranteed income (\u00a3{:,.0f} rising to "
            "\u00a3{:,.0f}) already exceeds the "
            "\u00a3{:,.0f} lower-rate ceiling from day one, "
            "so all DC withdrawals are taxed at 20%. The winning order "
            "minimises the total amount that needs to be withdrawn by "
            "using tax-free entitlements from the largest pot first.".format(
                guar_first, guar_final, lower_ceiling))

    # Bullet 3: Pot depletion comparison
    if runner_details:
        best_depleted = best_details.get('pot_depletion', {})
        runner_depleted = runner_details.get('pot_depletion', {})
        runner_only = {k: v for k, v in runner_depleted.items() if k not in best_depleted}
        if runner_only:
            for pname, age in runner_only.items():
                bullets.append(
                    "The winning order keeps {} invested throughout the plan, "
                    "while the next-best order exhausts it at age {}. "
                    "Keeping capital invested longer generates more compound growth.".format(
                        pname, age))
        elif best_depleted and runner_depleted:
            for pname in best_depleted:
                if pname in runner_depleted and best_depleted[pname] > runner_depleted[pname]:
                    bullets.append(
                        "{} lasts until age {} "
                        "in the best order vs age {} "
                        "in the runner-up, providing {} "
                        "extra years of investment growth.".format(
                            pname, best_depleted[pname],
                            runner_depleted[pname],
                            best_depleted[pname] - runner_depleted[pname]))

    # Bullet 4: Lifetime tax saving
    if comparison and comparison.get('total_tax_saving', 0) > 0:
        bullets.append(
            "Over the full plan, this order saves "
            "\u00a3{:,.0f} in lifetime tax "
            "compared to the next-best alternative, spread across "
            "{} years of lower annual tax bills.".format(
                comparison['total_tax_saving'],
                comparison['years_best_saves_tax']))

    return bullets


# =====================================================================
# Narrative Generation
# =====================================================================
def _generate_q1_narrative(result: dict, config: dict) -> dict:
    """Generate plain-English and advisor narratives for Q1 (Best Drawdown Order)."""
    best = result.get('best')
    ranked = result.get('ranked', [])
    if not best:
        return {'summary': 'No drawable sources configured.', 'advisor': ''}

    sustainable_count = sum(1 for s in ranked if s['sustainable'])
    total_count = len(ranked)
    best_name = best['strategy_name']
    best_capital = best['remaining_capital']

    sustainable_strategies = [s for s in ranked if s['sustainable']]
    worst_sustainable = sustainable_strategies[-1] if len(sustainable_strategies) > 1 else None

    summary = "Drawing from {} is the best order, ".format(best_name)
    summary += "leaving \u00a3{:,.0f} at the end of your plan. ".format(best_capital)
    if sustainable_count == total_count:
        summary += "All {} possible orders meet your income target every year.".format(total_count)
    elif sustainable_count > 0:
        summary += "Only {} of {} possible orders meet your income target every year \u2014 the rest run short.".format(sustainable_count, total_count)
    else:
        summary += "No withdrawal order fully sustains your target income."

    # Advisor detail
    advisor = "<p>Of {} permutations tested, {} are sustainable to age {}. ".format(total_count, sustainable_count, config['personal']['end_age'])
    if worst_sustainable:
        capital_diff = best_capital - worst_sustainable['remaining_capital']
        advisor += "The best order leaves \u00a3{:,.0f} more than the worst sustainable order ({}). ".format(capital_diff, worst_sustainable['strategy_name'])
    advisor += "The winning strategy's total lifetime tax is \u00a3{:,.0f}. ".format(best['total_tax'])
    if not best['sustainable']:
        advisor += "<em>Note: the top-ranked strategy is not fully sustainable — first shortfall at age {}.</em> ".format(best['first_shortfall_age'])

    # Add 'why' bullets
    runner = sustainable_strategies[1] if len(sustainable_strategies) > 1 else (ranked[1] if len(ranked) > 1 else None)
    why_bullets = _build_why_bullets(best, runner, config) if runner else []
    if why_bullets:
        advisor += "</p><p class='fw-bold mt-2 mb-1'>Why this order wins:</p><ol class='small'>"
        for i, bullet in enumerate(why_bullets, 1):
            advisor += "<li>{}</li>".format(bullet)
        advisor += "</ol>"
    else:
        advisor += "</p>"

    return {'summary': summary, 'advisor': advisor}


def _generate_q2_narrative(result: dict, config: dict) -> dict:
    """Generate plain-English and advisor narratives for Q2 (Max Sustainable Income)."""
    current = result['current_income']
    maximum = result['max_income']
    headroom = result['headroom_amount']
    headroom_pct = result['headroom_pct']
    end_age = config['personal']['end_age']

    summary = "You could increase your annual income from \u00a3{:,.0f} to \u00a3{:,.0f} ".format(current, maximum)
    summary += "and still have enough to last to age {}. ".format(end_age)
    summary += "That's a \u00a3{:,.0f} buffer ({:.1f}%) above your current target.".format(headroom, headroom_pct)

    details = _analyse_strategy_details(result['projection'], config)
    pot_depletion = details.get('pot_depletion', {})
    guar_coverage = details.get('guaranteed_coverage_pct', 0)
    guar_final = details.get('guaranteed_final', 0)
    target_final = details.get('target_final', 0)

    advisor = "<p>Binary search across income levels (±£100 tolerance) identifies £{:,.0f} as the ceiling.</p>".format(maximum)
    advisor += "<p class='fw-bold mt-2 mb-1'>Why this is the ceiling:</p><ol class='small'>"
    why_points = []
    if pot_depletion:
        depletion_items = sorted(pot_depletion.items(), key=lambda x: x[1])
        depletion_str = ", ".join("{} at age {}".format(name, age) for name, age in depletion_items)
        why_points.append("At \u00a3{:,.0f}, your pots deplete in this order: {}.".format(maximum, depletion_str))
    if guar_final > 0 and target_final > 0:
        gap = target_final - guar_final
        why_points.append(
            "In the final year, your inflation-adjusted target reaches \u00a3{:,.0f} "
            "but guaranteed income only covers \u00a3{:,.0f} ({:.0f}%). "
            "The \u00a3{:,.0f} gap must come from remaining pots \u2014 any higher income exhausts them before age {}.".format(
                target_final, guar_final, guar_coverage, gap, end_age))
    if headroom > 0:
        why_points.append(
            "Your current \u00a3{:,.0f} target leaves a {:.1f}% safety margin. "
            "This buffer protects against unexpectedly low investment returns or higher-than-assumed inflation.".format(
                current, headroom_pct))
    for i, point in enumerate(why_points, 1):
        advisor += "<li>{}</li>".format(point)
    advisor += "</ol>"
    return {'summary': summary, 'advisor': advisor}


def _generate_q3_narrative(result: dict, config: dict) -> dict:
    """Generate plain-English and advisor narratives for Q3 (Longevity Headroom)."""
    current_end = result['current_end_age']
    max_age = result['max_age']
    extra = result['extra_years']
    target = config['target_income']['net_annual']

    if extra > 0:
        summary = "Your plan can sustain \u00a3{:,.0f}/year until age {} \u2014 ".format(target, max_age)
        summary += "that's {} extra years beyond your planned end age of {}.".format(extra, current_end)
    elif extra == 0:
        summary = "Your plan just about lasts to age {} with no extra headroom. ".format(current_end)
        summary += "Consider reducing your target income or increasing contributions to build a buffer."
    else:
        summary = "Your plan falls short \u2014 it can only sustain your target income to age {}, ".format(max_age)
        summary += "which is {} years before your planned end age of {}.".format(abs(extra), current_end)

    details = _analyse_strategy_details(result['projection'], config)
    pot_depletion = details.get('pot_depletion', {})
    guar_final = details.get('guaranteed_final', 0)
    target_final = details.get('target_final', 0)

    advisor = "<p>Projection extended year-by-year from age {}.</p>".format(current_end)
    advisor += "<p class='fw-bold mt-2 mb-1'>Why the plan reaches its limit at age {}:</p><ol class='small'>".format(max_age)
    why_points = []
    if pot_depletion:
        depletion_items = sorted(pot_depletion.items(), key=lambda x: x[1])
        depletion_str = ", ".join("{} at age {}".format(name, age) for name, age in depletion_items)
        why_points.append("Pots deplete in sequence: {}. Once all drawable capital is gone, you rely entirely on guaranteed income.".format(depletion_str))
    if guar_final > 0 and target_final > 0:
        gap = target_final - guar_final
        if gap > 0:
            why_points.append(
                "At age {}, your inflation-adjusted target is \u00a3{:,.0f} "
                "but guaranteed pensions provide \u00a3{:,.0f} \u2014 a \u00a3{:,.0f} shortfall. "
                "Beyond this age, there is no remaining capital to bridge the gap.".format(
                    max_age, target_final, guar_final, gap))
        else:
            why_points.append(
                "By age {}, guaranteed income (\u00a3{:,.0f}) nearly matches "
                "the inflation-adjusted target (\u00a3{:,.0f}), so the plan is close to self-sustaining.".format(
                    max_age, guar_final, target_final))
    cpi = config['target_income'].get('cpi_rate', 0.03)
    if extra > 0:
        cost_per_extra_year = target * (1 + cpi) ** extra
        why_points.append(
            "Each additional year of longevity beyond age {} costs approximately "
            "\u00a3{:,.0f} in inflation-adjusted terms, "
            "funded by drawing down remaining capital.".format(current_end, cost_per_extra_year))
    for i, point in enumerate(why_points, 1):
        advisor += "<li>{}</li>".format(point)
    advisor += "</ol>"
    return {'summary': summary, 'advisor': advisor}


def _generate_q4_narrative(result: dict, config: dict) -> dict:
    """Generate plain-English and advisor narratives for Q4 (Tax-Efficient Drawdown)."""
    ranked = result.get('ranked', [])
    best = result.get('best')
    current_tax = result.get('current_tax', 0)
    if not best:
        return {'summary': 'No drawable sources configured.', 'advisor': ''}

    best_tax = best['total_tax']
    saving = current_tax - best_tax
    best_name = best['name']
    worst = max(ranked, key=lambda s: s['total_tax']) if ranked else best
    tax_spread = abs(worst['total_tax'] - best_tax)

    if saving > 0:
        summary = "Switching to {} would save you \u00a3{:,.0f} in lifetime tax ".format(best_name, saving)
        summary += "compared to your current withdrawal order."
    else:
        summary = "Your current withdrawal order is already the most tax-efficient \u2014 "
        summary += "total lifetime tax of \u00a3{:,.0f}.".format(current_tax)

    if not best['sustainable']:
        summary += " However, this strategy doesn't sustain your income target every year."

    advisor = "<p>Lifetime tax across all {} permutations ranges from £{:,.0f} to £{:,.0f} ".format(len(ranked), best_tax, worst['total_tax'])
    advisor += "(spread: \u00a3{:,.0f}). ".format(tax_spread)
    advisor += "The winning strategy ({}) achieves an average effective tax rate of {:.1f}%.</p>".format(best_name, best['avg_tax_rate'])

    sustainable_strategies = [s for s in ranked if s['sustainable']]
    runner = sustainable_strategies[1] if len(sustainable_strategies) > 1 else (ranked[1] if len(ranked) > 1 else None)
    why_bullets = _build_why_bullets(best, runner, config) if runner else []
    if why_bullets:
        advisor += "<p class='fw-bold mt-2 mb-1'>Why this order minimises tax:</p><ol class='small'>"
        for i, bullet in enumerate(why_bullets, 1):
            advisor += "<li>{}</li>".format(bullet)
        advisor += "</ol>"
    sustainable_count = sum(1 for s in ranked if s['sustainable'])
    if sustainable_count < len(ranked):
        advisor += "<p class='fst-italic mt-2'>Note: {} of {} strategies are not sustainable and are ranked below viable options regardless of tax savings.</p>".format(len(ranked) - sustainable_count, len(ranked))

    return {'summary': summary, 'advisor': advisor}


# =====================================================================
# CLI test harness
# =====================================================================
if __name__ == '__main__':
    import json
    import sys

    config_path = sys.argv[1] if len(sys.argv) > 1 else 'config_default.json'
    with open(config_path) as f:
        config = json.load(f)

    print("=" * 80)
    print("OPTIMISER - Testing all 4 questions")
    print("=" * 80)

    # Q1
    print("\n" + "-" * 60)
    print("Q1: Best Drawdown Order")
    print("-" * 60)
    q1 = find_best_drawdown_order(config)
    for i, s in enumerate(q1['ranked']):
        marker = " * WINNER" if i == 0 else ""
        sust = "Y" if s['sustainable'] else "N"
        print(f"  [{sust}] {s['name']:<60s}  Capital: {s['remaining_capital']:>12,.2f}  Tax: {s['total_tax']:>10,.2f}{marker}")

    # Q2
    print("\n" + "-" * 60)
    print("Q2: Maximum Sustainable Income")
    print("-" * 60)
    q2 = find_max_sustainable_income(config)
    print(f"  Current target:    {q2['current_income']:>10,.0f}/year")
    print(f"  Maximum possible:  {q2['max_income']:>10,.0f}/year")
    print(f"  Headroom:          {q2['headroom_amount']:>10,.0f} (+{q2['headroom_pct']:.1f}%)")

    # Q3
    print("\n" + "-" * 60)
    print("Q3: Longevity Headroom")
    print("-" * 60)
    q3 = find_max_sustainable_age(config)
    print(f"  Current end age:   {q3['current_end_age']}")
    print(f"  Maximum age:       {q3['max_age']}")
    print(f"  Extra years:       +{q3['extra_years']}")

    # Q4
    print("\n" + "-" * 60)
    print("Q4: Tax-Efficient Drawdown")
    print("-" * 60)
    q4 = find_tax_efficient_strategy(config)
    print(f"  Current total tax: {q4['current_tax']:>10,.2f}")
    for i, s in enumerate(q4['ranked']):
        marker = " * WINNER" if i == 0 else ""
        sust = "Y" if s['sustainable'] else "N"
        saving = f"Save {s['tax_saving_vs_current']:,.0f}" if s['tax_saving_vs_current'] > 0 else "-"
        print(f"  [{sust}] {s['name']:<60s}  Tax: {s['total_tax']:>10,.2f}  {saving}{marker}")

    print("\n" + "=" * 80)
    print("OPTIMISER - All tests complete")
    print("=" * 80)


# =====================================================================
# Wrapper class for Flask app integration
# =====================================================================
class Optimiser:
    """Convenience wrapper that runs all four optimisation questions."""

    def __init__(self, config: dict):
        self.config = config

    def run_all(self) -> dict:
        return {
            "best_drawdown": find_best_drawdown_order(self.config),
            "max_income": find_max_sustainable_income(self.config),
            "max_age": find_max_sustainable_age(self.config),
            "tax_efficient": find_tax_efficient_strategy(self.config),
        }
