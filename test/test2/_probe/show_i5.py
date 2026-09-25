import json, pathlib
d = json.loads(pathlib.Path("_probe/p2b.json").read_text(encoding="utf-8"))
p = [x for x in d["phases"] if x["phase"]=="P2b"][0]["detail"]
print("I5:", json.dumps(p.get("I5"), ensure_ascii=False, indent=1)[:1800])
print("\nI4:", json.dumps(p.get("I4"), ensure_ascii=False, indent=1)[:900])
