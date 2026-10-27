# -*- coding: utf-8 -*-
"""判据：跑过那两条 demo 自检之后，`demo/selftest/` 必须是干净的。

## 先给证据：是谁写的、脏成什么样

`demo/selftest/{blank,sample}.pdf` 曾经是两条 demo 自检的落点，不是测试夹具的落点：

- `src/agentflow/extract.py` 的 `__main__` 块：`DEMO = Path(__file__).resolve().parents[2]
  / "demo" / "selftest"`，随后 `pdf.save(str(pdf_path))` / `blank.save(str(blank_path))`，
  还会写一份 `nope.docx`（`(DEMO / "nope.docx").write_bytes(...)`）；
- `src/agentflow/llm.py` 的 `__main__` 块：同一个 `DEMO`、同样两处 `save`。

实测（2026-10-26，改前，两次读数）：

```text
> git status --porcelain -- demo/          （跑之前）
                                              <- 空
> python -m agentflow.extract ; git status --porcelain -- demo/
 M agentflow/demo/selftest/blank.pdf
 M agentflow/demo/selftest/sample.pdf
> python -m agentflow.llm     ; git status --porcelain -- demo/
 M agentflow/demo/selftest/blank.pdf
 M agentflow/demo/selftest/sample.pdf
```

HEAD 那次提交（`1ab029f`，2026-10-26 00:26:47）的 stat 里正好只有这两份 PDF
（`blank.pdf | 2 +-` / `sample.pdf | 2 +-`），而那次提交的主题是时钟系统收口 ——
脏文件被顺手提进了不相干的提交。

## 为什么根处是"写临时目录"，而不是"跑完再还原"

`fitz` 每次落盘的字节都不同（`nope.docx` 相同，两份 PDF 不同）⇒ 只要自检还写仓内目录，
跑一次就脏一次（不是"偶尔"）。按 HEAD 还原只是遮：G3 在 10:4x 还原过一次、当时判据 3 passed，
全量里另一条跑 demo 的用例又把它改脏了。所以治的地方是写者：两条自检的产物落到
`tempfile.mkdtemp()`，并在收尾时删掉。

`extract.py` 在 FC-27 禁改区（`.noai-paths` 的 `[category: solver-core]`），这次改动由
业主 2026-10-26 的施工单直接下令（"自检/演示的产物写到临时目录"），且只动
`if __name__ == "__main__":` 那一块（`extract_text` / PDF 后端一个字没动）。
`python scripts/noai_gate.py --paths src/agentflow/extract.py` 因此以退出码 1 结束
（`required_approvals=2`）—— 那是这道门该有的读数，不是可以绕过的。

## 这一份判据的三半（缺一半就会变成空转）

- 静态那一半（`test_the_two_demo_selfchecks_write_into_a_temp_dir_not_the_repo`）：
  钉住"两条自检都用 `tempfile.mkdtemp()`，且 `__main__` 块里不再出现 `demo` / `selftest`
  这两段路径分量"。谁改回写仓库，这一条当场红。
- 读数那一半（`test_the_repo_demo_selftest_is_not_dirty`）：`git status --porcelain --
  demo/selftest` 必须为空 —— 这就是"跑完之后仓库是干净的"这条口径。
- 正控那一半（`test_running_the_two_selfchecks_leaves_demo_selftest_clean`）：真把两条
  自检各跑一遍，再量同一个 `git status`。只有这一半能证明"跑起来真的没写进仓库"：
  静态那一半只证明路径改成临时目录了。改前这一半会红（上面那两行 M 就是它的读数）。

三半都按三态纪律写：git 起不来 / 不在仓库里 / 自检退出码非 0 = 没查成，判红
（不是跳过、也不是通过）。

## 已知盲区（写清，否则这一条会被读成比它实际更强）

`.gitignore` 里有一行 `/agentflow/demo/selftest/`（整条目录被忽略），而目录里那五份文件
是被跟踪的 —— git 的忽略规则不作用于已跟踪文件，所以"被改写"看得见，"新增一个文件"
看不见。也就是说这几条判据只量已跟踪的那几份（`blank.pdf` / `sample.pdf` / `nope.docx` /
`sample.html` / `sample_zh.txt`），新落进去的未跟踪文件它不报。
"""

