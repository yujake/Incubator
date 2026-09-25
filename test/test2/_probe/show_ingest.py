import json, pathlib
d = json.loads(pathlib.Path("_probe/p123.json").read_text(encoding="utf-8"))
p3 = [x for x in d["phases"] if x["phase"]=="P3"][0]
print(json.dumps(p3["detail"].get("ingest_per_report"), ensure_ascii=False, indent=1)[:4000])
