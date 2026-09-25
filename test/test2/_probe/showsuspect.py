import json, pathlib, sys
sys.path.insert(0, r"D:\Incubator\test\test1\src")
from abflow.store import Store
st = Store(r"D:\Incubator\test\test2\workspace")
rels = st.rows("relations")
cons = {c["concept_id"]: c["name"] for c in st.rows("concepts")}
print("concepts:", len(cons), "relations:", len(rels))
print("--- suspects ---")
for r in rels:
    if r.get("status") != "suspect":
        continue
    cc = r.get("_conflict_check") or {}
    print(f"\n[{r['relation_id']}] {[cons.get(c,c) for c in r['concept_ids']]}")
    print("  desc:", r["description"][:120])
    print("  quote:", r["quote"][:110])
    print("  conflicts_with:", cc.get("conflicts_with"))
    print("  reason:", str(cc.get("reason"))[:300])
