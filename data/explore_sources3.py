"""Find equity total returns, gilt total returns, and Bank Rate in A31."""
import pandas as pd
import os

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
BOE_FILE = os.path.join(DATA_DIR, "a-millennium-of-macroeconomic-data-for-the-uk.xlsx")

xl = pd.ExcelFile(BOE_FILE)

# ── A31: Full column scan for equity/gilt/return keywords ──
print("A31: All columns with equity/gilt/return/total/stock/share/consol keywords")
print("=" * 80)
df = pd.read_excel(xl, sheet_name='A31. Interest rates & asset ps ', header=None, nrows=8)
for col_idx in range(df.shape[1]):
    texts = []
    for r in range(8):
        v = str(df.iloc[r, col_idx])
        if v != 'nan':
            texts.append(v[:80])
    combined = ' '.join(texts).lower()
    keywords = ['equity', 'share', 'stock', 'gilt', 'consol', 'total return',
                'dividend', 'capital gain', 'bank rate', 'real return']
    if any(k in combined for k in keywords):
        print(f"\n  Col {col_idx}:")
        for t in texts:
            print(f"    {t}")

# ── Check how far the data goes ──
print("\n\nA31: Last few data rows")
print("=" * 80)
df_all = pd.read_excel(xl, sheet_name='A31. Interest rates & asset ps ', header=None, skiprows=7)
last_rows = df_all.tail(5)
for i, row in last_rows.iterrows():
    print(f"  Year={row.iloc[0]}")

# ── D1: Official Interest Rates (Bank Rate) ──
print("\n\nD1: Official Interest Rates — headers")
print("=" * 80)
sheets = xl.sheet_names
d1_match = [s for s in sheets if 'D1' in s][0]
df_d1 = pd.read_excel(xl, sheet_name=d1_match, header=None, nrows=8)
for col_idx in range(min(df_d1.shape[1], 8)):
    texts = [str(df_d1.iloc[r, col_idx])[:60] for r in range(8) if str(df_d1.iloc[r, col_idx]) != 'nan']
    if texts:
        print(f"  Col {col_idx}: {' | '.join(texts)}")

# Sample data
df_d1_data = pd.read_excel(xl, sheet_name=d1_match, header=None, skiprows=7, nrows=3)
print("  Sample:")
for i, row in df_d1_data.iterrows():
    print(f"    {[v for v in row.iloc[:5] if str(v) != 'nan']}")
