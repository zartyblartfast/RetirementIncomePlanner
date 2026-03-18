"""Get exact column layout for equity returns, gilt returns from A31 cols 22-35+."""
import pandas as pd
import os

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
BOE_FILE = os.path.join(DATA_DIR, "a-millennium-of-macroeconomic-data-for-the-uk.xlsx")

xl = pd.ExcelFile(BOE_FILE)

# ── A31: Cols 18-40 headers (asset prices and returns section) ──
print("A31: Cols 18-40 — headers rows 0-7")
print("=" * 80)
df = pd.read_excel(xl, sheet_name='A31. Interest rates & asset ps ', header=None, nrows=8, usecols=range(18, 37))
for col_idx in range(df.shape[1]):
    actual_col = col_idx + 18
    texts = [str(df.iloc[r, col_idx])[:80] for r in range(8) if str(df.iloc[r, col_idx]) != 'nan']
    if texts:
        print(f"\n  Col {actual_col}:")
        for t in texts:
            print(f"    {t}")

# ── Sample data from 1900-1905 for these columns ──
print("\n\nA31: Sample data 1900-1905, cols 0 + 18-40")
print("=" * 80)
df_all = pd.read_excel(xl, sheet_name='A31. Interest rates & asset ps ', header=None, skiprows=7)
for i, row in df_all.iterrows():
    yr = row.iloc[0]
    if yr == 1900:
        for j in range(6):
            r = df_all.iloc[i+j]
            year = r.iloc[0]
            vals = {}
            for c in [1, 19, 22, 23, 28, 30, 31, 32, 33, 34, 35]:
                v = r.iloc[c] if c < len(r) else None
                if str(v) != 'nan':
                    vals[c] = round(v, 4) if isinstance(v, float) else v
            print(f"  Year {year}: {vals}")
        break

# ── Also check the ONS CPI data for D7BT ──
print("\n\nONS mm23.csv: D7BT (CPI All Items 2015=100) — sample rows")
print("=" * 80)
df_ons = pd.read_csv(os.path.join(DATA_DIR, "mm23.csv"), low_memory=False)
# Find D7BT column
cdid_row = df_ons.iloc[0]  # CDID codes are in first data row after header
# Actually the structure is: row 0 = Title, so column headers are Title
# Let me check
print(f"  Columns count: {len(df_ons.columns)}")
print(f"  First col name: {df_ons.columns[0]}")
print(f"  Row 0 first vals: {list(df_ons.iloc[0, :3])}")

# Find D7BT by scanning CDID row (row index 0 in the data, which is row 1 in file)
for col_i, col_name in enumerate(df_ons.columns):
    if 'D7BT' in str(col_name) or 'D7BT' in str(df_ons.iloc[0, col_i]):
        print(f"\n  Found D7BT at col index {col_i}, header='{col_name}'")
        # Print some data rows
        for r in range(6, min(20, len(df_ons))):
            date_val = df_ons.iloc[r, 0]
            cpi_val = df_ons.iloc[r, col_i]
            if str(date_val) not in ('nan', ''):
                print(f"    {date_val}: {cpi_val}")
        break
