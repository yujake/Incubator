import sys
sys.path.insert(0, r"D:\Incubator\test\test1\src")
from abflow.store import Store
from abflow import interactions as I
st = Store(r"D:\Incubator\test\test2\workspace")
rels = {r["relation_id"]: r for r in st.rows("relations")}
cons = {c["concept_id"]: c["name"] for c in st.rows("concepts")}
for rid in ("0003","0004","0012","0016","0017","0019","0022","0006","0021","0024"):
    r = rels.get(rid)
    if not r: continue
    t = I._text_of(r)
    print(f"[{rid}] concepts={[cons.get(c,c) for c in r['concept_ids']]} group={r.get('concept_group_key')!r}")
    print(f"   statement={r.get('statement')!r}")
    print(f"   neg={I.negated(t)} pairs={sorted(I.opposite_flags(t))}")
    print(f"   text[:160]={t[:160]!r}")
    print()
