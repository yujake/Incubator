# -*- coding: utf-8 -*-
"""判据：`demo/selftest/` 里那两份 PDF 不许在跑过判据之后变脏（谁写的、以及怎么钉住）。

## 先给证据：是谁写的

`demo/selftest/{blank,sample}.pdf` 是两条 demo 自检的落点，不是测试夹具的落点：

- `src/agentflow/extract.py` 的 `__main__` 块：`DEMO = Path(__file__).resolve().parents[2]
  / "demo" / "selftest"`，随后 `pdf.save(str(pdf_path))` / `blank.save(str(blank_path))`，
  还会写一份 `nope.docx`（`(DEMO / "nope.docx").write_bytes(...)`）；
- `src/agentflow/llm.py` 的 `__main__` 块：同一个 `DEMO`、同样两处 `save`。

实测（2026-10-26 00:16）三次读数指向同一件事：

1. 这两份 PDF 与 `nope.docx` 的 mtime 都是 `2026-10-26 00:16:50`，而同一目录里的
   `sample.html` / `sample_zh.txt` 还是 `2026-10-18` 的 —— 只有被自检重写的那三份变了；
2. HEAD 那次提交（`1ab029f`，`2026-10-26 00:26:47`）的 stat 里正好只有这两份 PDF：
   `agentflow/demo/selftest/blank.pdf | 2 +-` / `agentflow/demo/selftest/sample.pdf | 2 +-`，
   而那次提交的主题是时钟系统收口 —— 脏文件被顺手提进了不相干的提交；
3. 把 `src` 拷到临时树里跑一遍 `python -m agentflow.extract`，产出的两份 PDF 与仓库里的
   逐字节不同（fitz 每次落盘的字节不同：nope.docx 相同，两份 PDF 不同）⇒ 重跑一次
   一定把工作区弄脏。

pytest 这一侧量不到它：全树 grep 只有那两个 `__main__` 块会写这三份文件，没有任何用例
起 `python -m agentflow.extract` / `agentflow.llm`。

## 为什么取"加判据"这一条修法，而不是把它们改成写 `tmp_path`

写者是 `extract.py` 与 `llm.py` 的 `__main__` 块。`extract.py` 在禁改区
（仓库根 `.noai-paths` 的 `[category: solver-core]`，`AGENTS.md` 的 FC-27 清单逐条列着），
把它改成写临时目录需要两名 reviewer 的人审；只改 `llm.py` 也修不掉 `extract.py` 那一半。
所以这里取施工单给的第二条路：加一条判据，把"跑过之后必须是干净的"这件事变成会红的读数。

## 这一份判据的两半（缺一半就会变成空转）

- 静态那一半（`test_the_two_demo_selfchecks_still_write_into_the_repo_demo_selftest`）：
  钉住"这两条自检的落点就是仓库里的 `demo/selftest`，而且路径从 `__file__` 算出来"。
  没有这一半，下面那条 git 判据守的是一个可能已经不存在的原因（有人把自检改成写临时目录，
  这条会红，得人来更新这两半）；它同时也是"改名/搬家"这件事的留痕；
- 读数那一半（`test_the_repo_demo_selftest_is_not_dirty`）：`git status --porcelain --
  demo/selftest` 必须为空。谁跑过那两条自检而没还原，这一条当场红，且失败信息里点名
  "是谁写的、怎么还原"。

两半都按三态纪律写：git 起不来 / 不在仓库里 = 没查成，判红（不是跳过、也不是通过）。

## 已知盲区（写清，否则这一条会被读成比它实际更强）

`.gitignore` 里有一行 `/agentflow/demo/selftest/`（整条目录被忽略），而目录里那五份文件
是被跟踪的 —— git 的忽略规则不作用于已跟踪文件，所以"被改写"看得见，"新增一个文件"
看不见。也就是说这条判据只量已跟踪的那几份（`blank.pdf` / `sample.pdf` / `nope.docx` /
`sample.html` / `sample_zh.txt`），新落进去的未跟踪文件它不报。
"""

from __future__ import annotations

import ast
import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "agentflow"

#: 会写 `demo/selftest/` 的那两个模块。逐条点名：新加一个也得在这里登记一行。
WRITERS: tuple[str, ...] = ("extract.py", "llm.py")

#: 被它们重写的那两份 PDF（`nope.docx` 也会被写，但它每次字节相同，不会弄脏）。
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
        "要么自检被搬走（那就改这里），要么它不再写 demo/selftest（那就改上面那次登记）"
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


def test_the_two_demo_selfchecks_still_write_into_the_repo_demo_selftest() -> None:
    """静态那一半：这两条自检的落点就是仓库里的 `demo/selftest`，且路径从 `__file__` 算出来。

    为什么要这一半：下面那条 git 判据守的是"它们会弄脏工作区"这个原因。原因消失了
    （自检改成写临时目录）而判据还在的话，它就变成一条没有对象的空断言，得人来更新。
    """
    seen: dict[str, set[str]] = {}
    for module in WRITERS:
        block = _main_block(module)
        got = _strings(block)
        assert {"demo", "selftest"} <= got, (
            f"{module} 的 `__main__` 块里找不到 `demo` / `selftest` 这两段路径分量：{sorted(got)}"
            "（自检搬去别处了，那就连这一条一起改）")
        assert {"sample.pdf", "blank.pdf"} <= got, (
            f"{module} 的 `__main__` 块里找不到被写的那两份 PDF：{sorted(got)}")
        # 落点必须跟着树走（从 `__file__` 算），不是写死的绝对路径：
        # 这条属性同时是"把它拷到临时树里跑一次"成立的前提。
        assert "__file__" in {n.id for n in ast.walk(block) if isinstance(n, ast.Name)}, (
            f"{module} 的 `__main__` 块的落点不再从 `__file__` 算 —— "
            "写死的绝对路径会让这条判据的现场读数在别的机器上完全走样")
        attrs = {n.func.attr for n in ast.walk(block)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert "save" in attrs, (
            f"{module} 的 `__main__` 块里没有 `save(...)` 调用 —— 它已经不写那两份 PDF 了？"
            f"（这一块里见到的属性调用：{sorted(attrs)}）")
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
