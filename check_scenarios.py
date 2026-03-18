"""Quick check of scenario data structure for chart truncation investigation."""
import json, os

for fname in sorted(os.listdir('scenarios')):
    if not fname.endswith('.json'):
        continue
    with open(os.path.join('scenarios', fname)) as f:
        sc = json.load(f)
    has_ext = 'ext_result' in sc
    if has_ext:
        years = sc['ext_result']['years']
    else:
        years = sc['result']['years']
    max_age = max(y['age'] for y in years)
    result_max = max(y['age'] for y in sc['result']['years'])
    print(f"{fname}:")
    print(f"  has ext_result: {has_ext}")
    print(f"  chart years max age: {max_age} ({len(years)} years)")
    print(f"  result years max age: {result_max} ({len(sc['result']['years'])} years)")
    print()
