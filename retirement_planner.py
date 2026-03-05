#!/usr/bin/env python3
"""
Retirement Income Planner V1.1 — CLI Interface
================================================
Command-line interface wrapping the RetirementEngine.

Usage: python retirement_planner.py config.json
"""

import sys
import csv
from pathlib import Path

try:
    from tabulate import tabulate
except ImportError:
    print("ERROR: 'tabulate' package required. Install with: pip install tabulate")
    sys.exit(1)

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
except ImportError:
    print("ERROR: 'matplotlib' package required. Install with: pip install matplotlib")
    sys.exit(1)

from retirement_engine import RetirementEngine


# =============================================================================
# OUTPUT FUNCTIONS
# =============================================================================
def print_results_table(results: list):
    """Print formatted results table to terminal using tabulate."""
    headers = [
        'Age', 'Tax Year', 'Target Net', 'State Pen', 'BP Pen',
        'DC W/draw', 'DC Tax-Free', 'ISA W/draw',
        'Taxable Inc', 'Tax Due', 'Net Income',
        'DC Pot 1', 'DC Pot 2', 'ISA', 'Total Cap'
    ]

    rows = []
    for r in results:
        row = [
            r['age'],
            r['tax_year'],
            f"\u00a3{r['target_net']:,.0f}",
            f"\u00a3{r['state_pension_gross']:,.0f}",
            f"\u00a3{r['bp_pension_gross']:,.0f}",
            f"\u00a3{r['dc_withdrawal_gross']:,.0f}",
            f"\u00a3{r['dc_tax_free_portion']:,.0f}",
            f"\u00a3{r['isa_withdrawal']:,.0f}",
            f"\u00a3{r['total_taxable_income']:,.0f}",
            f"\u00a3{r['tax_due']:,.0f}",
            f"\u00a3{r['net_income_achieved']:,.0f}" + (" \u26a0\ufe0f" if r['shortfall'] else " \u2705"),
            f"\u00a3{r['dc_pot1_balance']:,.0f}",
            f"\u00a3{r['dc_pot2_balance']:,.0f}",
            f"\u00a3{r['isa_balance']:,.0f}",
            f"\u00a3{r['total_capital']:,.0f}",
        ]
        rows.append(row)

    print("\n" + "=" * 120)
    print("RETIREMENT INCOME PROJECTION — YEAR BY YEAR")
    print("=" * 120)
    print(tabulate(rows, headers=headers, tablefmt='simple', stralign='right'))
    print()


def export_csv(results: list, output_path: str):
    """Export results to CSV file."""
    fieldnames = [
        'age', 'tax_year', 'target_net', 'state_pension_gross', 'bp_pension_gross',
        'dc_withdrawal_gross', 'dc_tax_free_portion', 'isa_withdrawal',
        'total_taxable_income', 'tax_due', 'net_income_achieved',
        'dc_pot1_balance', 'dc_pot2_balance', 'isa_balance', 'total_capital'
    ]

    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            row = {k: r[k] for k in fieldnames}
            writer.writerow(row)

    print(f"\u2705 CSV exported to: {output_path}")


def generate_chart(results: list, output_path: str):
    """Generate capital trajectory chart as PNG."""
    ages = [r['age'] for r in results]
    dc_pot1 = [r['dc_pot1_balance'] for r in results]
    dc_pot2 = [r['dc_pot2_balance'] for r in results]
    isa = [r['isa_balance'] for r in results]
    total = [r['total_capital'] for r in results]

    fig, ax = plt.subplots(figsize=(14, 7))

    ax.plot(ages, dc_pot1, 'b-o', markersize=4, linewidth=2, label='DC Pot 1 (Consolidated)')
    ax.plot(ages, dc_pot2, 'r-s', markersize=4, linewidth=2, label='DC Pot 2 (Employer)')
    ax.plot(ages, isa, 'g-^', markersize=4, linewidth=2, label='ISA')
    ax.plot(ages, total, 'k-D', markersize=5, linewidth=2.5, label='Total Capital')

    ax.set_xlabel('Age', fontsize=12)
    ax.set_ylabel('Balance (\u00a3)', fontsize=12)
    ax.set_title('Retirement Capital Trajectory', fontsize=14, fontweight='bold')
    ax.legend(fontsize=10, loc='upper right')
    ax.grid(True, alpha=0.3)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, p: f'\u00a3{x:,.0f}'))
    ax.set_xlim(ages[0], ages[-1])
    ax.set_ylim(bottom=0)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"\u2705 Chart saved to: {output_path}")


def print_summary(summary: dict, warnings: list):
    """Print summary metrics and warnings."""
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    if summary['sustainable']:
        print(f"\n  \u2705 SUSTAINABLE — Target income can be maintained to age {summary.get('end_age', 90)}")
    else:
        print(f"\n  \u26a0\ufe0f  NOT FULLY SUSTAINABLE — Income target unmet from age {summary['first_shortfall_age']}")

    print(f"\n  Total tax paid over retirement:    \u00a3{summary['total_tax_paid']:>12,.2f}")
    print(f"  Average effective tax rate:         {summary['avg_effective_tax_rate']:>11.1f}%")
    print(f"\n  Remaining capital at end:")
    print(f"    DC Pot 1 (Consolidated):         \u00a3{summary['remaining_dc_pot1']:>12,.2f}")
    print(f"    DC Pot 2 (Employer):             \u00a3{summary['remaining_dc_pot2']:>12,.2f}")
    print(f"    ISA:                             \u00a3{summary['remaining_isa']:>12,.2f}")
    print(f"    {'\u2500' * 45}")
    print(f"    TOTAL:                           \u00a3{summary['remaining_capital']:>12,.2f}")

    if summary['first_pot_exhausted_age']:
        print(f"\n  First pot exhausted at age:         {summary['first_pot_exhausted_age']}")
    else:
        print(f"\n  No pots exhausted \u2705")

    if warnings:
        print(f"\n  {'\u2500' * 60}")
        print("  WARNINGS:")
        for w in warnings:
            print(f"    {w}")

    print("\n" + "=" * 80)


# =============================================================================
# MAIN
# =============================================================================
def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python retirement_planner.py <config.json>")
        print("Example: python retirement_planner.py config_default.json")
        sys.exit(1)

    config_path = sys.argv[1]
    print(f"\n\u2699\ufe0f  Loading config from: {config_path}")
    config = RetirementEngine.load_config(config_path)

    # Create output directory
    script_dir = Path(config_path).parent
    output_dir = script_dir / 'output'
    output_dir.mkdir(exist_ok=True)

    print(f"\u2699\ufe0f  Running projection: age {config['personal']['retirement_age']} to {config['personal']['end_age']}")
    print(f"\u2699\ufe0f  Target net income: \u00a3{config['target_income']['net_annual']:,.0f}/year (CPI: {config['target_income']['cpi_rate']:.0%})")
    print(f"\u2699\ufe0f  Tax regime: {config['tax']['regime']}")

    # Run projection via engine
    engine = RetirementEngine(config)
    result = engine.run_projection()

    results  = result['years']
    warnings = result['warnings']
    summary  = result['summary']

    # Output results
    print_results_table(results)

    csv_path = str(output_dir / 'results.csv')
    export_csv(results, csv_path)

    chart_path = str(output_dir / 'capital_trajectory.png')
    generate_chart(results, chart_path)

    print_summary(summary, warnings)

    print(f"\n\u2705 All outputs saved to: {output_dir}/")
    print("\u2705 Retirement Income Planner V1.1 — Complete\n")


if __name__ == '__main__':
    main()
