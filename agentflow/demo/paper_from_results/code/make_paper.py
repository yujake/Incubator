"""T3 的工作区夹具之一：**写渲染锚**（只写锚，一个字都不碰 `main.tex`）。

这一份是 `draft/38` §9 三 说的那两份夹具里的渲染步（`paperbuild.DEFAULT_RENDER_SCRIPT`
就是 `code/make_paper.py`）。放到 `agentflow/demo/paper_from_results/code/` 是为了让它
**进版本库**（`projects/` 是 gitignore 的，工作区里的那份副本跑完就没了）。

## 与 T1 那份（`projects/p6r-paper-from-results/code/`）的两处不同，都是真机读数

1. **先 `mkdir(parents=True)`**：那一份写锚时直接 `write_text`，在"还没有 `out/paper/`"
   的工作区里会 `FileNotFoundError`（T3 第 5 趟 `t3e` 就是这么整趟走不通的）；
2. **主稿不在时给一句人话、并以退出码 2 结束**：那一份的失败在框架那一层只剩
   「脚本没打印 `REPRO_RESULT:`」，M 于是把原因猜成"缺 `source/` 基线"，
   并据此改了交付形式。这里把真正的原因（`out/paper/main.tex` 不在盘上）**直接打出来**。

## 契约

- 本脚本**只**产出锚（`renderanchor.build_anchor`），不改主稿、不编译；
- 退出码：0 = 锚写出来了；2 = 主稿不在盘上（**没查成**，不是"锚不一致"）。
"""
import json
import pathlib
import sys

sys.path.insert(0, r"D:\Incubator\agentflow\src")
from agentflow import renderanchor as RA  # noqa: E402
from agentflow.store import Store  # noqa: E402

root = pathlib.Path(".").resolve()
out = root / "out" / "paper"
tex = out / "main.tex"

if not tex.is_file():
    why = ("out/paper/main.tex 不在盘上 ⇒ 这一步只写锚，而锚要有主稿可比。"
           "先把论文正文落到 out/paper/main.tex（写稿那一步的产物），再跑本脚本")
    print("REPRO_RESULT: " + json.dumps({"anchor": "not_written", "reason": why},
                                        ensure_ascii=False))
    print(why, file=sys.stderr)
    sys.exit(2)

out.mkdir(parents=True, exist_ok=True)
st = Store(root)
(out / RA.ANCHOR_NAME).write_text(
    json.dumps(RA.build_anchor(st, out), ensure_ascii=False), encoding="utf-8")
print("REPRO_RESULT: " + json.dumps({"anchor": "written", "touched_main_tex": False}))
