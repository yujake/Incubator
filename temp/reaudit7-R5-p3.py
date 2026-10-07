"""第 7 轮重审 · R5 · 探针 p3（v2）：**机械判据**——注释/docstring 里反引号包着的**私有符号名**
必须真的在仓里存在（`AGENTS.md`：理由里写符号名，不写行号）。

用法：
    python temp/reaudit7-R5-p3.py --tree D:\\Incubator\\agentflow --label current

判据（刻意窄，避免噪声把真信号淹掉）：
1. 取本批 5 个文件里反引号包着的、形如 `_lower_snake` 的 token；
2. 在**整棵被测树**的 `.py` 里数它的出现次数；
3. 只出现 1 次（= 只有那处注释在说它）⇒ 判为**悬空引用**并逐条报出。
   （出现 ≥2 次说明它是真的符号/真的数据字段名，噪声档：`_keys` / `_quote_check` 就是后者。）

自校（`reaudit5-COMMON.md` §2 的"探针也要守自己"）：
- SELF-ASSERT：一条必假断言必须抛；
- 反向自校：临时在一个副本里注入一个**必然不存在**的 token ⇒ 判据必须报出它（证明不是恒绿）。

`--inject-fake` 打开反向自校（只在副本上开）。
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

ROOT = Path(r"D:\Incubator")
FILES = [
    "src/agentflow/runflow.py",
    "src/agentflow/modelcost.py",
    "src/agentflow/conductor.py",
    "src/agentflow/tools/table_tools.py",
    "tests/test_r5_orchestration_cost.py",
]
TICK = re.compile(r"`(_[a-z][a-z0-9_]*)`")


def self_assert() -> None:
    try:
        assert 1 == 2, "SELF-ASSERT"
    except AssertionError:
        print("[SELF-ASSERT] 必假断言确实抛了 AssertionError ⇒ 探针的断言机制在工作")
        return
    raise SystemExit(2)


def scan(tree: Path) -> list[tuple[str, str, int]]:
    corpus = {p: p.read_text(encoding="utf-8", errors="replace")
              for p in (tree / "src").rglob("*.py")}
    corpus.update({p: p.read_text(encoding="utf-8", errors="replace")
                   for p in (tree / "tests").rglob("*.py")})
    out: list[tuple[str, str, int]] = []
    seen: set[str] = set()
    for rel in FILES:
        text = (tree / rel).read_text(encoding="utf-8")
        for tok in sorted(set(TICK.findall(text))):
            if tok in seen:
                continue
            seen.add(tok)
            n = sum(t.count(tok) for t in corpus.values())
            if n <= 1:
                out.append((rel, tok, n))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--inject-fake", action="store_true",
                    help="反向自校：复制一份并在注释里塞一个必然不存在的私有符号名")
    args = ap.parse_args(argv)
    self_assert()
    tree = Path(args.tree).resolve()
    if args.inject_fake:
        tree = ROOT / "temp" / "r7-R5-p3-fake-tree"
        if tree.exists():
            shutil.rmtree(tree, ignore_errors=True)
        shutil.copytree(Path(args.tree).resolve(), tree)
        p = tree / "src" / "agentflow" / "runflow.py"
        t = p.read_text(encoding="utf-8")
        anchor = '"""本次运行已经花掉多少（`G-4` / `F5-FOUND-1`）。'
        assert t.count(anchor) == 1, "反向自校的注入锚点不唯一"
        p.write_text(t.replace(
            anchor,
            '"""本次运行已经花掉多少（`G-4` / `F5-FOUND-1` / `_probe_says_this_symbol_is_fake`）。',
            1), encoding="utf-8")
        print(f"[反向自校] 副本已注入一个必然不存在的 token：{tree}")

    hits = scan(tree)
    print(f"=== 探针 p3 · label={args.label} · tree={tree}")
    print("--- 悬空私有符号引用（出现次数 ≤ 1 ⇒ 只有这处注释在说它）")
    if not hits:
        print("    （0 条）")
    for rel, tok, n in hits:
        print(f"    {rel}: `{tok}`（全树出现 {n} 次）")
    print(f"--- 合计 {len(hits)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
