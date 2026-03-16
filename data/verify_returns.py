"""Verify the S&P 500 data extraction and return calculations."""
import pandas as pd

sp = pd.read_csv(r"data\sp500_data.csv")
sp["Date"] = pd.to_datetime(sp["Date"])
sp["Year"] = sp["Date"].dt.year
sp["Month"] = sp["Date"].dt.month

# Check raw monthly data for key years
for yr in [1928, 1929, 1930]:
    dec = sp[(sp["Year"] == yr) & (sp["Month"] == 12)]
    jan = sp[(sp["Year"] == yr) & (sp["Month"] == 1)]
    if len(dec):
        r = dec.iloc[0]
        print(f"{yr} Dec: SP500={r['SP500']:.2f}  Div={r['Dividend']:.4f}")
    if len(jan):
        r = jan.iloc[0]
        print(f"{yr} Jan: SP500={r['SP500']:.2f}  Div={r['Dividend']:.4f}")

print()

# Check what groupby('Year').last() actually returns
ann = sp.groupby("Year").last().reset_index()
for yr in [1928, 1929, 1930, 2007, 2008, 2009]:
    row = ann[ann["Year"] == yr]
    if len(row):
        r = row.iloc[0]
        sp_val = r["SP500"]
        div_val = r["Dividend"]
        print(f"groupby.last() {yr}: SP500={sp_val:.2f}  Div={div_val:.4f}  Month={r['Month']}")

print()

# Manual total return calculation for sanity check
print("Manual total return checks:")
for y0, y1 in [(1928, 1929), (1929, 1930), (2007, 2008), (2008, 2009), (2019, 2020)]:
    r0 = ann[ann["Year"] == y0]
    r1 = ann[ann["Year"] == y1]
    if len(r0) and len(r1):
        p0 = r0.iloc[0]["SP500"]
        p1 = r1.iloc[0]["SP500"]
        div = r1.iloc[0]["Dividend"] * 12
        price_ret = p1 / p0 - 1
        total_ret = (p1 + div) / p0 - 1
        print(f"  {y0}->{y1}: P0={p0:.2f} P1={p1:.2f} AnnDiv={div:.2f} "
              f"PriceRet={price_ret:+.3f} TotalRet={total_ret:+.3f}")
