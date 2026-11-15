# -*- coding: utf-8 -*-
"""CC3：把 readings.json 压成报告用的表格（逐链、Lean 开/关）。"""
import json
from pathlib import Path

d = json.loads(Path("temp/cc3/readings.json").read_text(encoding="utf-8")
               .split("\n", 1)[1] if Path("temp/cc3/readings.json").read_text(
                   encoding="utf-8").startswith("warning:") else
               Path("temp/cc3/readings.json").read_text(encoding="utf-8"))
for key, v in d.items():
    print("==", key)
    for k, val in v.items():
        text = json.dumps(val, ensure_ascii=False, default=str)
        print(f"   {k}: {text[:400]}")
