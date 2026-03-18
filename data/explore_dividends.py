"""Find dividend yield in the BoE Millennium data — needed for equity total return."""
import pandas as pd
import os

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
BOE_FILE = os.path.join(DATA_DIR, "a-millennium-of-macroeconomic-data-for-the-uk.xlsx")
xl = pd.ExcelFile(BOE_FILE)

# Search ALL sheets for 'dividend' keyword
print("Searching all sheets for 'dividend' keyword in headers...")
for sheet_name in xl.sheet_names:
    try:
        df = pd.read_excel(xl, sheet_name=sheet_name, header=None, nrows=8)
        for col_idx in range(df.shape[1]):
            for r in range(8):
                v = str(df.iloc[r, col_idx]).lower()
                if 'dividend' in v or 'total return' in v or 'equity return' in v:
                    text = str(df.iloc[r, col_idx])[:80]
                    print(f"  Sheet: {sheet_name.strip()}, Col {col_idx}, Row {r}: {text}")
    except Exception:
        pass

# Also check the A1 Headline series for any return-related columns
print("\nA1 Headline: checking cols 30+ for returns...")
df = pd.read_excel(xl, sheet_name='A1. Headline series', header=None, nrows=8)
for col_idx in range(df.shape[1]):
    texts = []
    for r in range(8):
        v = str(df.iloc[r, col_idx])
        if v != 'nan':
            texts.append(v[:80])
    combined = ' '.join(texts).lower()
    if any(k in combined for k in ['return', 'equity', 'share', 'gilt', 'dividend', 'stock']):
        print(f"\n  Col {col_idx}:")
        for t in texts[:4]:
            print(f"    {t}")

# Check ONS CPI date range
print("\n\nONS CPI (D7BT) — finding first non-null value...")
df_ons = pd.read_csv(os.path.join(DATA_DIR, "mm23.csv"), low_memory=False)
d7bt_col = 'CPI INDEX 00: ALL ITEMS 2015=100'
if d7bt_col in df_ons.columns:
    for r in range(len(df_ons)):
        date_val = df_ons.iloc[r, 0]
        cpi_val = df_ons[d7bt_col].iloc[r]
        try:
            float(cpi_val)
            print(f"  First valid CPI: row {r}, date={date_val}, CPI={cpi_val}")
            break
        except (ValueError, TypeError):
            continue
    # Find last valid
    for r in range(len(df_ons)-1, -1, -1):
        date_val = df_ons.iloc[r, 0]
        cpi_val = df_ons[d7bt_col].iloc[r]
        try:
            float(cpi_val)
            print(f"  Last valid CPI:  row {r}, date={date_val}, CPI={cpi_val}")
            break
        except (ValueError, TypeError):
            continue
