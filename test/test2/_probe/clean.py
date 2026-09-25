import json, pathlib, re
d = json.loads(pathlib.Path("raw-pages.json").read_text(encoding="utf-8"))
pages = d["pages"]
bad = set()
out = []
for i,p in enumerate(pages,1):
    q = []
    for ch in p:
        o = ord(ch)
        if o < 32 and ch not in "\n\t":
            bad.add(hex(o)); q.append(" ")
        else:
            q.append(ch)
    out.append(f"===== PAGE {i} =====\n" + "".join(q))
pathlib.Path("raw-joined.txt").write_text("\n".join(out), encoding="utf-8", newline="\n")
print("control chars replaced:", sorted(bad))
print("chars:", sum(len(x) for x in out))
