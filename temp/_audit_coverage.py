"""六批审计的**文件覆盖检查**：本会话改过的文件，有没有一个不在任何一批的冻结集里？

> ⚠️ **已被 `temp/_audit_coverage7.py` 取代（2026-09-27，第 6 轮）**，保留它是为了留痕。
> 取代的原因有两条，都是 `R7` 审计者实测报出来的（见 `temp/REAUDIT6-R7.md` §4）：
> ① 它在**默认 GBK 控制台会崩**（输出里有 `⇒`，`UnicodeEncodeError` ⇒ exit 1）——
>    与 `console.pin_utf8` 是同一件事；本文件现在也在 import 期把 stdout 钉成 UTF-8。
> ② 它解析 `reaudit5-COMMON.md` §3 的**散文清单**，只认到一部分条目 ⇒ 它把"不在任何冻结集里"
>    算成 122 个（连本批 25 个冻结文件全算进去）。**差集必须人工核**，不许只看它的计数。
> `_audit_coverage7.py` 换了个口径：把七批冻结集**写死在脚本里**（与派单文本逐字一致），
> 再与实际改动面比 —— 那样才有一个可复跑、可与派单对账的读数。

## 为什么必须查这个

判据二要"每批改动由没写过该批代码的独立子代理重审"，而六批是按**落点文件**切的
（`reaudit5-COMMON.md` §3 各批的「文件清单」）。⇒ 如果一个被改过的文件**不在任何一批的清单里**，
它就**永远不会被审**，而六批仍然可以"全部通过"。这是"判据结构性看不见"的又一种形态
（本会话已经见过几次：测试守着一句谎、清单里没有判据本体、现在轮到"审计范围"本身）。

实例：`src/agentflow/gates.py`（15 道论文门）**不在六批任何一批的清单里**，而它今天被改过。

## 做法

1. 从 `git status --porcelain` 取**本会话改过/新增**的文件（仓库未提交，所以工作区差异就是本会话）；
2. 从 `reaudit5-COMMON.md` §3 的每批「文件清单」段抽出路径；
3. 求差：改过但**没被任何一批覆盖**的 → 打印出来（这些要么加进某批，要么如实登记为"未覆盖面"）。

用法：`python D:\\Incubator\\temp\\_audit_coverage.py`
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

#: 把自己的 stdout 钉成 UTF-8（`R7` 审计者实测：默认 GBK 控制台下本脚本会因 `⇒` 崩掉，
#: 退出码 1 与"查过了、有未覆盖面"撞车 —— 三态纪律的反面教材。`_who_writes.py` 同做法。）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

REPO = Path(r"D:\Incubator")
PROJ = REPO / "agentflow"
COMMON = Path(r"D:\Incubator\temp\reaudit5-COMMON.md")
#: 只关心这几类（审计面的实质就是代码与测试；`.md` 单列）
KINDS = (".py", ".md")


def changed_files() -> list[str]:
    p = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = []
    for line in (p.stdout or "").split("\n"):
        if len(line) < 4:
            continue
        path = line[3:].strip().strip('"')
        if not path.startswith("agentflow/"):
            continue
        rel = path[len("agentflow/"):]
        if rel.endswith(KINDS):
            out.append(rel)
    return sorted(out)


def batch_lists() -> dict[str, list[str]]:
    text = COMMON.read_text(encoding="utf-8")
    batches: dict[str, list[str]] = {}
    cur = None
    for ln in text.split("\n"):
        m = re.match(r"^### (R\d)\s", ln)
        if m:
            cur = m.group(1)
            batches[cur] = []
            continue
        if cur and "文件清单" in ln:
            # 一个文件清单段可能跨多行：从这一行起，收所有反引号里的路径
            batches[cur] += re.findall(r"`([^`]+)`", ln)
    # 清单里常见 `tests/test_verify*.py` 这类通配 ⇒ 用 fnmatch 匹配
    return batches


def main() -> int:
    changed = changed_files()
    batches = batch_lists()
    print(f"本会话改过/新增（agentflow 下 {KINDS}）：{len(changed)} 个")
    for b, lst in batches.items():
        print(f"  {b} 的冻结集条目：{len(lst)} 条")
    import fnmatch
    covered: set[str] = set()
    for rel in changed:
        for b, lst in batches.items():
            for pat in lst:
                pat = pat.strip()
                if not pat or pat.endswith("/**") or "…" in pat:
                    continue
                if fnmatch.fnmatch(rel, pat) or rel == pat or Path(rel).name == pat:
                    covered.add(rel)
                    break
            if rel in covered:
                break
    missing = [r for r in changed if r not in covered]
    print(f"\n**改了但不在任何一批冻结集里的：{len(missing)} 个**")
    for r in missing:
        print(f"  - {r}")
    print("\n处置：把这些**加进最贴近的那一批**（例如 `src/agentflow/gates.py` 是论文证据门 ⇒ 归 R2 证据链），"
          "或在台账里如实登记为「未覆盖面」—— 但不许让它们留在两者之间。")
    # ⚠️ 退出码：**有未覆盖面 ⇒ 1**（三态纪律：一条永远返回 0 的检查，等于没有检查 ——
    # 而"差集非空"正是它要报的那件事）。一批清单都没解析出来 ⇒ 2（没查成，不是通过）。
    # （第一版我在这里写了个不存在的变量名 `buckets` —— 与本文件要防的那类错误同族，
    #   所以这里用 `batch_lists()` 的真实返回值 `batches`。）
    if not batches:
        print("没查成：`reaudit5-COMMON.md` 的 §3 一批清单都没解析出来（≠ 通过）")
        return 2
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
