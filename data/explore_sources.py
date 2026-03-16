"""Explore the BoE Millennium and ONS CPI data files to identify relevant columns."""
import pandas as pd
import os

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
BOE_FILE = os.path.join(DATA_DIR, "a-millennium-of-macroeconomic-data-for-the-uk.xlsx")
ONS_FILE = os.path.join(DATA_DIR, "mm23.csv")

xl = pd.ExcelFile(BOE_FILE)

# Key sheets to explore
sheets_of_interest = [
    ("A31. Interest rates & asset ps ", "Interest rates & asset prices"),
    ("M13. Mthly share prices 1709+ ", "Monthly share prices"),
    ("M10. Mthly long-term rates", "Monthly long-term rates"),
    ("M9. Mthly short-term rates", "Monthly short-term rates"),
    ("M6. Mthly prices and wages", "Monthly prices and wages"),
    ("A47. Wages and prices", "Annual wages and prices"),
]

# Fix sheet names with potential trailing spaces
all_sheets = xl.sheet_names

for target, desc in sheets_of_interest:
    # Find matching sheet (handle trailing spaces)
    match = None
    for s in all_sheets:
        if s.strip() == target.strip():
            match = s
            break
    if not match:
        print(f"\n### SHEET NOT FOUND: {target}")
        continue

    print(f"\n{'='*80}")
    print(f"### {desc} ({match.strip()})")
    print(f"{'='*80}")

    df = pd.read_excel(xl, sheet_name=match, header=None, nrows=8)
    for i, row in df.iterrows():
        vals = []
        for j, v in enumerate(row):
            s = str(v)
            if s != "nan":
                vals.append(f"[col {j}] {s[:60]}")
        if vals:
            print(f"  Row {i}:")
            for v in vals[:10]:  # limit columns shown
                print(f"    {v}")

# Also check the ONS CPI file
print(f"\n{'='*80}")
print(f"### ONS CPI (mm23.csv)")
print(f"{'='*80}")
with open(ONS_FILE, "r", encoding="utf-8", errors="replace") as f:
    for i, line in enumerate(f):
        if i < 10:
            print(f"  Line {i}: {line.strip()[:120]}")
        else:
            break
