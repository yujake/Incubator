import sys, json, pathlib
sys.path.insert(0, r"D:\Incubator\test\test1\src")
from abflow.extract import extract_text
dt = extract_text(r"D:\Incubator\test\main.pdf")
print("type:", type(dt).__name__)
print("attrs:", [a for a in dir(dt) if not a.startswith("_")])
pages = dt.pages
print("pages:", len(pages))
out = pathlib.Path(r"D:\Incubator\test\test2\_probe\raw-pages.json")
out.write_text(json.dumps({"backend": getattr(dt,'backend',None), "pages": pages}, ensure_ascii=False, indent=1), encoding="utf-8")
joined = "\n".join(pages)
pathlib.Path(r"D:\Incubator\test\test2\_probe\raw-joined.txt").write_text(joined, encoding="utf-8")
print("joined chars:", len(joined))