from __future__ import annotations

import ast
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "agentflow"

#: 曾经会写 `demo/selftest/` 的那两个模块。逐条点名：新加一个也得在这里登记一行。
WRITERS: tuple[str, ...] = ("extract.py", "llm.py")

#: 那两份每次字节都不相同的 PDF（`nope.docx` 也会被写，但它每次字节相同）。
DIRTIED: tuple[str, ...] = ("demo/selftest/sample.pdf", "demo/selftest/blank.pdf")


def _parse(module: str) -> ast.Module:
    path = SRC / module
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _main_block(module: str) -> ast.If:
    """取出 `if __name__ == "__main__":` 那一块（没有就红 —— 没查成不是通过）。"""
    for node in _parse(module).body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"):
            continue
        return node
    raise AssertionError(
        f"{module} 里没有 `if __name__ == \"__main__\":` 块 —— 这条判据要量的东西不见了："
        "要么自检被搬走（那就改这里），要么它换了形态（那就改下面那两半）"
    )


def _strings(node: ast.AST) -> set[str]:
    return {n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def dirty_paths(porcelain: str) -> list[str]:
    """`git status --porcelain -- <路径>` 的输出 -> 脏掉的文件（纯函数，便于一正一反）。"""
    got: list[str] = []
    for line in str(porcelain).splitlines():
        if not line.strip():
            continue
        # porcelain 的短格式：两列状态位 + 一个空格 + 路径。
        got.append(line[3:].strip())
    return got


def _git_status_porcelain(*paths: str) -> str:
    """仓库里这几个路径的 porcelain 读数；git 起不来或不在仓库里 ⇒ 判"没查成"。"""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--", *paths],
            cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:   # git 不在这台机器上
        pytest.fail(
            f"没查成：起不了 git（{type(exc).__name__}: {exc}）⇒ 这一条判据今天没有读数。"
            "三态纪律：没查成不算通过")
    if proc.returncode != 0:
        pytest.fail(
            "没查成：`git status --porcelain -- "
            f"{' '.join(paths)}` 退出码 {proc.returncode} ⇒ 这一条判据今天没有读数。"
            f"stderr：{(proc.stderr or '')[-400:]}")
    return proc.stdout or ""


def test_the_porcelain_parser_separates_dirty_from_clean() -> None:
    """差分（这一条自己承重）：解析器必须把脏的读成脏、干净的读成干净。

    没有这一半，"`git status` 必须为空"可以因为解析器永远返回空列表而永远绿 ——
    那正是本仓库反复踩的"绿着、但没在量"。
    """
    dirty = (
        " M demo/selftest/blank.pdf\n"
        " M demo/selftest/sample.pdf\n"
    )
    assert sorted(dirty_paths(dirty)) == sorted(DIRTIED), dirty_paths(dirty)
    assert dirty_paths("") == []
    assert dirty_paths("\n  \n") == []
    # 未跟踪的新文件也是脏的（`??` 开头的两列），不许被解析器漏掉。
    assert dirty_paths("?? demo/selftest/extra.pdf\n") == ["demo/selftest/extra.pdf"]


def test_the_two_demo_selfchecks_write_into_a_temp_dir_not_the_repo() -> None:
    """静态那一半：两条自检的落点必须是临时目录，且不再指向仓库里的 `demo/selftest`。

    改前这一半钉的是相反的事实（"落点就是仓库里的 `demo/selftest`，路径从 `__file__`
    算出来"）。2026-10-26 改写成临时目录之后，这一半跟着翻面：谁把落点改回仓内
    目录，这一条当场红 —— 而它守的原因（跑一次脏一次）由下面那两半继续量。
    """
    seen: dict[str, set[str]] = {}
    for module in WRITERS:
        block = _main_block(module)
        got = _strings(block)
        assert {"sample.pdf", "blank.pdf"} <= got, (
            f"{module} 的 `__main__` 块里找不到那两份产物的文件名：{sorted(got)}")
        attrs = {n.func.attr for n in ast.walk(block)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert "mkdtemp" in attrs, (
            f"{module} 的 `__main__` 块里没有 `tempfile.mkdtemp(...)` —— "
            "自检的产物必须落到临时目录"
            f"（这一块里见到的属性调用：{sorted(attrs)}）")
        assert "save" in attrs, (
            f"{module} 的 `__main__` 块里没有 `save(...)` 调用 —— 它已经不写那两份 PDF 了？"
            f"（这一块里见到的属性调用：{sorted(attrs)}）")
        assert "demo" not in got and "selftest" not in got, (
            f"{module} 的 `__main__` 块里又出现了 `demo` / `selftest` 这两段路径分量："
            f"{sorted(got)} —— 自检写回仓库就会跑一次脏一次（这条判据的存在理由）")
        seen[module] = got
    # 两个模块各写各的，但它们写的是同两份文件 —— 这一点也要在读数上分得开。
    assert len(seen) == len(WRITERS), seen


def test_the_repo_demo_selftest_is_not_dirty() -> None:
    """读数那一半：`git status --porcelain -- demo/selftest` 必须为空。

    红了说明有人跑过 `python -m agentflow.extract` / `python -m agentflow.llm` 而没还原。
    还原只要一句：`git checkout -- demo/selftest`（那两份 PDF 是自检的产物，不是手改的素材）。
    """
    porcelain = _git_status_porcelain("demo/selftest")
    dirty = dirty_paths(porcelain)
    assert dirty == [], (
        "`demo/selftest/` 被弄脏了 —— 写它的是两条 demo 自检的 `__main__` 块"
        "（`src/agentflow/extract.py` 与 `src/agentflow/llm.py`，落点见本文件 docstring）：\n"
        f"  脏掉的文件：{dirty}\n"
        f"  git 读数：{porcelain!r}\n"
        "  还原：`git checkout -- demo/selftest`（这两份 PDF 是自检产物，别提交它们）"
    )


def test_running_the_two_selfchecks_leaves_demo_selftest_clean(tmp_path: pathlib.Path) -> None:
    """正控：真跑那两条自检，跑完之后同一个 `git status` 必须为空。

    为什么要真跑：静态那一半只能证明"路径写成临时目录了"，证明不了"跑起来真的没写进
    仓库"。改前这一条会红 —— 实测就是上面 docstring 里那两行 `M demo/selftest/*.pdf`。

    自检的 cwd 用 `tmp_path`（空目录）：它们自己造临时工作区，不该依赖调用者的当前目录。
    退出码非 0 判红（自检没跑成 = 这一条没有读数），不是跳过。
    """
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
           "PYTHONPATH": str(REPO / "src")}
    for module in WRITERS:
        mod = module[:-3]
        r = subprocess.run([sys.executable, "-m", f"agentflow.{mod}"], cwd=str(tmp_path),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, timeout=600)
        out = (r.stdout or "") + (r.stderr or "")
        assert r.returncode == 0, f"`python -m agentflow.{mod}` 退出码 {r.returncode}：{out[-800:]}"
    porcelain = _git_status_porcelain("demo/selftest")
    dirty = dirty_paths(porcelain)
    assert dirty == [], (
        "跑过那两条自检之后 `demo/selftest/` 变脏了 —— 自检的产物又写进了仓库：\n"
        f"  脏掉的文件：{dirty}\n"
        f"  git 读数：{porcelain!r}\n"
        "  治的地方是写者（产物落到 `tempfile.mkdtemp()`），不是跑完再还原"
    )
