"""Deeper exploration: find exact columns for equity returns, gilt returns, CPI, Bank Rate."""
import pandas as pd
import os

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
BOE_FILE = os.path.join(DATA_DIR, "a-millennium-of-macroeconomic-data-for-the-uk.xlsx")
ONS_FILE = os.path.join(DATA_DIR, "mm23.csv")

xl = pd.ExcelFile(BOE_FILE)

# ── A31: Interest rates & asset prices ──
print("=" * 80)
print("A31: Interest rates & asset prices — looking for equity returns, gilt returns")
print("=" * 80)
df = pd.read_excel(xl, sheet_name='A31. Interest rates & asset ps ', header=None, nrows=8)
for col_idx in range(df.shape[1]):
    col_vals = [str(df.iloc[r, col_idx])[:70] for r in range(min(7, len(df))) if str(df.iloc[r, col_idx]) != 'nan']
    if col_vals:
        print(f"\n  Col {col_idx}: {' | '.join(col_vals)}")

# Also check a few data rows
print("\n--- Sample data rows (A31) ---")
df_data = pd.read_excel(xl, sheet_name='A31. Interest rates & asset ps ', header=None, skiprows=7, nrows=5)
for i, row in df_data.iterrows():
    print(f"  Row {i}: col0={row.iloc[0]}, col1={row.iloc[1]}, first 10 vals: {[round(v,4) if isinstance(v, float) else v for v in row.iloc[:10]]}")

# ── A47: Wages and prices — CPI ──
print("\n" + "=" * 80)
print("A47: Wages and prices — CPI columns")
print("=" * 80)
df = pd.read_excel(xl, sheet_name='A47. Wages and prices', header=None, nrows=8, usecols=range(12))
for col_idx in range(df.shape[1]):
    col_vals = [str(df.iloc[r, col_idx])[:70] for r in range(min(8, len(df))) if str(df.iloc[r, col_idx]) != 'nan']
    if col_vals:
        print(f"\n  Col {col_idx}: {' | '.join(col_vals)}")

# Sample data from ~1900
print("\n--- Sample data rows (A47, from ~1900) ---")
df_all = pd.read_excel(xl, sheet_name='A47. Wages and prices', header=None, skiprows=6)
# Find row where col 0 = 1900
for i, row in df_all.iterrows():
    if row.iloc[0] == 1900:
        for j in range(5):
            r = df_all.iloc[i+j]
            print(f"  Year {r.iloc[0]}: CPI(col3)={r.iloc[3]}, CPI_infl(col4)={r.iloc[4]}, RPI(col6)={r.iloc[6]}")
        break

# ── ONS CPI: find the right CDID ──
print("\n" + "=" * 80)
print("ONS mm23.csv — looking for CPI All Items index (D7BT or similar)")
print("=" * 80)
df_ons = pd.read_csv(ONS_FILE, nrows=2)
# Find columns with CPI in title
for col in df_ons.columns:
    title = str(df_ons.iloc[0].get(col, ''))  # Row 0 is CDID codes
    if 'nan' not in title.lower():
        pass  # Just find CPI All Items
# Read the title row and CDID row
with open(ONS_FILE, 'r', encoding='utf-8', errors='replace') as f:
    title_line = f.readline().strip()
    cdid_line = f.readline().strip()

titles = title_line.split('","')
cdids = cdid_line.split('","')
# Find CPI All Items
for i, (t, c) in enumerate(zip(titles, cdids)):
    t_clean = t.replace('"', '')
    c_clean = c.replace('"', '')
    if 'cpi' in t_clean.lower() and 'all items' in t_clean.lower() and 'index' in t_clean.lower():
        print(f"  Col {i}: CDID={c_clean} Title={t_clean[:80]}")
    if c_clean in ('D7BT', 'D7G7', 'L522'):
        print(f"  Col {i}: CDID={c_clean} Title={t_clean[:80]}")
